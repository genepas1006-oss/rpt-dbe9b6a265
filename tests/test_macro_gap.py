"""analysis.macro_gap のテスト（2026-11-09承認の手計算ケース・先読みなし）。"""

from datetime import date, timedelta

import pytest

from analysis.macro_gap import (
    ForecastEval,
    evaluate_forecasts,
    expected_gap,
    fit_slope,
    latest_before,
    previous_weekday,
    rolling_forecasts,
)


def _days(n, start=date(2026, 1, 5)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


# ---------------- 傾きと想定ギャップ ----------------
def test_slope_hand_calc_from_proposal():
    pairs = [(1.0, 0.6), (-1.0, -0.8), (2.0, 1.4), (-2.0, -1.2), (0.0, 0.1)]
    # Σxy = 0.6+0.8+2.8+2.4+0 = 6.6 / Σx² = 1+1+4+4+0 = 10 → 0.66
    assert fit_slope(pairs) == pytest.approx(0.66)
    assert expected_gap(0.66, 1.5) == pytest.approx(0.99)  # 米国+1.5% → 約+1.0%


def test_slope_has_no_intercept():
    # y=3 のように定数だけの動きでも、切片は持たない: Σxy/Σx² = (1*3+2*3)/(1+4) = 1.8
    assert fit_slope([(1.0, 3.0), (2.0, 3.0)]) == pytest.approx(1.8)


def test_slope_negative_and_scale():
    assert fit_slope([(1.0, -0.5), (2.0, -1.0)]) == pytest.approx(-0.5)
    assert fit_slope([(10.0, 5.0), (20.0, 10.0)]) == pytest.approx(0.5)


def test_slope_degenerate_inputs():
    assert fit_slope([]) is None
    assert fit_slope([(0.0, 1.0), (0.0, 2.0)]) is None  # xが全て0


# ---------------- 日付合わせ ----------------
def test_latest_before_excludes_the_day_itself():
    s = {date(2026, 11, 6): 0.01, date(2026, 11, 9): -0.02}
    assert latest_before(date(2026, 11, 9), s) == (date(2026, 11, 6), 0.01)
    assert latest_before(date(2026, 11, 10), s) == (date(2026, 11, 9), -0.02)
    assert latest_before(date(2026, 11, 6), s) is None


def test_previous_weekday_skips_weekend():
    assert previous_weekday(date(2026, 11, 9)) == date(2026, 11, 6)   # 月曜 → 金曜
    assert previous_weekday(date(2026, 11, 10)) == date(2026, 11, 9)
    assert previous_weekday(date(2026, 11, 7)) == date(2026, 11, 6)   # 土曜 → 金曜


# ---------------- 過去の精度（手計算） ----------------
def _series(xs, ys, window_days=None):
    ds = _days(len(xs) + 1)
    # 日本の営業日 ds[i+1] に対して、米国は ds[i]（その前の日）の値を使う
    us = {ds[i]: x for i, x in enumerate(xs)}
    gaps = {ds[i + 1]: y for i, y in enumerate(ys)}
    return us, gaps, ds


def test_rolling_forecast_hand_calc():
    xs = [1, 2, -1, 3, -2]
    ys = [0.6, 1.0, -0.4, 1.2, -1.1]
    us, gaps, ds = _series(xs, ys)
    fc = rolling_forecasts(us, gaps, window=3, min_n=3)
    assert [d for d, _, _ in fc] == [ds[4], ds[5]]  # 最初の3日は学習用
    # 4日目: 1〜3日 Σxy=0.6+2.0+0.4=3.0, Σx²=6 → 0.5 → 予測 0.5*3=1.5（実際1.2）
    assert fc[0][1] == pytest.approx(1.5) and fc[0][2] == 1.2
    # 5日目: 2〜4日 Σxy=2.0+0.4+3.6=6.0, Σx²=14 → 0.428571 → 予測 -0.857143（実際-1.1）
    assert fc[1][1] == pytest.approx(6.0 / 14 * -2) and fc[1][2] == -1.1


def test_evaluate_hand_calc():
    xs = [1, 2, -1, 3, -2]
    ys = [0.6, 1.0, -0.4, 1.2, -1.1]
    us, gaps, _ = _series(xs, ys)
    ev = evaluate_forecasts(rolling_forecasts(us, gaps, window=3, min_n=3))
    assert ev.n == 2
    assert ev.mae == pytest.approx((0.3 + (1.1 - 6 / 7)) / 2)           # ≒ 0.2714
    assert ev.mae_zero == pytest.approx((1.2 + 1.1) / 2)                 # 常に0予測のMAE 1.15
    assert ev.direction_acc == 1.0
    assert ev.mean_error == pytest.approx((0.3 + (-6 / 7 + 1.1)) / 2)    # 予測-実際の平均 ≒ +0.2714
    assert ev.corr is None  # 2点では相関を出さない


def test_perfect_linear_relation_gives_corr_one_and_zero_error():
    xs = [(-1) ** i * (1 + (i % 5)) / 10 for i in range(120)]
    ys = [0.7 * x for x in xs]
    us, gaps, _ = _series(xs, ys)
    ev = evaluate_forecasts(rolling_forecasts(us, gaps, window=50, min_n=30))
    assert ev.n == 120 - 30
    assert ev.corr == pytest.approx(1.0)
    assert ev.mae == pytest.approx(0.0, abs=1e-12)
    assert ev.direction_acc == 1.0 and ev.mae < ev.mae_zero


def test_anti_correlated_relation_with_fixed_wrong_sign_is_detected():
    # 傾きは学習するので負の関係も当たる。相関は+1（予測が実際と一致）
    xs = [(-1) ** i * (1 + (i % 4)) / 10 for i in range(100)]
    ys = [-0.5 * x for x in xs]
    us, gaps, _ = _series(xs, ys)
    ev = evaluate_forecasts(rolling_forecasts(us, gaps, window=40, min_n=20))
    assert ev.corr == pytest.approx(1.0) and ev.direction_acc == 1.0


# ---------------- 先読みがないこと ----------------
def test_prediction_ignores_the_day_and_later_actuals():
    xs = [1, 2, -1, 3, -2, 1.5, -1.5]
    ys = [0.6, 1.0, -0.4, 1.2, -1.1, 0.7, -0.9]
    us, gaps, ds = _series(xs, ys)
    base = rolling_forecasts(us, gaps, window=3, min_n=3)
    changed_gaps = dict(gaps)
    for d in ds[5:]:                      # 5日目以降の実際の値を極端に変える
        if d in changed_gaps:
            changed_gaps[d] = 99.0
    changed = rolling_forecasts(us, changed_gaps, window=3, min_n=3)
    # 5日目の予測は、5日目の実際の値に影響されない（予測値は同じ）
    p_base = {d: p for d, p, _ in base}
    p_changed = {d: p for d, p, _ in changed}
    assert p_base[ds[5]] == pytest.approx(p_changed[ds[5]])
    assert p_base[ds[4]] == pytest.approx(p_changed[ds[4]])


def test_us_return_alignment_uses_latest_strictly_before():
    ds = _days(70)
    us = {d: 0.01 for d in ds}
    us[ds[40]] = 5.0            # 日本の ds[40] と同じ日の米国値は、ds[40] の予測に使わない
    gaps = {d: 0.0065 for d in ds[1:]}
    fc = {d: (p, a) for d, p, a in rolling_forecasts(us, gaps, window=30, min_n=10)}
    # ds[40] の予測に使う米国値は ds[39] の 0.01（5.0 ではない）→ 傾き0.65×0.01
    assert fc[ds[40]][0] == pytest.approx(0.65 * 0.01, rel=1e-6)


def test_min_n_and_missing_us_days_are_skipped():
    ds = _days(20)
    us = {d: 0.01 * (i % 3 - 1) for i, d in enumerate(ds)}
    gaps = {d: 0.005 for d in ds[1:]}
    assert rolling_forecasts(us, gaps, window=10, min_n=60) == []   # 学習に必要な組が足りない
    assert rolling_forecasts({}, gaps) == []


def test_evaluate_empty_and_zero_actuals():
    assert evaluate_forecasts([]) == ForecastEval(0, None, None, None, None, None, None, None)
    d = date(2026, 1, 5)
    ev = evaluate_forecasts([(d, 0.1, 0.0), (d, -0.1, 0.0)])
    assert ev.direction_acc is None  # 実際が0の日だけなら方向は判定しない
    ev2 = evaluate_forecasts([(d, 0.1, 0.2), (d, 0.0, 0.3), (d, -0.1, -0.2)])
    assert ev2.direction_acc == pytest.approx(2 / 3)  # 予測0は一致とみなさない
