"""analysis.indicators のテスト（2026-11-06承認の手計算ケース）。"""

import pytest

from analysis.indicators import ma_deviation, market_bias, rsi_simple


def _closes_from_changes(start: float, changes: list[float]) -> list[float]:
    out = [start]
    for c in changes:
        out.append(out[-1] + c)
    return out


# ---- 25日移動平均からの乖離率 ----
def test_ma_deviation_hand_calc():
    # MA = (24*100 + 110) / 25 = 100.4 / 乖離 = (110-100.4)/100.4
    closes = [100.0] * 24 + [110.0]
    assert ma_deviation(closes) == pytest.approx(9.6 / 100.4)
    assert ma_deviation(closes) == pytest.approx(0.0956175, abs=1e-6)


def test_ma_deviation_negative():
    # MA = (24*100 + 90) / 25 = 99.6 / 乖離 = (90-99.6)/99.6
    closes = [100.0] * 24 + [90.0]
    assert ma_deviation(closes) == pytest.approx(-9.6 / 99.6)


def test_ma_deviation_flat_is_zero():
    assert ma_deviation([100.0] * 25) == 0.0


def test_ma_deviation_uses_only_last_25():
    # 古い値は無視される: 先頭に極端な値を足しても結果は同じ
    base = [100.0] * 24 + [110.0]
    assert ma_deviation([9999.0, 1.0] + base) == pytest.approx(ma_deviation(base))


def test_ma_deviation_insufficient_data_is_none():
    assert ma_deviation([100.0] * 24) is None
    assert ma_deviation([]) is None


def test_ma_deviation_zero_average_is_none():
    assert ma_deviation([0.0] * 25) is None


# ---- RSI(14日, 単純平均版) ----
def test_rsi_hand_calc_mixed():
    # +2 が7回, -1 が7回: 平均上昇 14/14=1.0, 平均下落 7/14=0.5 → RS=2 → 100-100/3
    closes = _closes_from_changes(100.0, [2, -1] * 7)
    assert len(closes) == 15
    assert rsi_simple(closes) == pytest.approx(100 - 100 / 3)
    assert rsi_simple(closes) == pytest.approx(66.6667, abs=1e-4)


def test_rsi_all_up_is_100():
    assert rsi_simple(_closes_from_changes(100.0, [1] * 14)) == 100.0


def test_rsi_all_down_is_0():
    assert rsi_simple(_closes_from_changes(100.0, [-1] * 14)) == 0.0


def test_rsi_flat_is_50():
    assert rsi_simple([100.0] * 15) == 50.0


def test_rsi_symmetric_changes_is_50():
    # 上昇合計=下落合計 → RS=1 → 50
    assert rsi_simple(_closes_from_changes(100.0, [1, -1] * 7)) == pytest.approx(50.0)


def test_rsi_uses_only_last_15_closes():
    recent = _closes_from_changes(100.0, [2, -1] * 7)
    assert rsi_simple([5.0, 500.0, 1.0] + recent) == pytest.approx(rsi_simple(recent))


def test_rsi_insufficient_data_is_none():
    assert rsi_simple([100.0] * 14) is None  # 前日比が13個しか取れない
    assert rsi_simple([]) is None


# ---- 地合い ----
def test_market_bias_above_ma_is_plus_one():
    # MA = (2400+101)/25 = 100.04 → 101 >= 100.04
    assert market_bias([100.0] * 24 + [101.0]) == 1


def test_market_bias_below_ma_is_minus_one():
    # MA = (2400+99)/25 = 99.96 → 99 < 99.96
    assert market_bias([100.0] * 24 + [99.0]) == -1


def test_market_bias_equal_to_ma_is_plus_one():
    # 全て100 → MA=100, 終値100 は「以上」なので +1
    assert market_bias([100.0] * 25) == 1


def test_market_bias_insufficient_data_is_none():
    assert market_bias([100.0] * 24) is None
