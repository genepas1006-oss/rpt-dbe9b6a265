"""前営業日以前の予測を実データで答え合わせする。

承認済み（2026-11-06）: 対象日が祝日などで株価がない場合は、対象日以降で最初の取引日
（実行日以前に限る、最大 FALLBACK_DAYS 日先まで）の足で答え合わせし、予測の対象日を
実際に使った取引日に更新する。
"""

from datetime import date, timedelta

from data_sources.base import DataSource
from tracking.predictions_db import get_pending_predictions, record_evaluation


FALLBACK_DAYS = 7


def evaluate_pending_predictions(db_path: str, source: DataSource, as_of: date) -> int:
    """target_date <= as_of の未評価予測を実データで答え合わせする。

    対象日の実データが取得できない予測はスキップする（1件の失敗で全体を止めない）。
    戻り値は実際に評価できた件数。
    """
    pending = get_pending_predictions(db_path, as_of)
    evaluated_count = 0

    for p in pending:
        bars = source.get_daily_bars(
            p.code, p.target_date, p.target_date + timedelta(days=FALLBACK_DAYS)
        )
        # 実行日より先の足は使わない（将来のデータを見ない）
        eligible = [b for b in bars if p.target_date <= b.trade_date <= as_of]
        if not eligible:
            continue

        bar = min(eligible, key=lambda b: b.trade_date)
        record_evaluation(
            db_path,
            prediction_id=p.id,
            target_low=bar.low,
            target_high=bar.high,
            target_close=bar.close,
            actual_date=bar.trade_date,
        )
        evaluated_count += 1

    return evaluated_count
