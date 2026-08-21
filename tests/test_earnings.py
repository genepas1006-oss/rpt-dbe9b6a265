"""analysis.earnings のテスト。

承認済みのサンプルデータ手計算（2026-08-21合意分、ケースC/D/E）をテストケース化する。
"""

from datetime import date, timedelta

from analysis.earnings import compute_earnings_score
from data_sources.base import DailyBar

BASE_DATE = date(2026, 1, 1)


def _build_bars(length: int, drift_at_index: dict) -> list[DailyBar]:
    """全営業日フラット(close=1000)のバー列を作り、drift_at_indexで指定した
    (発表インデックス -> 5日後リターン) の箇所だけ5日後の終値を変化させる。
    """
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


def test_case_c_recent_earnings_with_strong_history():
    # 過去4回(idx10,40,70,100)のドリフト実績: +4%,+3%,+5%,+2% → 平均+3.5%
    # 直近決算(idx130)から3営業日後(idx133)が「今日」
    hist = {10: 0.04, 40: 0.03, 70: 0.05, 100: 0.02}
    bars = _build_bars(length=134, drift_at_index=hist)
    earnings_dates = [BASE_DATE + timedelta(days=i) for i in (10, 40, 70, 100, 130)]

    result = compute_earnings_score(bars, earnings_dates)

    assert result is not None
    assert result.days_since_earnings == 3
    assert result.in_reaction_window is True
    assert round(result.post_earnings_drift_avg, 4) == round((0.04 + 0.03 + 0.05 + 0.02) / 4, 4)
    assert result.earnings_score == 2


def test_case_d_outside_reaction_window():
    hist = {10: 0.04, 40: 0.03, 70: 0.05, 100: 0.02}
    # 直近決算(idx130)から10営業日後(idx140)が「今日」→反応期間(3営業日)を超過
    bars = _build_bars(length=141, drift_at_index=hist)
    earnings_dates = [BASE_DATE + timedelta(days=i) for i in (10, 40, 70, 100, 130)]

    result = compute_earnings_score(bars, earnings_dates)

    assert result is not None
    assert result.days_since_earnings == 10
    assert result.in_reaction_window is False
    assert result.post_earnings_drift_avg is None
    assert result.earnings_score == 0


def test_case_e_insufficient_history():
    # 過去の決算発表が2回(idx10,40)しかない(4回未満) → データ不足で0点
    hist = {10: 0.04, 40: 0.03}
    # 直近決算(idx70)から1営業日後(idx71)が「今日」
    bars = _build_bars(length=72, drift_at_index=hist)
    earnings_dates = [BASE_DATE + timedelta(days=i) for i in (10, 40, 70)]

    result = compute_earnings_score(bars, earnings_dates)

    assert result is not None
    assert result.days_since_earnings == 1
    assert result.in_reaction_window is True
    assert result.post_earnings_drift_avg is None
    assert result.earnings_score == 0


def test_no_earnings_data_returns_none():
    bars = _build_bars(length=30, drift_at_index={})

    result = compute_earnings_score(bars, earnings_dates=[])

    assert result is None
