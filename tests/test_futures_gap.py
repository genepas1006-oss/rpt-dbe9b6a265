"""日経225先物（夜間）ベースの想定ギャップのテスト（2026-11-13承認の手計算ケース）。"""

from datetime import date, datetime, timedelta, timezone

import pytest

from analysis.futures_gap import compute_futures_gap, futures_move, last_completed
from data_sources.base import HourBar
from report.premarket import load_premarket, save_premarket
from tests.test_premarket import _page, _pm

JST = timezone(timedelta(hours=9))


def _hb(day, hour, close):
    return HourBar(datetime(day.year, day.month, day.day, hour, 0, tzinfo=JST), close)


D1, D2, D3, D4, D5 = date(2026, 11, 2), date(2026, 11, 4), date(2026, 11, 5), date(2026, 11, 6), date(2026, 11, 9)


def test_f1_slope_and_expected_gap():
    # 組 (x,y) = (+1%,+0.8%), (-2%,-1.8%), (+0.5%,+0.4%) → 傾き 0.00046/0.000525 = 0.87619
    moves = {D2: 0.01, D3: -0.02, D4: 0.005, D5: 0.01}
    bars = []
    for d in (D1, D2, D3, D4):
        bars.append(_hb(d, 14, 1000.0))  # 次の営業日の基準になる足（14:00〜15:00）
    for d, x in moves.items():
        bars.append(_hb(d, 7, 1000.0 * (1 + x)))  # 当日7:00〜8:00の足
    bars.sort(key=lambda b: b.start)
    gaps = {D1: 0.0, D2: 0.008, D3: -0.018, D4: 0.004}
    fg, reason = compute_futures_gap(bars, gaps, D5, "NIY=F", min_n=3)
    assert reason is None and fg.n_fit == 3
    assert fg.move == pytest.approx(0.01)
    assert fg.slope == pytest.approx(0.00046 / 0.000525)
    assert fg.expected_gap == pytest.approx(0.0087619, abs=1e-6)


def test_f2_move():
    bars = [_hb(D4, 14, 62000.0), _hb(D5, 7, 62310.0)]
    x, base, target = futures_move(bars, D5, D4)
    assert x == pytest.approx(0.005)


def test_f3_uses_last_completed_target_bar():
    bars = [_hb(D4, 14, 62000.0), _hb(D5, 7, 62310.0), _hb(D5, 8, 70000.0)]  # 8:00〜9:00の足は8:30時点で未完結
    x, _, target = futures_move(bars, D5, D4)
    assert target.close == 62310.0 and x == pytest.approx(0.005)
    assert last_completed(bars, datetime(2026, 11, 9, 8, 30, tzinfo=JST)).close == 62310.0


def test_f4_uses_last_completed_base_bar():
    bars = [_hb(D4, 14, 62000.0), _hb(D4, 15, 99999.0), _hb(D5, 7, 62310.0)]  # 15:00〜16:00の足は15:30時点で未完結
    _, base, _ = futures_move(bars, D5, D4)
    assert base.close == 62000.0


def test_f5_stale_latest_bar_is_unknown():
    tue = date(2026, 11, 10)  # 火曜（月曜以外）は3時間より古い足は不明
    bars = [_hb(D5, 14, 62000.0), _hb(tue, 3, 62310.0)]  # 3:00〜4:00の足は8:30の4時間半前
    assert futures_move(bars, tue, D5) is None
    fg, reason = compute_futures_gap(bars, {D5: 0.0}, tue, "NIY=F", min_n=1)
    assert fg is None and "古い" in reason


def test_f6_fetch_failure_is_unknown():
    fg, reason = compute_futures_gap([], {D4: 0.0}, D5, "NIY=F")
    assert fg is None and "取得に失敗" in reason


def test_f7_no_base_bar_is_unknown():
    assert futures_move([_hb(D5, 7, 62310.0)], D5, D4) is None


def test_f8_not_enough_pairs():
    bars = [_hb(D4, 14, 62000.0), _hb(D5, 7, 62310.0)]
    fg, reason = compute_futures_gap(bars, {D4: 0.0}, D5, "NIY=F", min_n=60)
    assert fg is None and "データが足りません" in reason


# --- 保存・表示 ---
def _fg():
    from analysis.futures_gap import FuturesGap

    return FuturesGap("NIY=F", 0.005, "2026-11-06 15:00", "2026-11-09 08:00", 0.9, 0.0045, 250, 460, 0.92, 0.0034, 0.0068, 0.83)


def test_premarket_json_roundtrip_with_futures(tmp_path):
    p = tmp_path / "premarket.json"
    save_premarket(p, _pm(futures=_fg()))
    assert load_premarket(p).futures == _fg()
    save_premarket(p, _pm())  # 旧形式（先物なし）も読める
    assert load_premarket(p).futures is None


def test_site_shows_futures_rows(tmp_path):
    page = _page(tmp_path, _pm(for_date=date(2026, 11, 10), futures=_fg()))
    assert '<div class="env-k">日経225先物（夜間）の動き</div>' in page
    assert "CME NIY=F（Yahoo Finance・1時間足）｜2026-11-06 15:00頃 → 2026-11-09 08:00頃" in page
    assert "想定ギャップの目安・先物ベース（日本株全体の平均）" in page
    assert "方向一致 83%・相関 0.92・平均誤差 0.34%（常に0と予測した場合 0.68%）" in page


def test_site_shows_futures_failure_reason(tmp_path):
    page = _page(tmp_path, _pm(for_date=date(2026, 11, 10), futures_note="先物の取得に失敗しました（取得制限・休場など）"))
    assert '<div class="env-k">日経225先物（夜間）の動き</div><div class="env-v">不明</div>' in page
    assert "先物の取得に失敗しました" in page


def test_monday_allows_weekend_closure_gap():
    fri, mon = date(2026, 11, 6), date(2026, 11, 9)
    bars = [_hb(fri, 14, 62000.0), _hb(date(2026, 11, 7), 5, 62310.0)]  # 土曜5:00〜6:00が最後の足（月曜8:30の50時間前）
    x, _, target = futures_move(bars, mon, fri)
    assert x == pytest.approx(0.005)
    assert futures_move(bars, date(2026, 11, 10), fri) is None  # 火曜は同じ古さなら不明
