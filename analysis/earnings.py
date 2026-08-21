"""決算発表前後の過去パターンに基づくスコアリング。

承認済み設計（2026-08-21）:
    直近の決算発表から3営業日以内（反応期間中）の銘柄のみを評価対象とする。
    過去の決算発表（直近を除く、最大4回）それぞれについて、
    「発表日（以降最初の営業日）の終値」から「5営業日後の終値」までの
    リターン（決算後ドリフト）を計算し、その平均を post_earnings_drift_avg とする。
    過去実績が4回に満たない場合は判定不能として0点とする。

    - 反応期間内 かつ post_earnings_drift_avg >= +2%: +2点
    - 反応期間内 かつ post_earnings_drift_avg >= 0%: +1点
    - それ以外（反応期間外、または過去実績不足）: 0点
"""

from dataclasses import dataclass, field
from datetime import date

from data_sources.base import DailyBar

DRIFT_WINDOW_DAYS = 5
MIN_HISTORY = 4
REACTION_WINDOW_DAYS = 3


@dataclass(frozen=True)
class EarningsScore:
    days_since_earnings: int
    in_reaction_window: bool
    post_earnings_drift_avg: float | None
    earnings_score: int
    reasons: list[str] = field(default_factory=list)


def _first_index_on_or_after(bars: list[DailyBar], target: date) -> int | None:
    for i, bar in enumerate(bars):
        if bar.trade_date >= target:
            return i
    return None


def compute_earnings_score(
    bars: list[DailyBar],
    earnings_dates: list[date],
    drift_window: int = DRIFT_WINDOW_DAYS,
    min_history: int = MIN_HISTORY,
    reaction_window: int = REACTION_WINDOW_DAYS,
) -> EarningsScore | None:
    """日次バー列（日付昇順）と決算発表日一覧からearnings_scoreを計算する。

    決算発表日の実績が一切ない場合はNoneを返す（呼び出し側で「決算データなし」扱い）。
    """
    if not bars:
        return None

    bars_sorted = sorted(bars, key=lambda b: b.trade_date)
    today = bars_sorted[-1].trade_date

    past_earnings = sorted(d for d in earnings_dates if d <= today)
    if not past_earnings:
        return None

    most_recent = past_earnings[-1]
    day0_idx = _first_index_on_or_after(bars_sorted, most_recent)
    if day0_idx is None:
        return None

    days_since_earnings = (len(bars_sorted) - 1) - day0_idx
    in_reaction_window = days_since_earnings <= reaction_window

    if not in_reaction_window:
        return EarningsScore(
            days_since_earnings=days_since_earnings,
            in_reaction_window=False,
            post_earnings_drift_avg=None,
            earnings_score=0,
            reasons=[],
        )

    drift_returns = []
    for hist_date in reversed(past_earnings[:-1]):
        hist_day0_idx = _first_index_on_or_after(bars_sorted, hist_date)
        if hist_day0_idx is None:
            continue
        hist_dayN_idx = hist_day0_idx + drift_window
        if hist_dayN_idx >= len(bars_sorted):
            continue
        day0_close = bars_sorted[hist_day0_idx].close
        dayN_close = bars_sorted[hist_dayN_idx].close
        if day0_close <= 0:
            continue
        drift_returns.append((dayN_close - day0_close) / day0_close)
        if len(drift_returns) == min_history:
            break

    if len(drift_returns) < min_history:
        return EarningsScore(
            days_since_earnings=days_since_earnings,
            in_reaction_window=True,
            post_earnings_drift_avg=None,
            earnings_score=0,
            reasons=[],
        )

    drift_avg = sum(drift_returns) / len(drift_returns)

    if drift_avg >= 0.02:
        earnings_score = 2
    elif drift_avg >= 0.0:
        earnings_score = 1
    else:
        earnings_score = 0

    reasons = []
    if earnings_score > 0:
        reasons.append(
            f"決算発表{days_since_earnings}営業日後、過去{min_history}回の決算後"
            f"平均ドリフト{drift_avg * 100:+.1f}%"
        )

    return EarningsScore(
        days_since_earnings=days_since_earnings,
        in_reaction_window=True,
        post_earnings_drift_avg=drift_avg,
        earnings_score=earnings_score,
        reasons=reasons,
    )
