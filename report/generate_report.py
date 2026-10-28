"""Markdownレポート生成。

断定的な勝率保証表現は使わず、スコア・根拠・デモ検証の実績値を提示するのみとする
（CLAUDE.md記載の方針）。

2026-10-26: 買い候補・売り（ショート）候補の2セクション構成に変更。
2026-10-26: 各候補に当日の値動き（寄り・高値・安値・引け・出来高）と
    ワンポイント要約を追加。
"""

from datetime import date

from analysis.scoring import RankedCandidate
from report.one_point_summary import build_one_point_summary, build_outlook
from tracking.predictions_db import WinRateStats


def _stats_lines(stats: WinRateStats) -> list[str]:
    lines = [
        f"- 答え合わせ済み予測数: {stats.total_predictions}件",
        f"- 指値約定数: {stats.filled_count}件"
        f"（不成立: {stats.total_predictions - stats.filled_count}件）",
    ]
    if stats.win_rate is None:
        lines.append("- 的中率（約定分のみ）: データなし")
    else:
        lines.append(f"- 的中率（約定分のみ）: {stats.win_rate * 100:.1f}%")
    return lines


def _candidate_section(
    heading: str, candidates: list[RankedCandidate], empty_message: str
) -> list[str]:
    lines = ["", heading, ""]
    if not candidates:
        lines.append(empty_message)
    else:
        for rank, c in enumerate(candidates, start=1):
            lines.append(f"### {rank}位 {c.name}（{c.code}） - スコア{c.total_score}点")
            lines.append(
                f"- 内訳: 値動き・出来高{c.technical_score}点 / 決算パターン{c.earnings_score}点"
            )
            lines.append(f"- 参考指値: {c.entry_price:,.1f}円")
            if c.reasons:
                lines.append(f"- 根拠: {' / '.join(c.reasons)}")
            lines.append(
                f"- 当日の値動き: 始値{c.day_open:,.1f}円 / 高値{c.day_high:,.1f}円 / "
                f"安値{c.day_low:,.1f}円 / 終値{c.day_close:,.1f}円 / "
                f"出来高{c.day_volume:,.0f}株"
            )
            summary = build_one_point_summary(
                c.day_open, c.day_high, c.day_low, c.day_close, c.volume_ratio
            )
            outlook = build_outlook(c.side, c.day_high, c.day_low, c.day_close, c.volume_ratio)
            lines.append(f"- ワンポイント: {summary} 明日の見通し: {outlook}")
            lines.append("")
    return lines


def generate_report(
    prediction_date: date,
    target_date: date,
    buy_candidates: list[RankedCandidate],
    sell_candidates: list[RankedCandidate],
    buy_stats: WinRateStats,
    sell_stats: WinRateStats,
) -> str:
    lines = [
        f"# 日本株デイクローズ・リサーチレポート {prediction_date.isoformat()}",
        "",
        "**注意: 本レポートは根拠付きスコアリングによる分析結果であり、"
        "翌日の値動きや勝率を保証するものではありません。実発注は行っていません"
        "（デモ検証フェーズ）。**",
        "",
        "## デモ検証成績（買い・現時点までの累計）",
        *_stats_lines(buy_stats),
        "",
        "## デモ検証成績（売り・現時点までの累計）",
        *_stats_lines(sell_stats),
    ]

    lines += _candidate_section(
        f"## 本日の買い候補（{target_date.isoformat()}向け・参考指値）",
        buy_candidates,
        "本日は基準（スコア>0）を満たす買い候補がありませんでした。",
    )
    lines += _candidate_section(
        f"## 本日の売り候補（{target_date.isoformat()}向け・参考指値）",
        sell_candidates,
        "本日は基準（スコア>0）を満たす売り候補がありませんでした。",
    )

    return "\n".join(lines)
