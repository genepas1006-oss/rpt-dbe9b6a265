"""成績欄の見出し的中率を「始値→終値の方向」にそろえる（2026-11-11承認・段階A）の手計算ケース。"""

import sqlite3

import pytest

from report.generate_report import _payoff_lines, _stats_lines
from tracking.payoff import get_payoff_stats
from tracking.predictions_db import get_market_order_stats, get_win_rate_stats, init_db


def _insert(db, oc, filled, result, anomaly=0, side="buy", variant="main"):
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO predictions (prediction_date, code, name, side, total_score, technical_score, earnings_score, "
        "entry_price, reasons, target_date, evaluated, filled, result_return, is_win, oc_return, data_anomaly, "
        "variant, created_at, target_close, pred_close) "
        "VALUES ('2026-11-09', 'X', 'X', ?, 1, 1, 0, 100, '[]', '2026-11-10', 1, ?, ?, ?, ?, ?, ?, 'now', 100, 100)",
        (side, filled, result, None if result is None else int(result > 0), oc, anomaly, variant),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.db")
    init_db(path)
    _insert(path, 0.010, 1, 0.012)    # 1
    _insert(path, -0.005, 1, -0.003)  # 2
    _insert(path, 0.020, 0, None)     # 3 不成立
    _insert(path, 0.0, 1, -0.001)     # 4 同値（始値基準では外れ）
    _insert(path, -0.015, 0, None)    # 5 不成立
    _insert(path, 0.030, 1, 0.03, anomaly=1)  # 6 データ異常（除外）
    _insert(path, None, 0, None)      # 7 始値の記録なし（除外）
    return path


def test_headline_open_close_win_rate(db):
    m = get_market_order_stats(db, "buy")
    assert m.count == 5 and m.wins == 2
    assert m.win_rate == pytest.approx(0.4)
    assert m.avg_return == pytest.approx(0.002)  # (1.0-0.5+2.0+0-1.5)/5 = +0.20%


def test_limit_based_reference_rate(db):
    s = get_win_rate_stats(db, side="buy")
    assert s.filled_count == 3 and s.win_count == 1  # 約定は #1,#2,#4。的中は #1 のみ
    lines = _stats_lines(s, get_market_order_stats(db, "buy"))
    assert lines[0] == "- 的中率（始値→終値の方向）: 40.0%（5件）"
    assert "- 指値で約定した場合の的中率（参考）: 33.3%（1/3件）" in lines


def test_payoff_on_open_close_basis(db):
    p = get_payoff_stats(db, "buy")
    assert p.count == 5 and p.wins == 2 and p.losses == 3
    assert p.avg_win == pytest.approx(0.015)
    assert p.avg_loss == pytest.approx(0.02 / 3)  # (0.5+0+1.5)/3 = 0.667%
    assert p.payoff_ratio == pytest.approx(2.25)
    assert p.avg_return == pytest.approx(0.002)
    assert 0.4 * p.avg_win - 0.6 * p.avg_loss == pytest.approx(p.avg_return)  # 検算
    lines = _payoff_lines(p)
    assert lines[0] == "- 平均利益（始値→終値・勝った場合のリターン）: +1.50%（2件）"
    assert lines[1] == "- 平均損失（始値→終値・負けた場合のリターン）: -0.67%（3件）"
    assert lines[2] == "- 損益比（平均利益÷平均損失）: 2.25"


def test_payoff_limit_basis_still_available(db):
    p = get_payoff_stats(db, "buy", basis="limit")
    assert p.count == 3 and p.wins == 1  # 約定した3件（#1,#2,#4）


def test_no_data_shows_no_data(tmp_path):
    path = str(tmp_path / "e.db")
    init_db(path)
    lines = _stats_lines(get_win_rate_stats(path, side="buy"), get_market_order_stats(path, "buy"))
    assert lines[0] == "- 的中率（始値→終値の方向）: データなし"
    assert get_payoff_stats(path, "buy") is None
