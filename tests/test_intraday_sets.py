"""寄り枠・昼の予想（試験運用）のテスト。承認済みの手計算ケース O1〜O3・L1〜L3・S1（2026-11-11）。"""

import sqlite3
from datetime import date, datetime, timedelta

import pytest

from analysis.intraday_sets import IntradayInput, direction_result, select_lunch, select_open_gap
from data_sources.base import DailyBar, IntradayBar
from report.forecast_set import ACTIVE, EXPIRED, JST, WAITING, evening_set, lunch_set, open_set, pick_banner_set, state_at
from tracking.intraday_db import LUNCH, OPEN_GAP, evaluate_intraday_predictions, get_intraday_stats, save_intraday_picks
from tracking.predictions_db import get_pending_predictions, get_win_rate_stats, init_db

DAY = date(2026, 11, 11)


def dt(h, m=0, s=0, d=DAY):
    return datetime(d.year, d.month, d.day, h, m, s, tzinfo=JST)


def inp(code, base, ref):
    return IntradayInput(code, code, base, ref)


# ---- O1: 寄り枠の対象（前日終値1,000円、境界を含む） ----
@pytest.mark.parametrize("open_price,side", [(980, "buy"), (1020, "sell"), (985, "buy"), (986, None), (1015, "sell"), (1014, None)])
def test_o1_open_gap_threshold(open_price, side):
    buy, sell, _, _ = select_open_gap([inp("A", 1000.0, float(open_price))])
    got = "buy" if buy else "sell" if sell else None
    assert got == side


def test_o2_open_gap_ranking_top5():
    gaps = [-0.05, -0.04, -0.03, -0.02, -0.016, -0.015]
    buy, _, extra_b, _ = select_open_gap([inp(f"C{i}", 1000.0, 1000.0 * (1 + g)) for i, g in enumerate(gaps)])
    assert [round(p.move, 3) for p in buy] == [-0.05, -0.04, -0.03, -0.02, -0.016] and extra_b == 1


def test_o2_ties_are_ordered_by_code():
    buy, _, _, _ = select_open_gap([inp("B", 1000.0, 980.0), inp("A", 1000.0, 980.0)])
    assert [p.code for p in buy] == ["A", "B"]


# ---- O3 / L2: 的中の判定（同値は外れ） ----
@pytest.mark.parametrize("side,basis,close,ret,win", [
    ("buy", 980, 990, 10 / 980, True), ("buy", 980, 980, 0.0, False), ("sell", 1020, 1010, 10 / 1020, True),
    ("buy", 960, 970, 10 / 960, True), ("buy", 960, 960, 0.0, False), ("sell", 1040, 1030, 10 / 1040, True),
])
def test_o3_l2_direction_result(side, basis, close, ret, win):
    r, w = direction_result(side, float(basis), float(close))
    assert r == pytest.approx(ret) and w is win


# ---- L1: 昼の予想の対象（前場始値1,000円、境界を含む） ----
@pytest.mark.parametrize("am_close,side", [(965, "buy"), (970, "buy"), (971, None), (1030, "sell"), (1029, None)])
def test_l1_lunch_threshold(am_close, side):
    buy, sell, _, _ = select_lunch([inp("A", 1000.0, float(am_close))])
    assert ("buy" if buy else "sell" if sell else None) == side


# ---- L3: 表示件数 ----
def test_l3_lunch_max_10_with_extra_count():
    inputs = [inp(f"B{i:02d}", 1000.0, 1000.0 * (1 - 0.03 - i * 0.001)) for i in range(13)]
    buy, _, extra, _ = select_lunch(inputs)
    assert len(buy) == 10 and extra == 3
    assert buy[0].move < buy[-1].move  # 動きの大きい順（買いは下落が大きい順）


def test_non_positive_prices_are_skipped():
    assert select_open_gap([inp("Z", 0.0, 980.0), inp("Y", 1000.0, 0.0)]) == ([], [], 0, 0)


# ---- S1: 有効期間とバナー ----
def test_s1_banner_with_open_lunch_and_evening():
    ev = evening_set(date(2026, 11, 10), DAY, dt(16, 12, d=date(2026, 11, 10)))
    op, lu = open_set(DAY, dt(9, 25)), lunch_set(DAY, dt(11, 50))
    assert pick_banner_set([ev, op, lu], dt(9, 30)) is op            # 夜と寄り枠が有効 → 作成が新しい寄り枠
    assert state_at(ev, dt(9, 30))[0] == ACTIVE and state_at(op, dt(9, 30))[0] == ACTIVE
    assert pick_banner_set([ev, op, lu], dt(11, 40)) is lu           # 両方期限切れ、昼は待機
    assert state_at(lu, dt(11, 40)) == (WAITING, timedelta(minutes=50))
    assert state_at(lu, dt(12, 30, 0))[0] == ACTIVE and pick_banner_set([ev, op, lu], dt(12, 30)) is lu
    assert state_at(op, dt(11, 30, 0))[0] == EXPIRED
    assert lu.label == "昼の予想（11/11 後場向け）" and op.label == "寄り枠（11/11 前場向け）"


# ---- DB・答え合わせ ----
class FakeSource:
    def __init__(self, closes, pm_open=None):
        self.closes, self.pm_open = closes, pm_open or {}

    def get_daily_bars(self, code, start, end):
        c = self.closes.get(code)
        return [DailyBar(start, 100.0, 1100.0, 900.0, c, 1000)] if c else []

    def get_intraday_bars(self, code, day):
        p = self.pm_open.get(code)
        return [IntradayBar(datetime(day.year, day.month, day.day, 12, 30, tzinfo=JST), p, p, p, p, 1)] if p else []


@pytest.fixture
def db(tmp_path):
    p = str(tmp_path / "t.db")
    init_db(p)
    return p


def _picks(slot_inputs, fn):
    buy, sell, _, _ = fn(slot_inputs)
    return [*buy, *sell]


def test_save_replace_and_main_stats_are_not_mixed(db):
    picks = _picks([inp("A", 1000.0, 980.0), inp("B", 1000.0, 1020.0)], select_open_gap)
    save_intraday_picks(db, DAY, OPEN_GAP, picks, open_set(DAY, dt(9, 25)))
    save_intraday_picks(db, DAY, OPEN_GAP, picks[:1], open_set(DAY, dt(9, 26)))  # 再実行 → 未評価は置き換え
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 1
    row = conn.execute("SELECT variant, slot, entry_price, pred_close, valid_from FROM predictions").fetchone()
    conn.close()
    assert row == (OPEN_GAP, "open", 980.0, 1000.0, "2026-11-11T09:00:00+09:00")
    assert get_win_rate_stats(db, "buy").total_predictions == 0  # 本番の成績には入らない
    assert get_pending_predictions(db, DAY) == []                # 本番の答え合わせの対象にもならない


def test_evaluate_open_and_lunch_after_close(db):
    save_intraday_picks(db, DAY, OPEN_GAP, _picks([inp("A", 1000.0, 980.0), inp("B", 1000.0, 1020.0)], select_open_gap),
                        open_set(DAY, dt(9, 25)))
    save_intraday_picks(db, DAY, LUNCH, _picks([inp("C", 1000.0, 965.0), inp("D", 1000.0, 1040.0)], select_lunch),
                        lunch_set(DAY, dt(11, 50)))
    src = FakeSource({"A": 990.0, "B": 1010.0, "C": 970.0, "D": 1040.0}, {"C": 960.0, "D": 1040.0})
    assert evaluate_intraday_predictions(db, src, dt(14, 0)) == 0           # 大引け前は判定しない
    assert evaluate_intraday_predictions(db, src, dt(15, 36)) == 4
    assert evaluate_intraday_predictions(db, src, dt(15, 36)) == 0          # 何度実行しても同じ
    assert get_intraday_stats(db, OPEN_GAP, "buy") == (1, 1)                # A: 始値980 → 終値990 → 的中
    assert get_intraday_stats(db, OPEN_GAP, "sell") == (1, 1)               # B: 始値1,020 → 終値1,010 → 的中
    assert get_intraday_stats(db, LUNCH, "buy") == (1, 1)                   # C: 後場始値960 → 終値970 → 的中
    assert get_intraday_stats(db, LUNCH, "sell") == (1, 0)                  # D: 後場始値1,040 → 終値1,040 → 同値で外れ
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT target_open, result_return FROM predictions WHERE code='C'").fetchone() == (960.0, pytest.approx(10 / 960))
    conn.close()


def test_missing_pm_open_is_retried_later(db):
    save_intraday_picks(db, DAY, LUNCH, _picks([inp("C", 1000.0, 965.0)], select_lunch), lunch_set(DAY, dt(11, 50)))
    assert evaluate_intraday_predictions(db, FakeSource({"C": 970.0}, {}), dt(16, 10)) == 0   # 後場始値が取れない → 保留
    assert evaluate_intraday_predictions(db, FakeSource({"C": 970.0}, {"C": 960.0}), dt(16, 10)) == 1


# ---- 作成の流れ（日中の足 → 選別 → 記録 → レポート → サイト） ----
class DaySource:
    """日中の足と日足を返す偽のデータ元。prev: 前日終値、open_: 寄り、am_close: 前場終値。"""

    def __init__(self, prev, open_, am_close=None, missing=()):
        self.prev, self.open_, self.am_close, self.missing = prev, open_, am_close or {}, set(missing)

    def get_daily_bars(self, code, start, end):
        return [] if code in self.missing or code not in self.prev else [DailyBar(end, 1, 1, 1, self.prev[code], 1)]

    def get_intraday_bars(self, code, day):
        if code in self.missing or code not in self.open_:
            return []
        o = self.open_[code]
        bars = [IntradayBar(datetime(day.year, day.month, day.day, 9, 0, tzinfo=JST), o, o, o, o, 1)]
        if code in self.am_close:
            bars.append(IntradayBar(datetime(day.year, day.month, day.day, 11, 25, tzinfo=JST), o, o, o, self.am_close[code], 1))
        return bars


UNIVERSE = [("1111", "アルファ"), ("2222", "ブラボー"), ("3333", "チャーリー"), ("4444", "デルタ")]


def test_run_open_end_to_end(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from intraday_runner import NoIntradayData, run_intraday

    src = DaySource({"1111": 1000.0, "2222": 1000.0, "3333": 1000.0, "4444": 1000.0},
                    {"1111": 980.0, "2222": 1020.0, "3333": 1000.0, "4444": 999.0})
    path = run_intraday("open", DAY, src, dt(9, 25), UNIVERSE, publish=False)
    text = path.read_text(encoding="utf-8")
    assert path.name == "2026-11-11-open.md" and "## 予想セット" in text
    assert "- 1位 | アルファ（1111） | 基準価格 980.0円 | -2.00% | 前日終値1,000.0円 → 始値980.0円" in text
    assert "ブラボー（2222）" in text and "チャーリー" not in text
    # 取得できた銘柄が半数未満なら、作成を中止する
    with pytest.raises(NoIntradayData):
        run_intraday("open", DAY, DaySource({"1111": 1000.0}, {"1111": 980.0}, missing=["2222", "3333", "4444"]), dt(9, 25), UNIVERSE, publish=False)


def test_run_lunch_requires_complete_morning_bars(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from intraday_runner import run_intraday

    prev = {c: 1000.0 for c, _ in UNIVERSE}
    src = DaySource(prev, {"1111": 1000.0, "2222": 1000.0, "3333": 1000.0, "4444": 1000.0},
                    {"1111": 965.0, "2222": 1030.0, "3333": 1029.0})           # 4444は前場の足が揃っていない
    text = run_intraday("lunch", DAY, src, dt(11, 50), UNIVERSE, publish=False).read_text(encoding="utf-8")
    assert "アルファ（1111） | 基準価格 965.0円 | -3.50% | 前場始値1,000.0円 → 前場終値965.0円" in text
    assert "ブラボー（2222）" in text and "チャーリー" not in text and "デルタ" not in text   # +2.9%は対象外


def test_site_orders_sets_and_keeps_them_out_of_history(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import json, re
    from analysis.scoring import RankedCandidate
    from intraday_runner import run_intraday
    from report.build_site import build_index
    from report.generate_report import generate_report
    from tracking.predictions_db import WinRateStats

    st = WinRateStats(1, 1, 1, 1.0)
    cand = RankedCandidate(code="6954", name="ファナック", total_score=3, technical_score=2, earnings_score=1,
                           volume_ratio=2.0, entry_price=5608.8, side="buy", day_close=5600.0)
    reports = tmp_path / "reports"; reports.mkdir()
    fs = evening_set(date(2026, 11, 10), DAY, dt(16, 12, d=date(2026, 11, 10)))
    (reports / "2026-11-10.md").write_text(generate_report(date(2026, 11, 10), DAY, [cand], [], st, st, forecast_set=fs), encoding="utf-8")
    prev = {c: 1000.0 for c, _ in UNIVERSE}
    opens = {c: 1000.0 for c, _ in UNIVERSE}; opens["1111"] = 980.0
    run_intraday("open", DAY, DaySource(prev, opens, {}), dt(9, 25), UNIVERSE, publish=False)
    run_intraday("lunch", DAY, DaySource(prev, opens, {"1111": 1000.0, "2222": 1040.0, "3333": 1000.0, "4444": 1000.0}), dt(11, 50), UNIVERSE, publish=False)
    page = build_index(reports, tmp_path / "docs", "x").read_text(encoding="utf-8")
    i_lunch, i_open, i_even = page.index("昼の予想（11/11 後場向け）"), page.index("寄り枠（11/11 前場向け）"), page.index("夜の予想（11/11 前場向け）")
    assert i_lunch < i_open < i_even                                  # 作成が新しいものが上
    data = json.loads(re.search(r'<script type="application/json" id="fsets">(.*?)</script>', page, re.S).group(1))
    assert sorted(d["slot"] for d in data) == ["evening", "lunch", "open"]
    assert "使える時間 11/11 12:30〜15:30" in page and "試験運用・効果は未確認" in page
    assert "<dt>寄り枠</dt>" in page
    assert page.count('class="day-row"') == 0  # 日中の枠のレポートは、過去のレポート一覧に入らない
    assert "アルファ（1111）" in page and 'class="ipick buy"' in page and 'class="ipick sell"' in page
