"""成行（寄り→引け）の参考成績のテスト（2026-11-09承認の手計算ケース）。"""

import sqlite3
from datetime import date

import pytest

from analysis.scoring import RankedCandidate
from data_sources.base import DailyBar, DataSource
from report.build_site import build_index
from report.generate_report import generate_report
from report.parse_report import parse_report
from tracking.evaluate import evaluate_pending_predictions
from tracking.predictions_db import (
    MarketOrderStats,
    WinRateStats,
    get_market_order_stats,
    init_db,
    record_evaluation,
    save_predictions,
)

D0, T0 = date(2026, 11, 5), date(2026, 11, 6)


def _cand(code, side="buy", price=None):
    price = price if price is not None else (995.0 if side == "buy" else 1005.0)
    return RankedCandidate(
        code=code, name=f"n{code}", total_score=3, technical_score=2, earnings_score=1,
        volume_ratio=1.2, entry_price=price, reasons=[], side=side, day_close=1000.0, daily_return=0.01,
    )


def _pid(db, code):
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT id FROM predictions WHERE code=?", (code,)).fetchone()[0]
    finally:
        conn.close()


def _eval(db, code, open_, close, low=None, high=None):
    low = low if low is not None else min(open_, close)
    high = high if high is not None else max(open_, close)
    record_evaluation(db, _pid(db, code), target_low=low, target_high=high, target_close=close,
                      actual_date=T0, target_open=open_, market_return=0.0)


def _oc(db, code):
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT oc_return FROM predictions WHERE code=?", (code,)).fetchone()[0]
    finally:
        conn.close()


def _db(tmp_path):
    db = str(tmp_path / "p.db")
    init_db(db)
    return db


# ---------------- 手計算（買い3件） ----------------
def _three_buys(tmp_path):
    db = _db(tmp_path)
    save_predictions(db, D0, T0, [_cand("A"), _cand("B"), _cand("C")])
    _eval(db, "A", 990, 1005, low=985, high=1010)  # 指値995: 約定(985<=995)。寄り990が有利なので990で約定。成行 +1.515%、指値 (1005-990)/990
    _eval(db, "B", 1000, 990, low=985, high=1000)  # 約定。成行 -1.0%、指値 (990-995)/995
    _eval(db, "C", 1000, 1000, low=996, high=1005)  # 安値996>995 → 指値は不成立。成行は 0.0%
    return db


def test_oc_return_values(tmp_path):
    db = _three_buys(tmp_path)
    assert _oc(db, "A") == pytest.approx(15 / 990)
    assert _oc(db, "B") == pytest.approx(-0.01)
    assert _oc(db, "C") == 0.0


def test_stats_hand_calc_buy(tmp_path):
    s = get_market_order_stats(_three_buys(tmp_path), "buy")
    assert (s.count, s.wins) == (3, 1)
    assert s.win_rate == pytest.approx(1 / 3)  # 33.3%（0.0%は的中でない）
    assert s.avg_return == pytest.approx((15 / 990 - 0.01 + 0.0) / 3)  # ≒ +0.1717%
    # 指値の平均は約定した2件のみ: ((1005-990)/990 + (990-995)/995)/2
    assert s.limit_avg_return == pytest.approx((15 / 990 - 5 / 995) / 2)


def test_unfilled_limit_still_counts_in_market_order_count(tmp_path):
    s = get_market_order_stats(_three_buys(tmp_path), "buy")
    assert s.count == 3  # 指値の約定は2件だが、成行は3件


def test_sell_sign_is_reversed(tmp_path):
    db = _db(tmp_path)
    save_predictions(db, D0, T0, [_cand("S", side="sell")])
    _eval(db, "S", 990, 1005, low=985, high=1010)  # 売り: 始値990→終値1005 は値上がり → 損
    assert _oc(db, "S") == pytest.approx(-15 / 990)
    s = get_market_order_stats(db, "sell")
    assert (s.count, s.wins) == (1, 0) and s.avg_return == pytest.approx(-15 / 990)


def test_sides_are_separate(tmp_path):
    db = _three_buys(tmp_path)
    assert get_market_order_stats(db, "sell").count == 0


def test_rows_without_open_are_excluded(tmp_path):
    db = _db(tmp_path)
    save_predictions(db, D0, T0, [_cand("OLD"), _cand("NEW")])
    record_evaluation(db, _pid(db, "OLD"), target_low=985, target_high=1010, target_close=1005)  # 始値なし（旧データ相当）
    _eval(db, "NEW", 990, 1005, low=985, high=1010)
    s = get_market_order_stats(db, "buy")
    assert s.count == 1 and _oc(db, "OLD") is None


def test_unevaluated_rows_are_excluded(tmp_path):
    db = _db(tmp_path)
    save_predictions(db, D0, T0, [_cand("P")])
    assert get_market_order_stats(db, "buy") == MarketOrderStats(0, 0, None, None, None)


def test_zero_open_is_not_recorded(tmp_path):
    db = _db(tmp_path)
    save_predictions(db, D0, T0, [_cand("Z")])
    _eval(db, "Z", 0, 1005, low=0, high=1010)
    assert _oc(db, "Z") is None


class _Src(DataSource):
    def __init__(self, bars):
        self.bars = bars

    def get_daily_bars(self, code, start, end):
        return [b for b in self.bars if start <= b.trade_date <= end]

    def get_earnings_dates(self, code):
        return []


def test_holiday_fallback_uses_actual_trading_day_values(tmp_path):
    db = _db(tmp_path)
    holiday, nxt = date(2026, 11, 3), date(2026, 11, 4)
    save_predictions(db, date(2026, 11, 2), holiday, [_cand("H")])
    evaluate_pending_predictions(db, _Src([DailyBar(nxt, 990, 1010, 985, 1005, 1)]), as_of=nxt)
    assert _oc(db, "H") == pytest.approx(15 / 990)  # 実際に使った営業日(11/4)の始値・終値


def test_migration_adds_oc_return_column(tmp_path):
    db = str(tmp_path / "old.db")
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, prediction_date TEXT NOT NULL, code TEXT NOT NULL,
            name TEXT NOT NULL, side TEXT NOT NULL DEFAULT 'buy', total_score INTEGER NOT NULL,
            technical_score INTEGER NOT NULL, earnings_score INTEGER NOT NULL, entry_price REAL NOT NULL,
            reasons TEXT NOT NULL, target_date TEXT NOT NULL, evaluated INTEGER NOT NULL DEFAULT 0,
            filled INTEGER, target_low REAL, target_high REAL, target_close REAL, result_return REAL,
            is_win INTEGER, created_at TEXT NOT NULL)"""
    )
    conn.commit()
    conn.close()
    init_db(db)
    conn = sqlite3.connect(db)
    assert "oc_return" in {r[1] for r in conn.execute("PRAGMA table_info(predictions)")}
    conn.close()


# ---------------- レポート → パース → サイト ----------------
STATS = WinRateStats(total_predictions=10, filled_count=8, win_count=4, win_rate=0.5)
MARKET = MarketOrderStats(count=3, wins=1, win_rate=1 / 3, avg_return=(15 / 990 - 0.01) / 3, limit_avg_return=0.0025126)


def _report(buy_market=MARKET, sell_market=None):
    cand = RankedCandidate(
        code="6954", name="ファナック", total_score=3, technical_score=2, earnings_score=1,
        volume_ratio=2.0, entry_price=100.0, reasons=[], side="buy",
        day_open=100, day_high=101, day_low=99, day_close=100, day_volume=1,
    )
    return generate_report(date(2026, 11, 6), date(2026, 11, 9), [cand], [], STATS, STATS,
                           None, None, None, None, buy_market, sell_market)


def test_report_lines_format():
    text = _report()
    assert "- 成行（寄り→引け）の的中率（参考）: 33.3%（3件）" in text
    assert "- 成行（寄り→引け）の平均リターン（参考）: +0.17%" in text
    assert "- 指値の平均リターン（同じ予測・約定分）: +0.25%" in text


def test_report_omits_lines_when_no_data():
    assert "成行" not in _report(buy_market=None)
    assert "成行" not in _report(buy_market=MarketOrderStats(0, 0, None, None, None))
    no_limit = _report(buy_market=MarketOrderStats(2, 1, 0.5, 0.001, None))
    assert "成行（寄り→引け）の的中率（参考）: 50.0%（2件）" in no_limit and "指値の平均リターン" not in no_limit


def test_parse_keeps_new_lines_as_stats():
    parsed = parse_report(_report())
    assert any("成行（寄り→引け）の的中率（参考）" in l for l in parsed.buy_stats_lines)


def test_site_tiles_no_bar_no_sign_color_and_win_rate_feature_unchanged(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "2026-11-06.md").write_text(_report(buy_market=MarketOrderStats(3, 1, 1 / 3, -0.0021, 0.0025126)), encoding="utf-8")
    page = build_index(reports, tmp_path / "docs", "t").read_text(encoding="utf-8")
    # バー付きの大きなタイルは「的中率（約定分のみ）」だけ（買い・売りの2つ）。成行のタイルには付かない
    assert page.count('class="stat-tile feature"') == 2 and page.count('class="bar"') == 2
    assert '<span class="cap">成行（寄り→引け）の的中率（参考）</span><span class="val">33.3%<span class="sub">（3件）</span></span>' in page
    assert '<span class="val">-0.21%</span>' in page  # 平均リターンは色付けしない
    assert '<span class="val">+0.25%</span>' in page
    assert 'color:var(--down)">-0.21%' not in page


def test_limit_average_uses_only_same_predictions_as_market_stats(tmp_path):
    db = _db(tmp_path)
    save_predictions(db, D0, T0, [_cand("OLD"), _cand("NEW"), _cand("UNF")])
    # 始値が未記録の旧データ(約定・+4.02%)は、指値の平均にも入れない
    record_evaluation(db, _pid(db, "OLD"), target_low=985, target_high=1010, target_close=1035)
    _eval(db, "NEW", 990, 1005, low=985, high=1010)  # 約定 寄り990で約定 (1005-990)/990
    _eval(db, "UNF", 1000, 1000, low=996, high=1005)  # 不成立
    s = get_market_order_stats(db, "buy")
    assert s.limit_avg_return == pytest.approx(15 / 990)  # NEWだけ
    # 防御: 不成立の行に何らかの値が入っていても、約定していなければ平均に入れない
    conn = sqlite3.connect(db)
    conn.execute("UPDATE predictions SET result_return = 0.5 WHERE code = 'UNF'")
    conn.commit()
    conn.close()
    assert get_market_order_stats(db, "buy").limit_avg_return == pytest.approx(15 / 990)
