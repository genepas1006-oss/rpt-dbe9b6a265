"""前営業日以前の予測を実データで答え合わせする。"""

from datetime import date

from data_sources.base import DataSource
from tracking.predictions_db import get_pending_predictions, record_evaluation


def evaluate_pending_predictions(db_path: str, source: DataSource, as_of: date) -> int:
    """target_date <= as_of の未評価予測を実データで答え合わせする。

    対象日の実データが取得できない予測はスキップする（1件の失敗で全体を止めない）。
    戻り値は実際に評価できた件数。
    """
    pending = get_pending_predictions(db_path, as_of)
    evaluated_count = 0

    for p in pending:
        bars = source.get_daily_bars(p.code, p.target_date, p.target_date)
        matching = [b for b in bars if b.trade_date == p.target_date]
        if not matching:
            continue

        bar = matching[0]
        record_evaluation(
            db_path,
            prediction_id=p.id,
            target_low=bar.low,
            target_high=bar.high,
            target_close=bar.close,
        )
        evaluated_count += 1

    return evaluated_count
