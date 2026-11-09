"""tracking.trade_eval のテスト（約定境界・不成立・同値の扱い）。"""

import pytest

from tracking.trade_eval import evaluate_trade


def test_buy_filled_win():
    r = evaluate_trade("buy", 995.0, low=990, high=1010, close=1005)
    assert r.filled and r.is_win is True
    assert r.result_return == pytest.approx(10 / 995)  # +1.005%


def test_buy_filled_loss():
    r = evaluate_trade("buy", 995.0, low=975, high=1000, close=980)
    assert r.filled and r.is_win is False
    assert r.result_return == pytest.approx(-15 / 995)  # -1.508%


def test_buy_unfilled():
    r = evaluate_trade("buy", 1990.0, low=1995, high=2050, close=2040)
    assert (r.filled, r.result_return, r.is_win) == (False, None, None)


def test_buy_low_equal_to_entry_is_filled():
    assert evaluate_trade("buy", 1000.0, low=1000, high=1010, close=1005).filled is True


def test_buy_low_just_above_entry_is_unfilled():
    assert evaluate_trade("buy", 1000.0, low=1000.01, high=1010, close=1005).filled is False


def test_sell_filled_win():
    r = evaluate_trade("sell", 502.5, low=495, high=510, close=498)
    assert r.filled and r.is_win is True
    assert r.result_return == pytest.approx(4.5 / 502.5)  # +0.896%


def test_sell_filled_loss():
    r = evaluate_trade("sell", 100.0, low=99, high=110, close=108)
    assert r.filled and r.is_win is False
    assert r.result_return == pytest.approx(-0.08)


def test_sell_unfilled():
    r = evaluate_trade("sell", 1005.0, low=950, high=1004, close=960)
    assert (r.filled, r.result_return, r.is_win) == (False, None, None)


def test_sell_high_equal_to_entry_is_filled():
    assert evaluate_trade("sell", 1000.0, low=990, high=1000, close=995).filled is True


def test_zero_return_is_filled_but_not_a_win():
    r = evaluate_trade("buy", 100.0, low=99, high=101, close=100)
    assert r.filled and r.result_return == 0.0 and r.is_win is False


# ---- 承認済み（2026-11-09）: 寄り値が指値より有利なら寄り値で約定する ----
@pytest.mark.parametrize(
    "side,low,high,close,open_,fill,ret,win",
    [
        ("buy", 995, 1015, 1004, 1010, 1000.0, 0.004, True),          # B1 寄りが指値より不利 → 指値で約定
        ("buy", 975, 995, 990, 980, 980.0, 10 / 980, True),           # B2 ギャップダウン → 寄り値で約定（従来式は-1.0%）
        ("buy", 1000, 1010, 1000, 1000, 1000.0, 0.0, False),          # B3 同値 → リターン0（的中でない）
        ("sell", 990, 1005, 998, 990, 1000.0, 0.002, True),           # S1 寄りが指値より不利 → 指値で約定
        ("sell", 1010, 1025, 1015, 1020, 1020.0, 5 / 1020, True),     # S2 ギャップアップ → 寄り値で約定（従来式は-1.5%）
        ("sell", 1010, 1025, 1030, 1020, 1020.0, -10 / 1020, False),  # S3
    ],
)
def test_fill_at_open_when_better(side, low, high, close, open_, fill, ret, win):
    r = evaluate_trade(side, 1000.0, low=low, high=high, close=close, open_price=open_)
    assert r.filled and r.fill_price == pytest.approx(fill)
    assert r.result_return == pytest.approx(ret)
    assert r.is_win is win


def test_unfilled_cases_with_open():
    b4 = evaluate_trade("buy", 1000.0, low=1001, high=1010, close=1005, open_price=1005)
    s4 = evaluate_trade("sell", 1000.0, low=990, high=999, close=995, open_price=995)
    assert (b4.filled, b4.result_return, b4.fill_price) == (False, None, None)
    assert (s4.filled, s4.result_return, s4.fill_price) == (False, None, None)


def test_without_open_falls_back_to_entry_price():  # B5
    r = evaluate_trade("buy", 1000.0, low=975, high=995, close=990)
    assert r.fill_price == 1000.0 and r.result_return == pytest.approx(-0.01)
