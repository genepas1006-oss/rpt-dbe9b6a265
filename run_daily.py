"""エントリーポイント: 後場終了後の日次リサーチを実行する。"""

import argparse
from datetime import date, datetime, timedelta
from pathlib import Path

from analysis.earnings import compute_earnings_score, compute_short_earnings_score
from analysis.scoring import CandidateInput, rank_candidates
from analysis.technical import compute_short_technical_score, compute_technical_score
from analysis.market_calendar import next_business_day  # noqa: F401  (run_daily.next_business_day として参照される)
from analysis.consistency import resolve_direction_conflicts
from analysis.fundamental_comment import build_snapshot
from analysis.volatile_pool import select_volatile_pool
from analysis.miss_review import snapshot_to_json
from analysis.market_gaps import market_overnight_gaps, save_market_gaps
from config import NIKKEI225
from data_sources.yfinance_source import YFinanceSource
from report.build_site import build_index
from report.forecast_set import JST, evening_set
from tracking.virtual_fund import get_default_virtual_fund
from report.generate_report import generate_report
from report.notify import notify_windows
from report.publish import publish_docs
from tracking.benchmark import compute_missing_benchmarks, get_score_effect
from tracking.exit_sim import get_exit_stats
from tracking.payoff import get_payoff_stats
from tracking.evaluate import evaluate_pending_predictions
from tracking.refill import backfill_target_open, flag_anomalies, recompute_fills, repair_inconsistent_opens
from tracking.market import index_daily_returns
from tracking.intraday_db import evaluate_intraday_predictions
from tracking.miss_reviews import update_miss_reviews
from tracking.missed import get_missed_predictions
from tracking.previous import get_previous_results
from tracking.predictions_db import VOLATILE, get_market_order_stats, get_win_rate_stats, init_db, replace_predictions
from tracking.unfilled import get_unfilled_predictions

DB_PATH = "data/predictions.db"
REPORTS_DIR = Path("reports")
DOCS_DIR = Path("docs")
HISTORY_DAYS = 500
MARKET_GAPS_PATH = Path("data/market_gaps.json")
INDEX_LOOKBACK_DAYS = 45


MIN_DATA_RATIO = 0.5


class NoMarketData(RuntimeError):
    """対象日の株価がほとんど取得できない（市場前・休場日・取得失敗）。レポートを作らない。"""


def has_enough_market_data(loaded: int, universe: int) -> bool:
    """対象日の足が取れた銘柄が、全体の半分以上あるか。"""
    return universe > 0 and loaded / universe >= MIN_DATA_RATIO


class PublishError(RuntimeError):
    """レポートは生成できたが、GitHub Pagesへの公開に失敗した。"""


def next_earnings_days(earnings_dates: list[date], today: date) -> int | None:
    """次回の決算発表日まで（暦日）の日数。今日以降の発表日がなければNone。"""
    upcoming = [d for d in earnings_dates if d >= today]
    return (min(upcoming) - today).days if upcoming else None


def run(prediction_date: date) -> Path:
    Path("data").mkdir(exist_ok=True)
    REPORTS_DIR.mkdir(exist_ok=True)
    init_db(DB_PATH)

    source = YFinanceSource()

    # 不的中の原因分析（地合い）用に日経平均の前日比を取得する。取得できなくても処理は続ける
    index_bars = source.get_symbol_bars(
        "^N225", prediction_date - timedelta(days=INDEX_LOOKBACK_DAYS), prediction_date
    )
    evaluate_pending_predictions(
        DB_PATH, source, as_of=prediction_date, market_returns=index_daily_returns(index_bars)
    )
    try:  # 寄り枠・昼の予想（試験運用）の答え合わせ。大引けの確定後だけ判定する。失敗しても続ける
        evaluate_intraday_predictions(DB_PATH, source)
    except Exception as e:  # noqa: BLE001
        print(f"[intraday] 答え合わせに失敗しました: {e}")

    # 約定価格の補正（寄り値が有利なら寄り値で約定）を過去分にも反映する。失敗しても続ける
    try:
        repair_inconsistent_opens(DB_PATH)
        backfill_target_open(DB_PATH, source)
        recompute_fills(DB_PATH)
        flag_anomalies(DB_PATH)
        update_miss_reviews(DB_PATH)  # 外れた予想の検証メモ（過去分の後追いも含む）
    except Exception as e:  # noqa: BLE001
        print(f"[refill] 再計算に失敗しました: {e}")

    start = prediction_date - timedelta(days=HISTORY_DAYS)
    buy_candidates = []
    sell_candidates = []
    all_bars = {}
    all_earnings = {}
    for code, name in NIKKEI225:
        bars = source.get_daily_bars(code, start, prediction_date)
        if not bars or bars[-1].trade_date != prediction_date:
            # 対象日のデータが取れない銘柄はスキップする（1銘柄の欠損で全体を止めない）
            continue

        all_bars[code] = bars
        earnings_dates = source.get_earnings_dates(code)
        all_earnings[code] = earnings_dates
        today = bars[-1]

        buy_candidates.append(
            CandidateInput(
                code=code,
                name=name,
                close=today.close,
                open=today.open,
                high=today.high,
                low=today.low,
                volume=today.volume,
                technical=compute_technical_score(bars),
                earnings=compute_earnings_score(bars, earnings_dates),
            )
        )
        sell_candidates.append(
            CandidateInput(
                code=code,
                name=name,
                close=today.close,
                open=today.open,
                high=today.high,
                low=today.low,
                volume=today.volume,
                technical=compute_short_technical_score(bars),
                earnings=compute_short_earnings_score(bars, earnings_dates),
            )
        )

    if not has_enough_market_data(len(all_bars), len(NIKKEI225)):
        raise NoMarketData(
            f"{prediction_date.isoformat()}の株価を取得できた銘柄が{len(all_bars)}/{len(NIKKEI225)}件のため、"
            "レポートの生成と公開を中止しました（市場の取引前・休場日・取得失敗の可能性）。"
        )

    # 朝の環境認識（米国市場→想定ギャップ）の傾きを出すための、日本株全体の夜間ギャップの履歴。失敗しても続ける
    market_gaps = {}
    try:
        market_gaps = market_overnight_gaps(all_bars)
        save_market_gaps(MARKET_GAPS_PATH, market_gaps)
    except Exception as e:  # noqa: BLE001
        print(f"[market_gaps] 保存に失敗しました: {e}")

    # 同日の全銘柄平均（スコアの効果の目安）。失敗しても続ける
    try:
        compute_missing_benchmarks(DB_PATH, all_bars)
    except Exception as e:  # noqa: BLE001
        print(f"[benchmark] 計算に失敗しました: {e}")

    # 方向が矛盾する銘柄（買いにも売りにも載る等）を取り除いてから、上位を選ぶ
    consistent_buy, consistent_sell = resolve_direction_conflicts(buy_candidates, sell_candidates)
    ranked_buy = rank_candidates(consistent_buy, side="buy")
    ranked_sell = rank_candidates(consistent_sell, side="sell")
    target_date = next_business_day(prediction_date)

    # 候補10銘柄のファンダメンタル（コメント用の参考情報）。取得できない銘柄は従来のコメントにする
    fundamentals = {}
    for c in [*ranked_buy, *ranked_sell]:
        try:
            f = source.get_fundamentals(c.code)
        except Exception as e:  # noqa: BLE001
            print(f"[fundamentals] {c.code} の取得に失敗しました: {e}")
            f = None
        if f is not None:
            fundamentals[c.code] = f
    earnings_days = {
        code: next_earnings_days(all_earnings.get(code, []), prediction_date)
        for code in {c.code for c in [*ranked_buy, *ranked_sell]}
    }
    # 予測時の材料（ファンダメンタル・決算までの日数）を記録しておき、外れたときの分析で突き合わせる
    extras = {}
    for c in [*ranked_buy, *ranked_sell]:
        f = fundamentals.get(c.code)
        snapshot = snapshot_to_json(build_snapshot(f, c.day_close)) if f is not None else None
        extras[c.code] = (snapshot, earnings_days.get(c.code))

    # 予想セット（作成時刻・データ基準・有効期間）。夜の予想は、翌営業日の前場（9:00〜11:30）向け
    fset = evening_set(prediction_date, target_date, datetime.now(JST))
    replace_predictions(DB_PATH, prediction_date, target_date, "buy", ranked_buy, extras, forecast_set=fset)
    replace_predictions(DB_PATH, prediction_date, target_date, "sell", ranked_sell, extras, forecast_set=fset)

    # テスト枠（値動き重視・試験運用）: 当日値幅率の上位30%から選ぶ。本番とは別の区分で記録する。失敗しても続ける
    exp_buy, exp_sell = [], []
    try:
        pool_codes = {c.code for c in select_volatile_pool(buy_candidates)}
        exp_buy = rank_candidates([c for c in consistent_buy if c.code in pool_codes], side="buy")
        exp_sell = rank_candidates([c for c in consistent_sell if c.code in pool_codes], side="sell")
        replace_predictions(DB_PATH, prediction_date, target_date, "buy", exp_buy, variant=VOLATILE, forecast_set=fset)
        replace_predictions(DB_PATH, prediction_date, target_date, "sell", exp_sell, variant=VOLATILE, forecast_set=fset)
    except Exception as e:  # noqa: BLE001
        print(f"[volatile] テスト枠の作成に失敗しました: {e}")
        exp_buy, exp_sell = [], []

    buy_stats = get_win_rate_stats(DB_PATH, side="buy")
    sell_stats = get_win_rate_stats(DB_PATH, side="sell")
    report_text = generate_report(
        prediction_date,
        target_date,
        ranked_buy,
        ranked_sell,
        buy_stats,
        sell_stats,
        get_unfilled_predictions(DB_PATH, "buy"),
        get_unfilled_predictions(DB_PATH, "sell"),
        get_missed_predictions(DB_PATH, "buy"),
        get_missed_predictions(DB_PATH, "sell"),
        get_market_order_stats(DB_PATH, "buy"),
        get_market_order_stats(DB_PATH, "sell"),
        get_previous_results(DB_PATH, "buy", prediction_date),
        get_previous_results(DB_PATH, "sell", prediction_date),
        get_score_effect(DB_PATH, "buy"),
        get_score_effect(DB_PATH, "sell"),
        fundamentals=fundamentals,
        earnings_days=earnings_days,
        exp_buy_candidates=exp_buy,
        exp_sell_candidates=exp_sell,
        exp_buy_stats=get_win_rate_stats(DB_PATH, side="buy", variant=VOLATILE),
        exp_sell_stats=get_win_rate_stats(DB_PATH, side="sell", variant=VOLATILE),
        exp_buy_effect=get_score_effect(DB_PATH, "buy", VOLATILE),
        exp_sell_effect=get_score_effect(DB_PATH, "sell", VOLATILE),
        forecast_set=fset,
        buy_exit=get_exit_stats(DB_PATH, "buy"),
        sell_exit=get_exit_stats(DB_PATH, "sell"),
        exp_buy_exit=get_exit_stats(DB_PATH, "buy", VOLATILE),
        exp_sell_exit=get_exit_stats(DB_PATH, "sell", VOLATILE),
        buy_payoff=get_payoff_stats(DB_PATH, "buy"),
        sell_payoff=get_payoff_stats(DB_PATH, "sell"),
        index_return=index_daily_returns(index_bars).get(prediction_date),
    )

    report_path = REPORTS_DIR / f"{prediction_date.isoformat()}.md"
    report_path.write_text(report_text, encoding="utf-8")

    summary_parts = []
    if ranked_buy:
        summary_parts.append(
            "買い: " + " / ".join(f"{c.name}({c.entry_price:,.0f}円)" for c in ranked_buy[:3])
        )
    if ranked_sell:
        summary_parts.append(
            "売り: " + " / ".join(f"{c.name}({c.entry_price:,.0f}円)" for c in ranked_sell[:3])
        )
    top_summary = " ｜ ".join(summary_parts) if summary_parts else "本日は候補なし"
    notify_windows(
        "日本株リサーチレポート完了",
        f"{prediction_date.isoformat()}分: {top_summary}",
    )

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    build_index(REPORTS_DIR, DOCS_DIR, generated_at, market_gaps, get_default_virtual_fund(DB_PATH))
    result = publish_docs(Path(__file__).parent, f"docs: {prediction_date.isoformat()}レポート公開")
    print(f"[publish] {result.status}: {result.detail}")
    if not result.ok:
        notify_windows(
            "日本株リサーチ: 公開に失敗しました",
            f"{prediction_date.isoformat()}分のレポートはPCに保存済みですが、サイトに公開されていません。",
        )
        raise PublishError(result.detail)

    return report_path


def main():
    parser = argparse.ArgumentParser(description="日本株デイクローズ・リサーチを実行する")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="対象日（YYYY-MM-DD）。省略時は本日。",
    )
    args = parser.parse_args()

    prediction_date = (
        datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()
    )

    try:
        report_path = run(prediction_date)
    except NoMarketData as e:
        print(e)
        raise SystemExit(1)
    print(f"レポートを生成しました: {report_path}")


if __name__ == "__main__":
    main()
