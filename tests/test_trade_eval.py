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
