"""手数料込みリターンと利確・損切り試算のテスト（2026-11-11承認の手計算ケース）。"""

import sqlite3

import pytest

from report.generate_report import _exit_lines
from tracking.exit_sim import ExitStats, apply_cost, get_exit_stats, simulate_exit
from tracking.predictions_db import init_db

COST = 0.001


# --- A. 手数料込みリターン（往復0.10%） ---
@pytest.mark.parametrize(
    "gross, net, win",
    [(0.015, 0.014, True), (0.0005, -0.0005, False), (-0.005, -0.006, False)],
)
def test_a_cost(gross, net, win):
    result = apply_cost(gross, COST)
    assert result == pytest.approx(net)
    assert (result > 0) is win


def test_a4_unfilled_stays_none():
    assert apply_cost(None, COST) is None


def test_zero_cost_is_noop():
    assert apply_cost(0.0123, 0.0) == pytest.approx(0.0123)


# --- B. 利確2%・損切り1% ---
@pytest.mark.parametrize(
    "side, fill, high, low, close, ret, outcome",
    [
        ("buy", 1000, 1025, 995, 1010, 0.02, "tp"),  # B1
        ("buy", 1000, 1010, 985, 1005, -0.01, "sl"),  # B2
        ("buy", 1000, 1010, 995, 1005, 0.005, "close"),  # B3
        ("buy", 1000, 1025, 990, 1010, -0.01, "ambiguous"),  # B4 両方到達→損切り優先
        ("sell", 2000, 2010, 1950, 1980, 0.02, "tp"),  # B5
        ("sell", 2000, 2025, 1950, 1980, -0.01, "ambiguous"),  # B6
    ],
)
def test_b_exit(side, fill, high, low, close, ret, outcome):
    r = simulate_exit(side, fill, high, low, close, 0.02, 0.01)
    assert r.result_return == pytest.approx(ret)
    assert r.outcome == outcome


def test_c_exit_with_cost():
    r = simulate_exit("buy", 1000, 1025, 995, 1010, 0.02, 0.01)
    assert apply_cost(r.result_return, COST) == pytest.approx(0.019)


def test_d_boundary_counts_as_reached():
    # 高値がちょうど利確価格1020、安値がちょうど損切り価格990でも到達とみなす
    assert simulate_exit("buy", 1000, 1020, 995, 1005, 0.02, 0.01).outcome == "tp"
    assert simulate_exit("buy", 1000, 1010, 990, 1005, 0.02, 0.01).outcome == "sl"
    assert simulate_exit("sell", 2000, 2010, 1960, 1990, 0.02, 0.01).outcome == "tp"


# --- 集計 ---
def _insert(db, side, entry, open_, high, low, close, variant="main", filled=1, anomaly=0):
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO predictions (prediction_date, code, name, side, total_score, technical_score, "
        "earnings_score, entry_price, reasons, target_date, evaluated, filled, target_open, target_high, "
        "target_low, target_close, created_at, variant, data_anomaly) "
        "VALUES ('2026-11-09', 'X', 'X', ?, 1, 1, 0, ?, '[]', '2026-11-10', 1, ?, ?, ?, ?, ?, 'now', ?, ?)",
        (side, entry, filled, open_, high, low, close, variant, anomaly),
    )
    conn.commit()
    conn.close()


def test_get_exit_stats(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    _insert(db, "buy", 1000, 1000, 1025, 995, 1010)  # tp  +2%
    _insert(db, "buy", 1000, 1000, 1010, 985, 1005)  # sl  -1%
    _insert(db, "buy", 1000, 1000, 1025, 990, 1010)  # 判定不能 -1%
    _insert(db, "buy", 1000, 1000, 1010, 995, 1005)  # 終値 +0.5%
    _insert(db, "buy", 1000, 1000, 1025, 995, 1010, filled=0)  # 不成立は除外
    _insert(db, "buy", 1000, 1000, 1025, 995, 1010, anomaly=1)  # データ異常は除外
    _insert(db, "buy", 1000, 1000, 1025, 995, 1010, variant="volatile")  # 別枠は除外
    _insert(db, "sell", 2000, 2000, 2010, 1950, 1980)  # 売りは除外
    [s] = get_exit_stats(db, "buy", rules=[(0.02, 0.01)], cost_rate=0.0)
    assert s.count == 4
    assert (s.tp_count, s.sl_count, s.close_count, s.ambiguous_count) == (1, 1, 1, 1)
    assert s.avg_return == pytest.approx((0.02 - 0.01 - 0.01 + 0.005) / 4)
    assert s.wins == 2
    assert s.win_rate == pytest.approx(0.5)
    [sc] = get_exit_stats(db, "buy", rules=[(0.02, 0.01)], cost_rate=COST)
    assert sc.avg_return == pytest.approx(s.avg_return - COST)
    assert sc.wins == 2


def test_gap_fill_uses_open_price(tmp_path):
    """寄り値が指値より有利なら寄り値で約定するため、利確・損切りの基準も寄り値になる。"""
    db = str(tmp_path / "t.db")
    init_db(db)
    _insert(db, "buy", 1000, 980, 995, 975, 990)  # 約定980 / 利確2%=999.6 未到達 / 損切り1%=970.2 未到達 → 終値990
    [s] = get_exit_stats(db, "buy", rules=[(0.02, 0.01)], cost_rate=0.0)
    assert s.close_count == 1
    assert s.avg_return == pytest.approx((990 - 980) / 980)


def test_exit_lines_format():
    s = ExitStats(0.02, 0.01, 4, 2, 0.00125, 1, 1, 1, 1)
    [line] = _exit_lines([s], 0.0)
    assert line.startswith("- 利確2%・損切り1%の平均リターン（試算）: +0.12%")
    assert "判定不能1件" in line
    [line2] = _exit_lines([s], 0.001)
    assert "試算・手数料込み" in line2
    assert _exit_lines(None) == []
    assert _exit_lines([ExitStats(0.02, 0.01, 0, 0, None, 0, 0, 0, 0)]) == []
