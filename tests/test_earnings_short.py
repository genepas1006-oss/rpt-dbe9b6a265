"""analysis.earnings の売り（ショート）候補スコアリングのテスト。

承認済みのサンプルデータ手計算（2026-10-26合意分）をテストケース化する。
"""

from datetime import date, timedelta

from analysis.earnings import compute_short_earnings_score
from data_sources.base import DailyBar

BASE_DATE = date(2026, 1, 1)


def _build_bars(length: int, drift_at_index: dict) -> list[DailyBar]:
    closes = [1000.0] * length
    for idx, ret in drift_at_index.items():
        closes[idx + 5] = closes[idx] * (1 + ret)

    return [
        DailyBar(
            trade_date=BASE_DATE + timedelta(days=i),
            open=closes[i],
            high=closes[i],
            low=closes[i],
            close=closes[i],
            volume=1000,
        )
        for i in range(length)
    ]


def test_strong_short_signal_with_negative_drift_history():
    # 過去4回(idx10,40,70,100)のドリフト実績: -4%,-3%,-1%,-2% → 平均-2.5%
    # 直近決算(idx130)から2営業日後(idx132)が「今日」(反応期間内)
    hist = {10: -0.04, 40: -0.03, 70: -0.01, 100: -0.02}
    bars = _build_bars(length=133, drift_at_index=hist)
    earnings_dates = [BASE_DATE + timedelta(days=i) for i in (10, 40, 70, 100, 130)]

    result = compute_short_earnings_score(bars, earnings_dates)

    assert result is not None
    assert result.days_since_earnings == 2
    assert result.in_reaction_window is True
    assert round(result.post_earnings_drift_avg, 4) == round(
        (-0.04 - 0.03 - 0.01 - 0.02) / 4, 4
    )
    assert result.earnings_score == 2


def test_weak_negative_drift_scores_one_point():
    # 過去4回のドリフト平均-0.5%（0%以下だが-2%未満ではない）
    hist = {10: -0.01, 40: 0.0, 70: -0.01, 100: 0.0}
    bars = _build_bars(length=133, drift_at_index=hist)
    earnings_dates = [BASE_DATE + timedelta(days=i) for i in (10, 40, 70, 100, 130)]

    result = compute_short_earnings_score(bars, earnings_dates)

    assert result is not None
    assert result.earnings_score == 1


def test_positive_drift_scores_zero():
    hist = {10: 0.04, 40: 0.03, 70: 0.05, 100: 0.02}
    bars = _build_bars(length=133, drift_at_index=hist)
    earnings_dates = [BASE_DATE + timedelta(days=i) for i in (10, 40, 70, 100, 130)]

    result = compute_short_earnings_score(bars, earnings_dates)

    assert result is not None
    assert result.earnings_score == 0
    assert result.reasons == []
