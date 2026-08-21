"""analysis.technical のテスト。

承認済みのサンプルデータ手計算（2026-08-21合意分）をそのままテストケース化する。
"""

from datetime import date, timedelta

from analysis.technical import compute_technical_score
from data_sources.base import DailyBar


def _make_bars(prior_close: float, prior_volume: float, today_bar: DailyBar, lookback: int = 20) -> list[DailyBar]:
    """直近lookback日分の「当日より前」のバー＋当日バーを組み立てるテスト用ヘルパー。

    出来高平均・前日終値の計算に使われるのは、直近lookback本の出来高全体と
    直前1本（当日の前営業日）の終値のみなので、それ以外の値は固定でよい。
    """
    base_date = today_bar.trade_date - timedelta(days=lookback + 5)
    prior_bars = []
    for i in range(lookback):
        prior_bars.append(
            DailyBar(
                trade_date=base_date + timedelta(days=i),
                open=prior_close,
                high=prior_close,
                low=prior_close,
                close=prior_close,
                volume=prior_volume,
            )
        )
    return prior_bars + [today_bar]


def test_strong_signal_case_a():
    today = DailyBar(
        trade_date=date(2026, 8, 21),
        open=2950,
        high=3020,
        low=2880,
        close=3000,
        volume=45_000_000,
    )
    bars = _make_bars(prior_close=2900, prior_volume=20_000_000, today_bar=today)

    result = compute_technical_score(bars)

    assert result is not None
    assert result.volume_ratio == 2.25
    assert round(result.daily_return, 4) == round((3000 - 2900) / 2900, 4)
    assert round(result.close_position, 3) == round(120 / 140, 3)
    assert result.volume_points == 2
    assert result.return_points == 2
    assert result.close_position_points == 1
    assert result.technical_score == 5


def test_weak_signal_case_b():
    today = DailyBar(
        trade_date=date(2026, 8, 21),
        open=1000,
        high=1020,
        low=995,
        close=1005,
        volume=11_000_000,
    )
    bars = _make_bars(prior_close=1000, prior_volume=10_000_000, today_bar=today)

    result = compute_technical_score(bars)

    assert result is not None
    assert round(result.volume_ratio, 2) == 1.1
    assert round(result.daily_return, 4) == 0.005
    assert round(result.close_position, 2) == 0.4
    assert result.volume_points == 0
    assert result.return_points == 0
    assert result.close_position_points == 0
    assert result.technical_score == 0


def test_insufficient_history_returns_none():
    today = DailyBar(
        trade_date=date(2026, 8, 21),
        open=1000,
        high=1020,
        low=995,
        close=1005,
        volume=11_000_000,
    )
    bars = _make_bars(prior_close=1000, prior_volume=10_000_000, today_bar=today, lookback=5)

    result = compute_technical_score(bars, lookback=20)

    assert result is None


def test_no_range_day_uses_neutral_close_position():
    today = DailyBar(
        trade_date=date(2026, 8, 21),
        open=1000,
        high=1000,
        low=1000,
        close=1000,
        volume=10_000_000,
    )
    bars = _make_bars(prior_close=1000, prior_volume=10_000_000, today_bar=today)

    result = compute_technical_score(bars)

    assert result is not None
    assert result.close_position == 0.5
    assert result.close_position_points == 0
