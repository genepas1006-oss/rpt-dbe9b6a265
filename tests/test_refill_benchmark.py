"""約定価格の再計算（refill）と全銘柄平均・スコアの効果（benchmark）のテスト。承認済み手計算（2026-11-09）。"""

import sqlite3
from datetime import date

import pytest

from data_sources.base import DailyBar
from tracking.benchmark import compute_missing_benchmarks, compute_universe_return, get_score_effect, init_benchmarks
from tracking.predictions_db import init_db
from tracking.refill import backfill_target_open, recompute_fills

D0, D1, D2 = date(2026, 11, 9), date(2026, 11, 10), date(2026, 11, 11)


def _bar(d, o, h, l, c):
    return DailyBar(d, o, h, l, c, 1000)


@pytest.fixture
def db(tmp_path):
    p = str(tmp_path / "t.db")
    init_db(p)
    return p


def _insert(db, code, side="buy", entry=1000.0, low=None, high=None, close=None, open_=None, evaluated=1,
            filled=1, ret=None, win=None, pdate="2026-11-09", fill_price=None):
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO predictions (prediction_date, code, name, side, total_score, technical_score, earnings_score, "
        "entry_price, reasons, target_date, evaluated, filled, target_low, target_high, target_close, target_open, "
        "result_return, is_win, created_at, pred_close, pred_daily_return, pred_volume_ratio, miss_causes, fill_price) "
        "VALUES (?, ?, ?, ?, 1, 1, 0, ?, '[]', '2026-11-10', ?, ?, ?, ?, ?, ?, ?, ?, 'now', 1000, 0.03, 2.0, ?, ?)",
        (pdate, code, code, side, entry, evaluated, filled, low, high, close, open_, ret, win,
         '["x"]' if win == 0 else None, fill_price),
    )
    conn.commit()
    conn.close()


def _row(db, code):
    conn = sqlite3.connect(db)
    r = conn.execute("SELECT fill_price, result_return, is_win, miss_causes FROM predictions WHERE code = ?", (code,)).fetchone()
    conn.close()
    return r


# ---- B. 過去データの再計算 ----
def test_recompute_flips_loss_to_win_and_clears_miss_causes(db):
    _insert(db, "A", low=975, high=1000, close=990, open_=980, ret=-0.01, win=0)
    assert recompute_fills(db) == 1
    fill, ret, win, causes = _row(db, "A")
    assert fill == 980 and ret == pytest.approx(10 / 980) and win == 1 and causes is None


def test_recompute_leaves_missing_open_and_unfilled_rows_and_is_idempotent(db):
    _insert(db, "N", low=975, high=1000, close=990, open_=None, ret=-0.01, win=0)
    _insert(db, "U", low=1001, high=1010, close=1005, open_=1005, filled=0)
    assert recompute_fills(db) == 0
    assert _row(db, "N")[:3] == (None, -0.01, 0)
    _insert(db, "A", low=975, high=1000, close=990, open_=980, ret=-0.01, win=0)
    assert recompute_fills(db) == 1
    assert recompute_fills(db) == 0


class _Src:
    def __init__(self, opens):
        self.opens = opens

    def get_daily_bars(self, code, start, end):
        if code not in self.opens:
            raise RuntimeError("fail")
        return [_bar(start, self.opens[code], self.opens[code] + 5, self.opens[code] - 5, self.opens[code])]


def test_backfill_target_open_skips_failures(db):
    _insert(db, "A", low=975, high=1000, close=990, open_=None, ret=-0.01, win=0)
    _insert(db, "B", low=975, high=1000, close=990, open_=None, ret=-0.01, win=0)
    assert backfill_target_open(db, _Src({"A": 980.0})) == 1
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT target_open FROM predictions WHERE code='A'").fetchone()[0] == 980.0
    assert conn.execute("SELECT target_open FROM predictions WHERE code='B'").fetchone()[0] is None
    conn.close()


# ---- C/D. 全銘柄平均 ----
def _universe_buy():
    pre = lambda: _bar(D0, 1000, 1000, 1000, 1000)
    return {
        "P": [pre(), _bar(D1, 1000, 1010, 990, 1004)],  # 995で約定 +9/995
        "Q": [pre(), _bar(D1, 980, 990, 970, 985)],      # 寄り980で約定 +5/980
        "R": [pre(), _bar(D1, 1005, 1010, 996, 1008)],   # 不成立
        "S": [pre(), _bar(D1, 1010, 1012, 990, 985)],    # 995で約定 -10/995
    }


def test_case_c_universe_return_buy():
    ur = compute_universe_return("buy", _universe_buy(), D0)
    assert ur.filled_count == 3 and ur.universe_count == 4
    assert ur.avg_return == pytest.approx((9 / 995 + 5 / 980 - 10 / 995) / 3)  # +0.1366%


def test_case_d_universe_return_sell():
    bars = {
        "X": [_bar(D0, 1000, 1000, 1000, 1000), _bar(D1, 1020, 1025, 1010, 1015)],  # 指値1005 → 寄り1020で約定 +5/1020
        "Y": [_bar(D0, 1000, 1000, 1000, 1000), _bar(D1, 1000, 1004, 990, 995)],    # 高値1004 < 1005 → 不成立
    }
    ur = compute_universe_return("sell", bars, D0)
    assert ur.filled_count == 1 and ur.avg_return == pytest.approx(5 / 1020)


def test_universe_skips_stocks_without_next_bar():
    assert compute_universe_return("buy", {"Z": [_bar(D0, 1, 1, 1, 1)]}, D0) is None


def test_score_effect_two_days_and_exclusions(db):
    init_benchmarks(db)
    conn = sqlite3.connect(db)
    conn.executemany("INSERT INTO benchmarks VALUES (?,?,?,?,?)", [
        ("2026-11-09", "buy", (9 / 995 + 5 / 980 - 10 / 995) / 3, 3, 4),
        ("2026-11-10", "buy", 0.001, 10, 20),
        ("2026-11-11", "buy", 0.05, 10, 20),   # TOP5が全て不成立の日 → 除外
        # 2026-11-12 は全銘柄平均の記録なし → 除外
    ])
    conn.commit(); conn.close()
    # 1日目: TOP5の約定が P(+9/995) と S(-10/995)
    _insert(db, "P", low=990, high=1010, close=1004, open_=1000, ret=9 / 995, win=1, pdate="2026-11-09")
    _insert(db, "S", low=990, high=1012, close=985, open_=1010, ret=-10 / 995, win=0, pdate="2026-11-09")
    _insert(db, "T", low=990, high=1010, close=1003, open_=1000, ret=0.003, win=1, pdate="2026-11-10")  # 2日目 +0.3%
    _insert(db, "U", filled=0, pdate="2026-11-11")
    _insert(db, "V", low=990, high=1010, close=1003, open_=1000, ret=0.01, win=1, pdate="2026-11-12")
    e = get_score_effect(db, "buy")
    day1_top = (9 / 995 - 10 / 995) / 2          # -0.0503%
    day1_bench = (9 / 995 + 5 / 980 - 10 / 995) / 3  # +0.1366%
    assert e.days == 2
    assert e.top_avg == pytest.approx((day1_top + 0.003) / 2)
    assert e.bench_avg == pytest.approx((day1_bench + 0.001) / 2)
    assert e.excess == pytest.approx(((day1_top - day1_bench) + (0.003 - 0.001)) / 2)  # +0.0066%
    assert get_score_effect(db, "sell") is None


def test_compute_missing_benchmarks_saves_once(db):
    _insert(db, "P", low=990, high=1010, close=1004, open_=1000, ret=9 / 995, win=1)
    assert compute_missing_benchmarks(db, _universe_buy()) == 1
    assert compute_missing_benchmarks(db, _universe_buy()) == 0


def test_report_line_and_site_tile_for_score_effect(tmp_path):
    from pathlib import Path

    from report.build_site import build_index
    from report.generate_report import generate_report
    from tracking.benchmark import ScoreEffect
    from tracking.predictions_db import WinRateStats

    st = WinRateStats(total_predictions=10, filled_count=8, win_count=4, win_rate=0.5)
    eff = ScoreEffect(days=2, top_avg=0.00125, bench_avg=0.00118, excess=0.000066)
    text = generate_report(D0, D1, [], [], st, st, buy_effect=eff)
    assert "- 全銘柄平均との差（スコアの効果の目安）: +0.01%（TOP5 +0.12% / 全銘柄 +0.12%・2日）" in text
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "2026-11-09.md").write_text(text, encoding="utf-8")
    page = build_index(reports, tmp_path / "docs", "x").read_text(encoding="utf-8")
    assert "全銘柄平均との差（スコアの効果の目安）" in page and "+0.01%" in page


# ---- 株式分割などで基準の違う寄り値を使わない（2026-11-10 バグ修正） ----
def test_open_consistency_boundaries():
    from tracking.refill import open_is_consistent

    assert open_is_consistent(1004, 975, 1000) and open_is_consistent(971, 975, 1000)  # 安値-0.5%〜高値+0.5%
    assert not open_is_consistent(1006, 975, 1000) and not open_is_consistent(969, 975, 1000)
    assert not open_is_consistent(98, 975, 1000)  # 10分割で調整された寄り値
    assert open_is_consistent(5, None, None)  # 安値・高値が不明なら判定しない


def test_backfill_rejects_split_adjusted_open(db):
    _insert(db, "S", low=975, high=1000, close=990, open_=None, ret=-0.01, win=0)
    assert backfill_target_open(db, _Src({"S": 98.0})) == 0
    assert recompute_fills(db) == 0
    assert _row(db, "S")[:3] == (None, -0.01, 0)


def test_repair_restores_row_damaged_by_split_adjusted_open(db):
    # 10分割の前に記録した予測。調整後の寄り値98で補正され、損益が +910% になってしまった行
    _insert(db, "S", low=975, high=1000, close=990, open_=98, ret=(990 - 98) / 98, win=1, fill_price=98)
    _insert(db, "OK", low=975, high=1000, close=990, open_=980, ret=10 / 980, win=1, fill_price=980)  # 正常な行は触らない
    from tracking.refill import repair_inconsistent_opens

    assert repair_inconsistent_opens(db) == 1
    fill, ret, win, _ = _row(db, "S")
    assert fill is None and ret == pytest.approx(-0.01) and win == 0  # (990-1000)/1000 の補正前の評価に戻る
    assert _row(db, "OK")[:3] == (980, pytest.approx(10 / 980), 1)
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT target_open, oc_return FROM predictions WHERE code='S'").fetchone() == (None, None)
    conn.close()
    assert repair_inconsistent_opens(db) == 0


def test_has_enough_market_data():
    from run_daily import has_enough_market_data

    assert has_enough_market_data(225, 225) and has_enough_market_data(113, 225)
    assert not has_enough_market_data(112, 225) and not has_enough_market_data(0, 225)
    assert not has_enough_market_data(0, 0)
