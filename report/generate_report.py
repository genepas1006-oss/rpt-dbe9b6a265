"""Markdownレポート生成。

断定的な勝率保証表現は使わず、スコア・根拠・デモ検証の実績値を提示するのみとする
（CLAUDE.md記載の方針）。

2026-10-26: 買い候補・売り（ショート）候補の2セクション構成に変更。
2026-10-26: 各候補に当日の値動き（寄り・高値・安値・引け・出来高）と
    ワンポイント要約を追加。
"""

from datetime import date

from analysis.scoring import RankedCandidate
from data_sources.base import Fundamentals
from report.forecast_set import ForecastSet, to_md_lines
from report.one_point_summary import (
    build_one_point_summary,
    build_one_point_with_fundamentals,
    build_outlook,
    build_outlook_with_fundamentals,
)
from tracking.predictions_db import MarketOrderStats, WinRateStats
from tracking.missed import MissedPrediction
from tracking.previous import STATUS_LABEL, STATUS_ORDER, PreviousResults
from tracking.benchmark import ScoreEffect
from tracking.exit_sim import ExitStats
from tracking.payoff import PayoffStats, excursions
from analysis.card_explain import (
    MAX_SCORE, close_position, reason_sentence, relative_strength_text, round_level_text, score_rows,
)
from analysis.fundamental_comment import build_fundamental_outlook, build_fundamental_sentence, earnings_notice
from config import COST_RATE
from tracking.unfilled import UnfilledPrediction


def _stats_lines(stats: WinRateStats, market: MarketOrderStats | None = None) -> list[str]:
    """成績欄。見出しの的中率は、始値→終値の方向（約定の有無を問わない。2026-11-11承認・段階A）。"""
    lines = []
    if market is not None:
        if market.count == 0 or market.win_rate is None:
            lines.append("- 的中率（始値→終値の方向）: データなし")
        else:
            lines.append(f"- 的中率（始値→終値の方向）: {market.win_rate * 100:.1f}%（{market.count}件）")
    lines += [
        f"- 答え合わせ済み予測数: {stats.total_predictions}件",
        f"- 指値約定数: {stats.filled_count}件"
        f"（不成立: {stats.total_predictions - stats.filled_count}件）",
    ]
    if stats.win_rate is None:
        lines.append("- 指値で約定した場合の的中率（参考）: データなし")
    else:
        lines.append(
            f"- 指値で約定した場合の的中率（参考）: {stats.win_rate * 100:.1f}%"
            f"（{stats.win_count}/{stats.filled_count}件）"
        )
    if stats.direction_total:
        lines.append(
            f"- 方向の的中率（予測日終値比）: {stats.direction_hits / stats.direction_total * 100:.1f}%"
            f"（{stats.direction_hits}/{stats.direction_total}件）"
        )
    if stats.excluded_count:
        lines.append(f"- データ異常で除外（株式分割の疑い）: {stats.excluded_count}件")
    return lines


def _score_effect_lines(effect: ScoreEffect | None) -> list[str]:
    """TOP5と同日の全銘柄平均の差。優位性の証明ではなく、スコアの効果の目安として出す。"""
    if effect is None:
        return []
    return [
        f"- 全銘柄平均との差（スコアの効果の目安・指値で約定した場合）: {effect.excess * 100:+.2f}%"
        f"（TOP5 {effect.top_avg * 100:+.2f}% / 全銘柄 {effect.bench_avg * 100:+.2f}%・{effect.days}日）"
    ]


def _market_order_lines(stats: MarketOrderStats | None) -> list[str]:
    """指値で約定した場合の平均リターン（同じ予測）。始値→終値の的中率と平均リターンは、成績欄の見出し・損益比の行に移した。"""
    if stats is None or stats.count == 0 or stats.limit_avg_return is None:
        return []
    return [f"- 指値の平均リターン（同じ予測・約定分）: {stats.limit_avg_return * 100:+.2f}%"]


def _payoff_lines(stats: PayoffStats | None) -> list[str]:
    """勝ったときの平均利益・負けたときの平均損失・損益比。平均値の差だけでは分からない勝ち負けの形を示す。"""
    if stats is None:
        return []
    win = "なし" if stats.avg_win is None else f"{stats.avg_win * 100:+.2f}%"
    if stats.avg_loss is None:
        loss = "なし"
    elif stats.avg_loss == 0:
        loss = "0.00%"
    else:
        loss = f"-{stats.avg_loss * 100:.2f}%"
    ratio = "算出不可" if stats.payoff_ratio is None else f"{stats.payoff_ratio:.2f}"
    return [
        f"- 平均利益（始値→終値・勝った場合のリターン）: {win}（{stats.wins}件）",
        f"- 平均損失（始値→終値・負けた場合のリターン）: {loss}（{stats.losses}件）",
        f"- 損益比（平均利益÷平均損失）: {ratio}",
        f"- 1件あたりの平均リターン（始値→終値）: {stats.avg_return * 100:+.2f}%",
    ]


def _exit_lines(stats: list[ExitStats] | None, cost_rate: float = COST_RATE) -> list[str]:
    """利確・損切りを使った場合の試算。日足からの計算なので、日中の値動きの順序は反映されない。"""
    if not stats or all(s.count == 0 for s in stats):
        return []
    note = "試算・手数料込み" if cost_rate > 0 else "試算"
    lines = []
    for s in stats:
        if s.count == 0 or s.avg_return is None:
            continue
        lines.append(
            f"- 利確{s.take_profit * 100:g}%・損切り{s.stop_loss * 100:g}%の平均リターン（{note}）: "
            f"{s.avg_return * 100:+.2f}%"
            f"（的中 {s.win_rate * 100:.1f}%・約定{s.count}件・利確{s.tp_count}/損切り{s.sl_count}/"
            f"終値{s.close_count}・判定不能{s.ambiguous_count}件）"
        )
    return lines


def _previous_section(side_label: str, prev: PreviousResults | None) -> list[str]:
    """前営業日の予想とその結果。成績（累計）の直後、本日の候補の前に置く。"""
    if prev is None or not prev.items:
        return []
    counts = prev.counts()
    summary = "・".join(f"{STATUS_LABEL[s]}{counts[s]}" for s in STATUS_ORDER)
    lines = [
        "",
        f"## 前営業日の結果（{side_label}）",
        "",
        f"- 対象: {prev.prediction_date.isoformat()}予測 → {prev.target_date.isoformat()} | {summary}",
    ]
    for i in prev.items:
        ret = "-" if i.result_return is None else f"{i.result_return * 100:+.2f}%"
        oc = "-" if i.oc_return is None else f"{i.oc_return * 100:+.2f}%"
        move = (
            "-"
            if i.target_open is None or i.target_close is None
            else f"始値{i.target_open:,.1f}円 → 終値{i.target_close:,.1f}円"
        )
        fp = i.fill_price
        entry = f"{i.entry_price:,.1f}円" + (
            f"（約定{fp:,.1f}円）" if fp is not None and abs(fp - i.entry_price) > 1e-9 else ""
        )
        lines.append(
            f"- {i.rank}位 | {i.name}（{i.code}） | {STATUS_LABEL[i.status]} | "
            f"{entry} | {ret} | {move} | {oc}" + (f" | {i.note}" if i.note else "")
        )
        lines += [f"  - {t}" for t in i.explain_lines()]
    return lines


def _unfilled_section(side_label: str, unfilled: list[UnfilledPrediction]) -> list[str]:
    if not unfilled:
        return []
    lines = ["", f"## 不成立の履歴（{side_label}）", ""]
    for u in unfilled:
        lines.append(
            f"- {u.prediction_date.isoformat()} | {u.target_date.isoformat()} | "
            f"{u.name}（{u.code}） | {u.entry_price:,.1f}円 | {u.reason}"
        )
    return lines


def _missed_section(side_label: str, missed: list[MissedPrediction]) -> list[str]:
    if not missed:
        return []
    lines = ["", f"## 不的中の履歴（{side_label}）", ""]
    for m in missed:
        lines.append(
            f"- {m.prediction_date.isoformat()} | {m.target_date.isoformat()} | "
            f"{m.name}（{m.code}） | {m.entry_price:,.1f}円 | {m.result_return * 100:+.2f}% | "
            f"{'・'.join(m.causes)} | {m.detail}" + (f" | {m.review}" if m.review else "")
        )
    return lines


def _candidate_section(
    heading: str,
    candidates: list[RankedCandidate],
    empty_message: str,
    fundamentals: dict[str, Fundamentals] | None = None,
    earnings_days: dict[str, int | None] | None = None,
    index_return: float | None = None,
) -> list[str]:
    lines = ["", heading, ""]
    if not candidates:
        lines.append(empty_message)
    else:
        for rank, c in enumerate(candidates, start=1):
            pos = close_position(c.day_high, c.day_low, c.day_close)
            rows = score_rows(c.side, c.volume_ratio, c.daily_return, pos, c.earnings_score)
            lines.append(f"### {rank}位 {c.name}（{c.code}） - スコア{c.total_score}点")
            lines.append(
                f"- 内訳: 値動き・出来高{c.technical_score}点 / 決算パターン{c.earnings_score}点"
            )
            lines += [f"- 採点: {r.to_md()}" for r in rows]
            lines.append(f"- 参考指値: {c.entry_price:,.1f}円")
            if c.reasons:
                lines.append(f"- 根拠: {' / '.join(c.reasons)}")
            lines.append(
                f"- 当日の値動き: 始値{c.day_open:,.1f}円 / 高値{c.day_high:,.1f}円 / "
                f"安値{c.day_low:,.1f}円 / 終値{c.day_close:,.1f}円 / "
                f"出来高{c.day_volume:,.0f}株 / 引け位置{pos:.2f}（値幅の下から{pos * 100:.0f}%）"
            )
            reason = reason_sentence(c.side, rows)
            if reason:
                lines.append(f"- 候補の理由: {reason}")
            f = (fundamentals or {}).get(c.code)
            watch = [
                relative_strength_text(c.daily_return, index_return),
                round_level_text(c.day_close),
                earnings_notice((earnings_days or {}).get(c.code)),
            ]
            lines += [f"- 気をつける点: {w}" for w in watch if w]
            if f is not None:
                ref = (build_fundamental_sentence(f, c.day_close) or "") + (
                    build_fundamental_outlook(f, c.day_close, c.side) or ""
                )
                if ref:
                    lines.append(f"- 参考（業績・割安度）: {ref}")
            lines.append("")
    return lines


def generate_report(
    prediction_date: date,
    target_date: date,
    buy_candidates: list[RankedCandidate],
    sell_candidates: list[RankedCandidate],
    buy_stats: WinRateStats,
    sell_stats: WinRateStats,
    buy_unfilled: list[UnfilledPrediction] | None = None,
    sell_unfilled: list[UnfilledPrediction] | None = None,
    buy_missed: list[MissedPrediction] | None = None,
    sell_missed: list[MissedPrediction] | None = None,
    buy_market: MarketOrderStats | None = None,
    sell_market: MarketOrderStats | None = None,
    buy_previous: PreviousResults | None = None,
    sell_previous: PreviousResults | None = None,
    buy_effect: ScoreEffect | None = None,
    sell_effect: ScoreEffect | None = None,
    fundamentals: dict[str, Fundamentals] | None = None,
    earnings_days: dict[str, int | None] | None = None,
    exp_buy_candidates: list[RankedCandidate] | None = None,
    exp_sell_candidates: list[RankedCandidate] | None = None,
    exp_buy_stats: WinRateStats | None = None,
    exp_sell_stats: WinRateStats | None = None,
    exp_buy_effect: ScoreEffect | None = None,
    exp_sell_effect: ScoreEffect | None = None,
    forecast_set: ForecastSet | None = None,
    buy_exit: list[ExitStats] | None = None,
    sell_exit: list[ExitStats] | None = None,
    exp_buy_exit: list[ExitStats] | None = None,
    exp_sell_exit: list[ExitStats] | None = None,
    exp_buy_market: MarketOrderStats | None = None,
    exp_sell_market: MarketOrderStats | None = None,
    buy_payoff: PayoffStats | None = None,
    sell_payoff: PayoffStats | None = None,
    index_return: float | None = None,
) -> str:
    set_lines = to_md_lines(forecast_set) if forecast_set else []
    lines = [
        f"# 日本株デイクローズ・リサーチレポート {prediction_date.isoformat()}",
        "",
        "**注意: 本レポートは根拠付きスコアリングによる分析結果であり、"
        "翌日の値動きや勝率を保証するものではありません。実発注は行っていません"
        "（デモ検証フェーズ）。**",
        "",
        *set_lines,
        "## デモ検証成績（買い・現時点までの累計）",
        *_stats_lines(buy_stats, buy_market),
        *_payoff_lines(buy_payoff),
        *_score_effect_lines(buy_effect),
        *_market_order_lines(buy_market),
        *_exit_lines(buy_exit),
        "",
        "## デモ検証成績（売り・現時点までの累計）",
        *_stats_lines(sell_stats, sell_market),
        *_payoff_lines(sell_payoff),
        *_score_effect_lines(sell_effect),
        *_market_order_lines(sell_market),
        *_exit_lines(sell_exit),
    ]
    lines += _previous_section("買い", buy_previous)
    lines += _previous_section("売り", sell_previous)
    lines += _unfilled_section("買い", buy_unfilled or [])
    lines += _unfilled_section("売り", sell_unfilled or [])
    lines += _missed_section("買い", buy_missed or [])
    lines += _missed_section("売り", sell_missed or [])

    lines += _candidate_section(
        f"## 本日の買い候補（{target_date.isoformat()}向け・参考指値）",
        buy_candidates,
        "本日は基準（スコア>0）を満たす買い候補がありませんでした。",
        fundamentals,
        earnings_days,
        index_return=index_return,
    )
    lines += _candidate_section(
        f"## 本日の売り候補（{target_date.isoformat()}向け・参考指値）",
        sell_candidates,
        "本日は基準（スコア>0）を満たす売り候補がありませんでした。",
        fundamentals,
        earnings_days,
        index_return=index_return,
    )

    # テスト枠（値動き重視・試験運用）。本番の成績・仮想資金には含めない
    if exp_buy_candidates or exp_sell_candidates:
        for label, stats, effect, exits, mkt in (
            ("買い", exp_buy_stats, exp_buy_effect, exp_buy_exit, exp_buy_market),
            ("売り", exp_sell_stats, exp_sell_effect, exp_sell_exit, exp_sell_market),
        ):
            if stats is not None:
                lines += [
                    "",
                    f"## テスト枠の成績（{label}・値動き重視）",
                    *_stats_lines(stats, mkt),
                    *_score_effect_lines(effect),
                    *_exit_lines(exits),
                ]
        lines += _candidate_section(
            f"## テスト枠の買い候補（{target_date.isoformat()}向け・値動き重視）",
            exp_buy_candidates or [],
            "テスト枠に該当する買い候補がありませんでした。",
            index_return=index_return,
        )
        lines += _candidate_section(
            f"## テスト枠の売り候補（{target_date.isoformat()}向け・値動き重視）",
            exp_sell_candidates or [],
            "テスト枠に該当する売り候補がありませんでした。",
            index_return=index_return,
        )

    return "\n".join(lines)
