"""tracking.evaluate のテスト。"""

from datetime import date

from analysis.scoring import RankedCandidate
from data_sources.base import DailyBar, DataSource
from tracking.evaluate import evaluate_pending_predictions
from tracking.predictions_db import get_win_rate_stats, init_db, save_predictions

PREDICTION_DATE = date(2026, 8, 21)
TARGET_DATE = date(2026, 8, 24)


class _FakeSource(DataSource):
    """テスト用の固定データを返すデータソース。"""

    def __init__(self, bars_by_code: dict[str, list[DailyBar]]):
        self._bars_by_code = bars_by_code

    def get_daily_bars(self, code, start, end):
        return [b for b in self._bars_by_code.get(code, []) if start <= b.trade_date <= end]

    def get_earnings_dates(self, code):
        return []


def _candidate(code: str, entry_price: float) -> RankedCandidate:
    return RankedCandidate(
        code=code,
        name=f"銘柄{code}",
        total_score=4,
        technical_score=2,
        earnings_score=2,
        volume_ratio=2.1,
        entry_price=entry_price,
        reasons=["テスト用"],
    )


def test_evaluate_pending_predictions_updates_db(tmp_path):
    db_path = str(tmp_path / "predictions.db")
    init_db(db_path)
    save_predictions(db_path, PREDICTION_DATE, TARGET_DATE, [_candidate("DDD", 1194.0)])

    source = _FakeSource(
        {
            "DDD": [
                DailyBar(
                    trade_date=TARGET_DATE,
                    open=1190,
                    high=1210,
                    low=1180,
                    close=1205,
                    volume=1000,
                )
            ]
        }
    )

    evaluated_count = evaluate_pending_predictions(db_path, source, as_of=TARGET_DATE)

    assert evaluated_count == 1
    stats = get_win_rate_stats(db_path)
    assert stats.filled_count == 1
    assert stats.win_count == 1


def test_evaluate_skips_when_data_missing(tmp_path):
    db_path = str(tmp_path / "predictions.db")
    init_db(db_path)
    save_predictions(db_path, PREDICTION_DATE, TARGET_DATE, [_candidate("DDD", 1194.0)])

    source = _FakeSource({})  # DDDのデータが一切取得できないケース

    evaluated_count = evaluate_pending_predictions(db_path, source, as_of=TARGET_DATE)

    assert evaluated_count == 0
    stats = get_win_rate_stats(db_path)
    assert stats.total_predictions == 0
