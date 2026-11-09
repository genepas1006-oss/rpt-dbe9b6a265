"""株式分割などのデータ異常（予測日終値に対する対象日終値の比 r < 0.65 または r > 1.5）の除外。承認済み（2026-11-10）。"""

import sqlite3

import pytest

from tracking.benchmark import get_score_effect, init_benchmarks
from tracking.predictions_db import get_win_rate_stats, init_db, is_data_anomaly
from tracking.refill import flag_anomalies
from tracking.unfilled import get_unfilled_predictions
from tracking.virtual_fund import get_virtual_fund
from datetime import date


@pytest.mark.parametrize(
    "pred,target,expected",
    [(10_000, 1_000, True), (1_000, 700, False), (1_000, 650, False), (1_000, 649, True),
     (1_000, 1_500, False), (1_000, 1_501, True), (None, 1_000, False), (0, 1_000, False)],
)
def test_ratio_boundaries(pred, target, expected):  # Z1〜Z7
    assert is_data_anomaly(pred, target) is expected


@pytest.fixture
def db(tmp_path):
    p = str(tmp_path / "t.db")
    init_db(p)
    return p


def _ins(db, code, side="buy", filled=1, ret=None, win=None, pred_close=1000.0, target_close=1000.0,
         pdate="2026-11-09", anomaly=0, entry=995.0):
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO predictions (prediction_date, code, name, side, total_score, technical_score, earnings_score, "
        "entry_price, reasons, target_date, evaluated, filled, target_low, target_high, target_close, result_return, "
        "is_win, created_at, pred_close, data_anomaly) VALUES (?, ?, ?, ?, 1, 1, 0, ?, '[]', '2026-11-10', 1, ?, "
        "1, 2, ?, ?, ?, 'now', ?, ?)",
        (pdate, code, code, side, entry, filled, target_close, ret, win, pred_close, anomaly),
    )
    conn.commit(); conn.close()


def test_flag_anomalies_and_win_rate_excludes(db):
    _ins(db, "A", ret=0.01, win=1)
    _ins(db, "B", ret=-0.01, win=0)
    _ins(db, "Z", ret=-0.90, win=0, pred_close=10_000.0, target_close=1_000.0)  # Z1 10分割
    _ins(db, "OLD", ret=-0.90, win=0, pred_close=None, entry=9_950.0, target_close=1_000.0)  # 予測日終値未記録は指値で代用
    assert flag_anomalies(db) == 2
    assert flag_anomalies(db) == 0  # 何度実行しても同じ
    s = get_win_rate_stats(db, "buy")
    assert (s.total_predictions, s.filled_count, s.win_count, s.excluded_count) == (2, 2, 1, 2)
    assert s.win_rate == pytest.approx(0.5)


def test_virtual_fund_ignores_anomaly_rows(db):
    # 1銘柄あたり 1,000,000/10 = 100,000円。P +2% と 分割の行(-90%) → 損益は +2,000円
    _ins(db, "P", ret=0.02, win=1)
    _ins(db, "Z", ret=-0.90, win=0, anomaly=1)
    fund = get_virtual_fund(db, date(2026, 11, 9), 1_000_000, 10)
    assert fund.days[0].pnl == pytest.approx(2000)
    assert fund.balance == pytest.approx(1_002_000)


def test_unfilled_and_score_effect_exclude_anomaly(db):
    _ins(db, "U", filled=0, anomaly=1)
    assert get_unfilled_predictions(db, "buy") == []
    init_benchmarks(db)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO benchmarks VALUES ('2026-11-09','buy',0.001,10,20)")
    conn.commit(); conn.close()
    _ins(db, "Z", ret=-0.90, win=0, anomaly=1)
    assert get_score_effect(db, "buy") is None


def test_report_line_for_excluded_count():
    from report.generate_report import _stats_lines
    from tracking.predictions_db import WinRateStats

    lines = _stats_lines(WinRateStats(2, 2, 1, 0.5, excluded_count=1))
    assert "- データ異常で除外（株式分割の疑い）: 1件" in lines
    assert not any("除外" in l for l in _stats_lines(WinRateStats(2, 2, 1, 0.5)))
