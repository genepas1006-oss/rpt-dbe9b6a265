"""エントリーポイント: 後場終了後の日次リサーチを実行する。"""

import argparse
from datetime import date, datetime, timedelta
from pathlib import Path

from analysis.earnings import compute_earnings_score
from analysis.scoring import CandidateInput, rank_candidates
from analysis.technical import compute_technical_score
from config import NIKKEI225
from data_sources.yfinance_source import YFinanceSource
from report.generate_report import generate_report
from report.notify import notify_windows
from tracking.evaluate import evaluate_pending_predictions
from tracking.predictions_db import get_win_rate_stats, init_db, save_predictions

DB_PATH = "data/predictions.db"
REPORTS_DIR = Path("reports")
HISTORY_DAYS = 500


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

    evaluate_pending_predictions(DB_PATH, source, as_of=prediction_date)

    start = prediction_date - timedelta(days=HISTORY_DAYS)
    candidates = []
    for code, name in NIKKEI225:
        bars = source.get_daily_bars(code, start, prediction_date)
        if not bars or bars[-1].trade_date != prediction_date:
            # 対象日のデータが取れない銘柄はスキップする（1銘柄の欠損で全体を止めない）
            continue

        earnings_dates = source.get_earnings_dates(code)
        technical = compute_technical_score(bars)
        earnings = compute_earnings_score(bars, earnings_dates)

        candidates.append(
            CandidateInput(
                code=code,
                name=name,
                close=bars[-1].close,
                technical=technical,
                earnings=earnings,
            )
        )

    ranked = rank_candidates(candidates)
    target_date = next_business_day(prediction_date)

    if ranked:
        save_predictions(DB_PATH, prediction_date, target_date, ranked)

    stats = get_win_rate_stats(DB_PATH)
    report_text = generate_report(prediction_date, target_date, ranked, stats)

    report_path = REPORTS_DIR / f"{prediction_date.isoformat()}.md"
    report_path.write_text(report_text, encoding="utf-8")

    if ranked:
        top_summary = " / ".join(f"{c.name}({c.entry_price:,.0f}円)" for c in ranked[:3])
    else:
        top_summary = "本日は候補なし"
    notify_windows(
        "日本株リサーチレポート完了",
        f"{prediction_date.isoformat()}分: {top_summary}",
    )

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

    report_path = run(prediction_date)
    print(f"レポートを生成しました: {report_path}")


if __name__ == "__main__":
    main()
