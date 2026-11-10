"""方向の的中率（予測日終値から見て予想した向きに動いたか）と、的中なのに方向が逆の行の注記。承認済みの手計算（2026-11-10）。"""

import sqlite3
from datetime import date

import pytest

from config import ENTRY_DISCOUNT
from tracking.predictions_db import get_win_rate_stats, init_db
from tracking.previous import get_previous_results
from tracking.trade_eval import base_price_of, is_direction_hit


@pytest.mark.parametrize("side,close,expected", [
    ("buy", 1010, True), ("buy", 990, False), ("buy", 1000, False),     # D1
    ("sell", 990, True), ("sell", 1010, False), ("sell", 1000, False),  # D2
])
def test_d1_d2_direction_hit(side, close, expected):
    assert is_direction_hit(side, 1000.0, close) is expected


def test_d3_denka_win_but_direction_wrong():
    assert is_direction_hit("sell", 2889.4, 2932.5) is False  # 2,932.5 > 2,889.4
    assert (2992.5 - 2932.5) / 2992.5 == pytest.approx(0.02005, abs=1e-5)  # 損益は+2.01%（寄り値で約定）


def test_d4_tokyu_win_and_direction_right():
    assert is_direction_hit("sell", 1196.0, 1195.0) is True


def test_d5_old_row_uses_entry_price_back_calculation():
    base = base_price_of("sell", None, 1202.0, ENTRY_DISCOUNT)
    assert base == pytest.approx(1196.0, abs=0.03)  # 1,202.0 ÷ 1.005
    assert is_direction_hit("sell", base, 1195.0) is True
    assert base_price_of("buy", None, 995.0, ENTRY_DISCOUNT) == pytest.approx(1000.0, abs=0.01)  # 995 ÷ 0.995
    assert base_price_of("sell", 1196.0, 1202.0, ENTRY_DISCOUNT) == 1196.0  # 記録があればそれを使う


@pytest.fixture
def db(tmp_path):
    p = str(tmp_path / "t.db")
    init_db(p)
    return p


def _ins(db, code, side="buy", pc=1000.0, entry=995.0, close=1000.0, filled=1, win=None, ret=None, anomaly=0,
         pdate="2026-11-09", open_=None):
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO predictions (prediction_date, code, name, side, total_score, technical_score, earnings_score, "
        "entry_price, reasons, target_date, evaluated, filled, target_low, target_high, target_close, target_open, "
        "result_return, is_win, created_at, pred_close, data_anomaly) VALUES (?, ?, ?, ?, 1, 1, 0, ?, '[]', "
        "'2026-11-10', 1, ?, 1, 99999, ?, ?, ?, ?, 'now', ?, ?)",
        (pdate, code, code, side, entry, filled, close, open_, ret, win, pc, anomaly),
    )
    conn.commit(); conn.close()


def test_d6_direction_rate_counts_all_evaluated_and_excludes_anomaly(db):
    _ins(db, "A", close=1010, filled=1, win=1, ret=0.01)           # 方向的中
    _ins(db, "B", close=990, filled=1, win=0, ret=-0.01)           # 外れ
    _ins(db, "C", close=1020, filled=0)                            # 不成立でも方向は数える → 的中
    _ins(db, "D", close=1005, filled=1, win=1, ret=0.005)          # 的中
    _ins(db, "Z", pc=10_000.0, close=1_000.0, anomaly=1)           # 株式分割の疑い → 除外
    s = get_win_rate_stats(db, "buy")
    assert (s.direction_total, s.direction_hits) == (4, 3)
    assert s.direction_hits / s.direction_total == pytest.approx(0.75)


def test_report_line_for_direction_rate():
    from report.generate_report import _stats_lines
    from tracking.predictions_db import WinRateStats

    lines = _stats_lines(WinRateStats(4, 3, 2, 0.667, direction_total=4, direction_hits=3))
    assert "- 方向の的中率（予測日終値比）: 75.0%（3/4件）" in lines
    assert not any("方向の的中率" in l for l in _stats_lines(WinRateStats(4, 3, 2, 0.667)))


def test_d7_note_only_for_win_with_wrong_direction(db):
    # 売り: 的中なのに方向が逆（デンカ）/ 的中で方向も合う（東急不動産）/ 不的中 / 不成立
    _ins(db, "DENKA", "sell", pc=2889.4, entry=2903.9, close=2932.5, win=1, ret=0.02005, open_=2992.5)
    _ins(db, "TOKYU", "sell", pc=1196.0, entry=1202.0, close=1195.0, win=1, ret=0.0071, open_=1203.5)
    _ins(db, "LOSS", "sell", pc=1000.0, entry=1005.0, close=1030.0, win=0, ret=-0.0249)
    _ins(db, "UNF", "sell", pc=1000.0, entry=1005.0, close=990.0, filled=0)
    prev = get_previous_results(db, "sell", date(2026, 11, 10))
    notes = {i.name: i.note for i in prev.items}
    assert notes == {"DENKA": "ギャップで有利に約定", "TOKYU": "", "LOSS": "", "UNF": ""}


def test_report_site_and_glossary_show_note(db, tmp_path):
    from analysis.scoring import RankedCandidate
    from report.build_site import build_index
    from report.generate_report import generate_report
    from tracking.predictions_db import WinRateStats

    _ins(db, "DENKA", "sell", pc=2889.4, entry=2903.9, close=2932.5, win=1, ret=0.02005, open_=2992.5)
    st = WinRateStats(1, 1, 1, 1.0, direction_total=1, direction_hits=0)
    cand = RankedCandidate(code="6954", name="ファナック", total_score=3, technical_score=2, earnings_score=1,
                           volume_ratio=2.0, entry_price=5608.8, side="sell", day_close=5600.0)
    text = generate_report(date(2026, 11, 10), date(2026, 11, 11), [], [cand], st, st,
                           sell_previous=get_previous_results(db, "sell", date(2026, 11, 10)))
    assert " | ギャップで有利に約定" in text and "- 方向の的中率（予測日終値比）: 0.0%（0/1件）" in text
    reports = tmp_path / "reports"; reports.mkdir()
    (reports / "2026-11-10.md").write_text(text, encoding="utf-8")
    page = build_index(reports, tmp_path / "docs", "x").read_text(encoding="utf-8")
    assert '<small class="pn-note">ギャップで有利に約定</small>' in page
    assert "<dt>方向の的中率</dt>" in page and "<dt>ギャップで有利に約定</dt>" in page
