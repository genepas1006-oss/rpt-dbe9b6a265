"""analysis.technical の売り（ショート）候補スコアリングのテスト。

承認済みのサンプルデータ手計算（2026-10-26合意分）をテストケース化する。
"""

from datetime import date, timedelta

from analysis.technical import compute_short_technical_score
from data_sources.base import DailyBar


def _make_bars(prior_close: float, prior_volume: float, today_bar: DailyBar, lookback: int = 20) -> list[DailyBar]:
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


def test_strong_short_signal():
    # 前日終値1000円→当日970円(-3.0%)、出来高倍率2.5倍、引け位置0.125
    today = DailyBar(
        trade_date=date(2026, 10, 26),
        open=995,
        high=1005,
        low=965,
        close=970,
        volume=250_000,
    )
    bars = _make_bars(prior_close=1000, prior_volume=100_000, today_bar=today)

    result = compute_short_technical_score(bars)

    assert result is not None
    assert round(result.volume_ratio, 2) == 2.5
    assert round(result.daily_return, 4) == -0.03
    assert round(result.close_position, 3) == round(5 / 40, 3)
    assert result.volume_points == 2
    assert result.return_points == 2
    assert result.close_position_points == 1
    assert result.technical_score == 5


def test_weak_short_signal_on_up_day():
    today = DailyBar(
        trade_date=date(2026, 10, 26),
        open=995,
        high=1020,
        low=995,
        close=1010,
        volume=11_000,
    )
    bars = _make_bars(prior_close=1000, prior_volume=10_000, today_bar=today)

    result = compute_short_technical_score(bars)

    assert result is not None
    assert result.return_points == 0
    assert result.close_position_points == 0
    assert result.technical_score == result.volume_points
