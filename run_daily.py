"""エントリーポイント: 後場終了後の日次リサーチを実行する。"""

import argparse
from datetime import date, datetime, timedelta
from pathlib import Path

from analysis.earnings import compute_earnings_score, compute_short_earnings_score
from analysis.scoring import CandidateInput, rank_candidates
from analysis.technical import compute_short_technical_score, compute_technical_score
from analysis.market_gaps import market_overnight_gaps, save_market_gaps
from config import NIKKEI225
from data_sources.yfinance_source import YFinanceSource
from report.build_site import build_index
from tracking.virtual_fund import get_default_virtual_fund
from report.generate_report import generate_report
from report.notify import notify_windows
from report.publish import publish_docs
from tracking.benchmark import compute_missing_benchmarks, get_score_effect
from tracking.evaluate import evaluate_pending_predictions
from tracking.refill import backfill_target_open, recompute_fills, repair_inconsistent_opens
from tracking.market import index_daily_returns
from tracking.missed import get_missed_predictions
from tracking.previous import get_previous_results
from tracking.predictions_db import get_market_order_stats, get_win_rate_stats, init_db, replace_predictions
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


def next_business_day(d: date) -> date:
    """土日をスキップした翌営業日を返す（日本の祝日は考慮していない・既知の簡略化）。"""
    next_day = d + timedelta(days=1)
    while next_day.weekday() >= 5:  # 5=土, 6=日
        next_day += timedelta(days=1)
    return next_day


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

    # 約定価格の補正（寄り値が有利なら寄り値で約定）を過去分にも反映する。失敗しても続ける
    try:
        repair_inconsistent_opens(DB_PATH)
        backfill_target_open(DB_PATH, source)
        recompute_fills(DB_PATH)
    except Exception as e:  # noqa: BLE001
        print(f"[refill] 再計算に失敗しました: {e}")

    start = prediction_date - timedelta(days=HISTORY_DAYS)
    buy_candidates = []
    sell_candidates = []
    all_bars = {}
    for code, name in NIKKEI225:
        bars = source.get_daily_bars(code, start, prediction_date)
        if not bars or bars[-1].trade_date != prediction_date:
            # 対象日のデータが取れない銘柄はスキップする（1銘柄の欠損で全体を止めない）
            continue

        all_bars[code] = bars
        earnings_dates = source.get_earnings_dates(code)
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

    ranked_buy = rank_candidates(buy_candidates, side="buy")
    ranked_sell = rank_candidates(sell_candidates, side="sell")
    target_date = next_business_day(prediction_date)

    replace_predictions(DB_PATH, prediction_date, target_date, "buy", ranked_buy)
    replace_predictions(DB_PATH, prediction_date, target_date, "sell", ranked_sell)

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
