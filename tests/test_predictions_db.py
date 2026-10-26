"""tracking.predictions_db のテスト。

承認済みのサンプルデータ手計算（2026-08-21合意分、DDD=約定/AAA=不成立の例）を
テストケース化する。
"""

from datetime import date

from analysis.scoring import RankedCandidate
from tracking.predictions_db import (
    get_pending_predictions,
    get_win_rate_stats,
    init_db,
    record_evaluation,
    save_predictions,
)

PREDICTION_DATE = date(2026, 8, 21)
TARGET_DATE = date(2026, 8, 24)


def _candidate(code: str, entry_price: float, side: str = "buy") -> RankedCandidate:
    return RankedCandidate(
        code=code,
        name=f"銘柄{code}",
        total_score=4,
        technical_score=2,
        earnings_score=2,
        volume_ratio=2.1,
        entry_price=entry_price,
        reasons=["テスト用"],
        side=side,
    )


def test_filled_and_win_case(tmp_path):
    db_path = str(tmp_path / "predictions.db")
    init_db(db_path)
    save_predictions(db_path, PREDICTION_DATE, TARGET_DATE, [_candidate("DDD", 1194.0)])

    [pending] = get_pending_predictions(db_path, TARGET_DATE)
    record_evaluation(
        db_path,
        prediction_id=pending.id,
        target_low=1180.0,
        target_high=1210.0,
        target_close=1205.0,
    )

    stats = get_win_rate_stats(db_path)
    assert stats.total_predictions == 1
    assert stats.filled_count == 1
    assert stats.win_count == 1
    assert stats.win_rate == 1.0
    assert get_pending_predictions(db_path, TARGET_DATE) == []


def test_not_filled_case(tmp_path):
    db_path = str(tmp_path / "predictions.db")
    init_db(db_path)
    save_predictions(db_path, PREDICTION_DATE, TARGET_DATE, [_candidate("AAA", 2985.0)])

    [pending] = get_pending_predictions(db_path, TARGET_DATE)
    record_evaluation(
        db_path,
        prediction_id=pending.id,
        target_low=2990.0,
        target_high=3050.0,
        target_close=3020.0,
    )

    stats = get_win_rate_stats(db_path)
    assert stats.total_predictions == 1
    assert stats.filled_count == 0
    assert stats.win_count == 0
    assert stats.win_rate is None


def test_win_rate_aggregates_multiple_predictions(tmp_path):
    db_path = str(tmp_path / "predictions.db")
    init_db(db_path)
    save_predictions(
        db_path, PREDICTION_DATE, TARGET_DATE, [_candidate("DDD", 1194.0), _candidate("AAA", 2985.0)]
    )

    pending = get_pending_predictions(db_path, TARGET_DATE)
    by_code = {p.code: p for p in pending}
    record_evaluation(db_path, by_code["DDD"].id, target_low=1180.0, target_high=1210.0, target_close=1205.0)
    record_evaluation(db_path, by_code["AAA"].id, target_low=2990.0, target_high=3050.0, target_close=3020.0)

    stats = get_win_rate_stats(db_path)
    assert stats.total_predictions == 2
    assert stats.filled_count == 1
    assert stats.win_count == 1
    assert stats.win_rate == 1.0


def test_get_pending_predictions_excludes_future_target_dates(tmp_path):
    db_path = str(tmp_path / "predictions.db")
    init_db(db_path)
    save_predictions(db_path, PREDICTION_DATE, TARGET_DATE, [_candidate("DDD", 1194.0)])

    pending = get_pending_predictions(db_path, PREDICTION_DATE)

    assert pending == []


def test_sell_side_filled_and_win_case(tmp_path):
    # 売り指値974.9円、翌営業日高値980円(>=974.9で約定)、終値960円(下落)→的中
    db_path = str(tmp_path / "predictions.db")
    init_db(db_path)
    save_predictions(
        db_path, PREDICTION_DATE, TARGET_DATE, [_candidate("EEE", 974.9, side="sell")]
    )

    [pending] = get_pending_predictions(db_path, TARGET_DATE)
    assert pending.side == "sell"
    record_evaluation(
        db_path, prediction_id=pending.id, target_low=955.0, target_high=980.0, target_close=960.0
    )

    stats = get_win_rate_stats(db_path, side="sell")
    assert stats.filled_count == 1
    assert stats.win_count == 1
    assert round(stats.win_rate, 4) == 1.0


def test_sell_side_filled_and_loss_case(tmp_path):
    # 売り指値974.9円で約定したが、終値980円(上昇)→不的中
    db_path = str(tmp_path / "predictions.db")
    init_db(db_path)
    save_predictions(
        db_path, PREDICTION_DATE, TARGET_DATE, [_candidate("FFF", 974.9, side="sell")]
    )

    [pending] = get_pending_predictions(db_path, TARGET_DATE)
    record_evaluation(
        db_path, prediction_id=pending.id, target_low=970.0, target_high=985.0, target_close=980.0
    )

    stats = get_win_rate_stats(db_path, side="sell")
    assert stats.filled_count == 1
    assert stats.win_count == 0


def test_win_rate_stats_filters_by_side(tmp_path):
    db_path = str(tmp_path / "predictions.db")
    init_db(db_path)
    save_predictions(
        db_path,
        PREDICTION_DATE,
        TARGET_DATE,
        [_candidate("DDD", 1194.0, side="buy"), _candidate("EEE", 974.9, side="sell")],
    )

    pending = get_pending_predictions(db_path, TARGET_DATE)
    by_code = {p.code: p for p in pending}
    record_evaluation(db_path, by_code["DDD"].id, target_low=1180.0, target_high=1210.0, target_close=1205.0)
    record_evaluation(db_path, by_code["EEE"].id, target_low=955.0, target_high=980.0, target_close=960.0)

    assert get_win_rate_stats(db_path).filled_count == 2
    assert get_win_rate_stats(db_path, side="buy").filled_count == 1
    assert get_win_rate_stats(db_path, side="sell").filled_count == 1
