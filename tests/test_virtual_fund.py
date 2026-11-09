"""tracking.virtual_fund のテスト（承認済みの手計算ケース、2026-11-09）。"""

import sqlite3
from datetime import date

import pytest

from tracking.predictions_db import init_db
from tracking.virtual_fund import get_virtual_fund

START = date(2026, 11, 9)


def _insert(db, pred_date, target_date, side, filled, ret, evaluated=1):
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO predictions (prediction_date, code, name, side, total_score, technical_score, "
        "earnings_score, entry_price, reasons, target_date, evaluated, filled, result_return, created_at) "
        "VALUES (?, 'X', 'X', ?, 1, 1, 0, 100, '[]', ?, ?, ?, ?, 'now')",
        (pred_date, side, target_date, evaluated, None if not evaluated else int(filled), ret),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.db")
    init_db(path)
    return path


def _day1(db):
    for side, filled, ret in [
        ("buy", 1, 0.02), ("buy", 1, -0.01), ("buy", 0, None), ("buy", 1, 0.005), ("buy", 0, None),
        ("sell", 1, 0.03), ("sell", 1, -0.025), ("sell", 0, None), ("sell", 1, -0.004), ("sell", 0, None),
    ]:
        _insert(db, "2026-11-09", "2026-11-10", side, filled, ret)


def test_case1_first_day(db):
    _day1(db)
    fund = get_virtual_fund(db, START, 1_000_000, 10)
    d = fund.days[0]
    assert d.pnl == pytest.approx(1600)
    assert d.buy_pnl == pytest.approx(1500)
    assert d.sell_pnl == pytest.approx(100)
    assert d.filled_count == 6
    assert fund.balance == pytest.approx(1_001_600)
    assert d.pnl_pct == pytest.approx(0.0016)
    assert fund.total_pct == pytest.approx(0.0016)


def test_case2_compounding_second_day(db):
    _day1(db)
    _insert(db, "2026-11-10", "2026-11-11", "buy", 1, -0.05)
    for _ in range(9):
        _insert(db, "2026-11-10", "2026-11-11", "sell", 0, None)
    fund = get_virtual_fund(db, START, 1_000_000, 10)
    d = fund.days[1]
    assert d.start_balance == pytest.approx(1_001_600)
    assert d.pnl == pytest.approx(-5008)
    assert d.pnl_pct == pytest.approx(-0.005)
    assert fund.balance == pytest.approx(996_592)
    assert fund.total_pnl == pytest.approx(-3408)
    assert fund.total_pct == pytest.approx(-0.00340800)  # -0.34%


def test_case3_pending_day_is_excluded(db):
    _day1(db)
    _insert(db, "2026-11-10", "2026-11-11", "buy", 0, None, evaluated=0)
    fund = get_virtual_fund(db, START, 1_000_000, 10)
    assert len(fund.days) == 1
    assert fund.balance == pytest.approx(1_001_600)


def test_case4_all_unfilled_day_is_zero(db):
    for side in ("buy", "sell"):
        _insert(db, "2026-11-09", "2026-11-10", side, 0, None)
    fund = get_virtual_fund(db, START, 1_000_000, 10)
    assert fund.days[0].pnl == 0
    assert fund.days[0].pnl_pct == 0
    assert fund.balance == 1_000_000


def test_case5_no_confirmed_days(db):
    _insert(db, "2026-11-09", "2026-11-10", "buy", 0, None, evaluated=0)
    fund = get_virtual_fund(db, START, 1_000_000, 10)
    assert fund.days == []
    assert fund.last_day is None
    assert fund.balance == 1_000_000
    assert fund.total_pnl == 0


def test_predictions_before_start_date_are_ignored(db):
    _insert(db, "2026-11-06", "2026-11-09", "buy", 1, 0.10)
    fund = get_virtual_fund(db, START, 1_000_000, 10)
    assert fund.days == []
