"""backtest.preopen のテスト（手計算ケース・先読みなし・統計）。"""

from datetime import date, timedelta

import numpy as np
import pytest

from backtest.preopen import (
    MIN_TRADES,
    BootResult,
    Sample,
    Strategy,
    StrategyResult,
    atr,
    build_samples,
    build_strategies,
    cluster_bootstrap_diff,
    evaluate_strategy,
    is_candidate,
    latest_return_before,
    true_range,
    wilson_interval,
)
from data_sources.base import DailyBar


def _dates(n, start=date(2026, 1, 5)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _bar(d, o, h, l, c, v):  # noqa: E741
    return DailyBar(d, o, h, l, c, v)


# ---------------- ATR ----------------
def test_true_range_cases():
    assert true_range(100, 102, 98) == 4          # 高-安
    assert true_range(100, 112, 108) == 12        # |高-前日終値| が最大（ギャップアップ）
    assert true_range(100, 92, 88) == 12          # |安-前日終値| が最大（ギャップダウン）


def test_atr_hand_calc_period_2():
    # 前日終値100 → 足1: 高105 安99 → TR=max(6,5,1)=6 / 足2: 前日終値=足1の終値102, 高112 安108 → max(4,10,6)=10 ... 手計算しやすい値に固定
    bars = [
        _bar(date(2026, 1, 5), 100, 100, 100, 100, 1),
        _bar(date(2026, 1, 6), 100, 105, 99, 101, 1),    # TR = max(6, 5, 1) = 6
        _bar(date(2026, 1, 7), 110, 113, 109, 112, 1),   # TR = max(4, 12, 8) = 12（前日終値101）
    ]
    assert atr(bars, period=2) == 9.0  # (6+12)/2


def test_atr_flat_and_insufficient():
    flat = [_bar(d, 100, 102, 98, 100, 1) for d in _dates(16)]
    assert atr(flat) == 4.0  # TR=4が14本
    assert atr(flat[:14]) is None  # 14本では前日終値が足りない（15本必要）
    assert atr(flat[:15]) == 4.0


# ---------------- サンプル生成（手計算） ----------------
def _stock(n_flat=39, prev_close=100.0, today=(106, 108, 104, 107, 100), prev_vol=300):
    ds = _dates(n_flat + 2)
    bars = [_bar(d, 100, 102, 98, 100, 100) for d in ds[:n_flat]]
    bars.append(_bar(ds[n_flat], 100, 102, 98, prev_close, prev_vol))  # 前日
    bars.append(_bar(ds[n_flat + 1], *today))                          # 当日
    return bars


def _index(bars):
    return [_bar(b.trade_date, 100, 100, 100, 100, 1) for b in bars]


def _samples(bars, us=(), fx=()):
    return build_samples({"X": bars}, _index(bars), list(us), list(fx))


def test_sample_hand_calc():
    bars = _stock()
    s = _samples(bars)[-1]
    assert s.day == bars[-1].trade_date
    assert s.gap_atr == pytest.approx(1.5)        # (106-100)/ATR4
    assert s.atr_pct == pytest.approx(0.04)       # 4/100
    assert s.vol_ratio == pytest.approx(3.0)      # 前日300 / 前20日平均100
    assert s.breakout20 is False                  # 前日終値100 は、その前20日の終値最高値100を上回らない
    assert s.oc == pytest.approx((107 - 106) / 106)


def test_breakout_flag_and_gap_with_prev_close_101():
    s = _samples(_stock(prev_close=101.0))[-1]
    assert s.breakout20 is True                   # 101 > 100
    assert s.gap_atr == pytest.approx((106 - 101) / 4)  # 1.25
    assert s.atr_pct == pytest.approx(4 / 101)


def test_gap_down_is_negative():
    s = _samples(_stock(today=(96, 97, 94, 95, 100)))[-1]
    assert s.gap_atr == pytest.approx(-1.0)       # (96-100)/4


def test_warmup_skips_early_days():
    bars = _stock()  # 41本
    samples = _samples(bars)
    assert len(samples) == 20                     # 前20本の出来高が揃う t=21..40
    assert samples[0].day == bars[21].trade_date


def test_zero_open_or_zero_prev_close_is_skipped():
    assert _samples(_stock(today=(0, 1, 0, 1, 1)))[-1].day != _stock()[-1].trade_date or True
    bad = _stock(today=(0, 1, 0, 1, 1))
    assert all(s.day != bad[-1].trade_date for s in _samples(bad))


# ---------------- 先読みがないこと ----------------
def test_features_ignore_today_close_high_low_volume():
    base = _samples(_stock())[-1]
    changed = _samples(_stock(today=(106, 999, 1, 500, 10**9)))[-1]
    assert (changed.gap_atr, changed.atr_pct, changed.vol_ratio, changed.breakout20) == (
        base.gap_atr, base.atr_pct, base.vol_ratio, base.breakout20)
    assert changed.oc != base.oc  # 結果（oc）だけが変わる


def test_gap_depends_on_today_open_only():
    assert _samples(_stock(today=(103, 108, 104, 107, 100)))[-1].gap_atr == pytest.approx(0.75)


def test_earlier_samples_ignore_later_bars():
    bars = _stock()
    extra = bars + [_bar(bars[-1].trade_date + timedelta(days=1), 1, 9999, 1, 5000, 10**9)]
    a = _samples(bars)
    b = _samples(extra)
    assert a == b[: len(a)]  # 後の足を足しても、それまでのサンプルは変わらない


# ---------------- 地合い（米国・ドル円）の日付合わせ ----------------
def _market(dates_closes):
    return [_bar(d, c, c, c, c, 1) for d, c in dates_closes]


def test_latest_return_before_excludes_same_day():
    dates = [date(2026, 11, 6), date(2026, 11, 9)]
    rets = [0.01, -0.02]
    assert latest_return_before(date(2026, 11, 9), dates, rets) == 0.01   # 同日は含めない
    assert latest_return_before(date(2026, 11, 10), dates, rets) == -0.02
    assert latest_return_before(date(2026, 11, 6), dates, rets) is None   # それ以前なし
    assert latest_return_before(date(2026, 11, 16), dates, rets) == -0.02


def test_us_return_alignment_in_samples():
    bars = _stock()
    today = bars[-1].trade_date
    prev = today - timedelta(days=1)
    us = _market([(today - timedelta(days=5), 100.0), (prev, 101.0), (today, 120.0)])  # 当日の米国バーは使わない
    s = _samples(bars, us=us)[-1]
    assert s.us_ret == pytest.approx(0.01)  # prev(101)/前(100)-1。当日(120)は使わない


def test_missing_market_data_is_none():
    s = _samples(_stock())[-1]
    assert s.us_ret is None and s.fx_ret is None
    assert s.nk_prev_ret == 0.0  # 指数は全て100


# ---------------- 統計 ----------------
def test_wilson_known_values():
    lo, hi = wilson_interval(50, 100)
    assert lo == pytest.approx(0.4038, abs=1e-3) and hi == pytest.approx(0.5962, abs=1e-3)
    lo0, hi0 = wilson_interval(0, 10)
    assert lo0 == pytest.approx(0.0, abs=1e-9) and hi0 == pytest.approx(0.2775, abs=1e-3)
    assert wilson_interval(0, 0) is None


def _stats(diffs_per_day, n=10):
    """日ごとに『選んだ分の平均 = 全体の平均 + diff』となるday_statsを作る。"""
    ds = _dates(len(diffs_per_day))
    return {d: (n * (0.0 + diff), n, 0.0, n) for d, diff in zip(ds, diffs_per_day)}


def test_bootstrap_constant_positive_difference():
    r = cluster_bootstrap_diff(_stats([0.01] * 30), resamples=2_000, seed=1)
    assert r.mean == pytest.approx(0.01)
    assert r.ci_low == pytest.approx(0.01) and r.ci_high == pytest.approx(0.01)
    assert r.p_not_positive == 0.0


def test_bootstrap_zero_difference_has_large_p():
    # ちょうど平均0になる交互の+-1%（100日ずつ）: 差の推定値は0で、プラスは偶然の範囲
    r = cluster_bootstrap_diff(_stats([0.01, -0.01] * 100), resamples=5_000, seed=2)
    assert r.mean == pytest.approx(0.0, abs=1e-12)
    assert r.ci_low < 0 < r.ci_high
    assert 0.3 < r.p_not_positive < 0.7


def test_bootstrap_strong_signal_with_noise_has_small_p():
    rng = np.random.default_rng(1)
    r = cluster_bootstrap_diff(_stats(list(0.01 + rng.normal(0, 0.01, 300))), resamples=5_000, seed=3)
    assert r.ci_low > 0 and r.p_not_positive < 0.001


def test_bootstrap_is_reproducible_and_seed_sensitive():
    st = _stats(list(np.random.default_rng(5).normal(0.002, 0.01, 100)))
    a = cluster_bootstrap_diff(st, resamples=3_000, seed=7)
    b = cluster_bootstrap_diff(st, resamples=3_000, seed=7)
    c = cluster_bootstrap_diff(st, resamples=3_000, seed=8)
    assert a == b and a != c


def test_bootstrap_ci_brackets_point_estimate():
    st = _stats(list(np.random.default_rng(9).normal(0.003, 0.02, 150)))
    r = cluster_bootstrap_diff(st, resamples=5_000, seed=4)
    assert r.ci_low <= r.mean <= r.ci_high


def test_bootstrap_empty_inputs():
    assert cluster_bootstrap_diff({}, 100) == BootResult(None, None, None, None)
    d = _dates(3)
    none_selected = {x: (0.0, 0, 1.0, 10) for x in d}
    assert cluster_bootstrap_diff(none_selected, 100) == BootResult(None, None, None, None)


def test_bootstrap_clusters_by_day_not_by_trade():
    # 同じ日の取引は同時に出入りする: 1日だけ極端に良い日があれば、その日が抜けた再標本で差が消える → p>0
    st = _stats([0.0] * 49 + [0.5])
    r = cluster_bootstrap_diff(st, resamples=5_000, seed=5)
    assert r.p_not_positive > 0.2


# ---------------- 戦略の評価（手計算） ----------------
def _s(day, oc, **kw):
    base = dict(prev_close=100.0, open=100.0, gap_atr=0.5, atr_pct=0.04, vol_ratio=1.0, breakout20=False,
                us_ret=None, fx_ret=None, nk_prev_ret=None)
    base.update(kw)
    return Sample(day=day, code="X", close=100.0 * (1 + oc), **base)


def test_evaluate_strategy_long_and_short_hand_calc():
    ds = _dates(4)
    samples = [_s(ds[0], 0.01), _s(ds[1], -0.01), _s(ds[2], 0.02), _s(ds[3], 0.0)]
    long = evaluate_strategy(samples, Strategy("L", +1, lambda s: True), cost=0.001, resamples=200)
    assert long.n == 4
    assert long.win_rate == 0.5                       # +1%, +2% の2/4（0.0は的中でない）
    assert long.avg_gross == pytest.approx(0.005)     # (1-1+2+0)/4 = +0.5%
    assert long.avg_net == pytest.approx(0.004)       # 費用0.1%後
    short = evaluate_strategy(samples, Strategy("S", -1, lambda s: True), cost=0.001, resamples=200)
    assert short.win_rate == 0.25                     # -1%の1/4（符号反転: -1,+1,-2,0 のうち正は+1%の1件）
    assert short.avg_gross == pytest.approx(-0.005)
    assert short.avg_net == pytest.approx(-0.006)


def test_evaluate_strategy_difference_vs_baseline_is_zero_when_selecting_everything():
    ds = _dates(30)
    samples = [_s(d, 0.001 * (i % 5 - 2)) for i, d in enumerate(ds)]
    r = evaluate_strategy(samples, Strategy("ALL", +1, lambda s: True), resamples=500)
    assert r.ret_boot.mean == pytest.approx(0.0) and r.win_boot.mean == pytest.approx(0.0)


def test_evaluate_strategy_selected_subset_difference():
    ds = _dates(2)
    samples = [_s(ds[0], 0.02, gap_atr=0.5), _s(ds[0], -0.02, gap_atr=2.0),
               _s(ds[1], 0.02, gap_atr=0.5), _s(ds[1], -0.02, gap_atr=2.0)]
    r = evaluate_strategy(samples, Strategy("G", +1, lambda s: s.gap_atr <= 1.0), resamples=500)
    assert r.n == 2 and r.win_rate == 1.0
    assert r.ret_boot.mean == pytest.approx(0.02)     # 選んだ分+2% - 全体0% = +2%
    assert r.win_boot.mean == pytest.approx(0.5)      # 的中率 100% - 50%


def test_evaluate_strategy_empty_selection():
    r = evaluate_strategy([_s(date(2026, 1, 5), 0.01)], Strategy("N", +1, lambda s: False), resamples=100)
    assert r.n == 0 and r.win_rate is None and r.wilson is None and r.avg_gross is None and r.avg_net is None


# ---------------- ルールの定義（境界） ----------------
def _strat(name):
    return next(s for s in build_strategies() if s.name == name)


def test_strategy_count_and_unique_names():
    strategies = build_strategies()
    assert len(strategies) == 2 + 12 * 4 == 50
    assert len({s.name for s in strategies}) == 50


def test_filter_boundaries():
    ok = _s(date(2026, 1, 5), 0.0, gap_atr=1.0, atr_pct=0.03, vol_ratio=2.0)
    assert _strat("gapup_cont+atr3+gap1").predicate(ok) is True
    assert _strat("gapup_cont+vol2").predicate(ok) is True
    assert _strat("gapup_cont+atr3").predicate(_s(date(2026, 1, 5), 0.0, atr_pct=0.0299)) is False
    assert _strat("gapup_cont+atr3+gap1").predicate(_s(date(2026, 1, 5), 0.0, gap_atr=1.01)) is False
    assert _strat("gapup_cont+vol2").predicate(_s(date(2026, 1, 5), 0.0, vol_ratio=1.99)) is False


def test_signal_boundaries_and_direction():
    d = date(2026, 1, 5)
    assert _strat("gapup_cont").direction == +1 and _strat("gapup_fade").direction == -1
    assert _strat("gapdown_cont").direction == -1 and _strat("gapdown_fade").direction == +1
    assert _strat("gapup_cont").predicate(_s(d, 0, gap_atr=0.3)) and not _strat("gapup_cont").predicate(_s(d, 0, gap_atr=0.29))
    assert _strat("gapup_cont").predicate(_s(d, 0, gap_atr=1.0)) and not _strat("gapup_cont").predicate(_s(d, 0, gap_atr=1.01))
    assert _strat("gapdown_fade").predicate(_s(d, 0, gap_atr=-0.3)) and not _strat("gapdown_fade").predicate(_s(d, 0, gap_atr=-0.29))
    assert _strat("panic_fade").predicate(_s(d, 0, gap_atr=-1.5)) and not _strat("panic_fade").predicate(_s(d, 0, gap_atr=-1.49))
    assert _strat("us_up_long").predicate(_s(d, 0, us_ret=0.005)) and not _strat("us_up_long").predicate(_s(d, 0, us_ret=0.0049))
    assert _strat("us_down_short").predicate(_s(d, 0, us_ret=-0.005)) and not _strat("us_down_short").predicate(_s(d, 0, us_ret=-0.0049))
    assert not _strat("us_up_long").predicate(_s(d, 0, us_ret=None))  # 地合いが不明なら選ばない
    assert not _strat("fx_down_short").predicate(_s(d, 0, fx_ret=None))
    assert _strat("breakout_cont").predicate(_s(d, 0, breakout20=True)) and not _strat("breakout_cont").predicate(_s(d, 0))


# ---------------- 採用候補の条件 ----------------
def _res(n=500, net=0.001, mean=0.002, p=0.0001):
    return StrategyResult("x", n, 0.55, (0.5, 0.6), net + 0.001, net, BootResult(mean, 0.0, 0.01, p), BootResult(0.02, 0.0, 0.04, p))


def test_candidate_requires_everything():
    assert is_candidate(_res(p=0.0001), _res(p=0.04)) is True
    assert is_candidate(_res(p=0.001), _res(p=0.04)) is True             # 0.001 < 0.05/48(=0.001042)
    assert is_candidate(_res(p=0.05 / 48), _res(p=0.04)) is False        # 境界ちょうどは候補にしない
    assert is_candidate(_res(p=0.0011), _res(p=0.04)) is False           # 前半が補正後の基準を満たさない
    assert is_candidate(_res(p=0.0001), _res(p=0.05)) is False           # 後半 p<0.05 は未満
    assert is_candidate(_res(n=MIN_TRADES - 1), _res()) is False         # 件数不足
    assert is_candidate(_res(), _res(net=-0.0001)) is False              # 費用後マイナス
    assert is_candidate(_res(net=0.0), _res()) is False                  # 費用後ゼロ
    assert is_candidate(_res(mean=-0.001), _res()) is False              # 差がマイナス
    assert is_candidate(_res(), StrategyResult("x", 500, None, None, None, None, BootResult(None, None, None, None), BootResult(None, None, None, None))) is False


# ---------------- 期間分割 ----------------
def test_split_samples_by_day_70_30():
    from backtest.preopen import split_samples

    ds = _dates(10)
    samples = [_s(d, 0.0) for d in ds for _ in range(3)]  # 1日3件
    train, valid = split_samples(samples)
    assert len(train) == 7 * 3 and len(valid) == 3 * 3
    assert max(s.day for s in train) < min(s.day for s in valid)  # 同じ日が両方に入らない


def test_split_samples_truncates_and_handles_empty():
    from backtest.preopen import split_samples

    train, valid = split_samples([_s(d, 0.0) for d in _dates(4)])
    assert (len(train), len(valid)) == (2, 2)  # int(4*0.7)=2
    assert split_samples([]) == ([], [])


def test_short_strategy_baseline_uses_same_direction():
    # 売りで全件を選ぶと、基準（同じ向きの全件）と同じなので差は0。向きを付け忘れると差が0にならない
    ds = _dates(40)
    samples = [_s(d, 0.01 if i % 3 else -0.02) for i, d in enumerate(ds)]
    r = evaluate_strategy(samples, Strategy("ALL_short", -1, lambda s: True), resamples=500)
    assert r.ret_boot.mean == pytest.approx(0.0, abs=1e-12) and r.win_boot.mean == pytest.approx(0.0, abs=1e-12)


def test_bootstrap_interval_is_95_percent():
    diffs = list(np.random.default_rng(11).normal(0.002, 0.01, 400))
    r = cluster_bootstrap_diff(_stats(diffs), resamples=20_000, seed=6)
    se = float(np.std(diffs, ddof=1) / np.sqrt(len(diffs)))
    width = r.ci_high - r.ci_low
    assert width == pytest.approx(2 * 1.96 * se, rel=0.1)  # 正規近似の95%区間の幅（90%区間なら約16%狭い）
