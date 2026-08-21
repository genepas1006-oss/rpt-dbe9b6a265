"""値動き・出来高に基づくテクニカルスコアリング。

承認済み設計（2026-08-21）:
    - 出来高倍率 = 当日出来高 ÷ 直近20営業日（当日除く）平均出来高
        >=2.0倍: +2点 / >=1.5倍: +1点
    - 当日騰落率 = (当日終値 − 前日終値) ÷ 前日終値
        >=+3%: +2点 / >=+1%: +1点
    - 引け位置 = (当日終値 − 当日安値) ÷ (当日高値 − 当日安値)
        （高値=安値の日は0.5固定）
        >=0.8: +1点
    technical_score は上記3指標の加点合計（0〜5点）。
"""

from dataclasses import dataclass, field

from data_sources.base import DailyBar

LOOKBACK_DAYS = 20


@dataclass(frozen=True)
class TechnicalScore:
    volume_ratio: float
    daily_return: float
    close_position: float
    volume_points: int
    return_points: int
    close_position_points: int
    technical_score: int
    reasons: list[str] = field(default_factory=list)


def _volume_points(volume_ratio: float) -> int:
    if volume_ratio >= 2.0:
        return 2
    if volume_ratio >= 1.5:
        return 1
    return 0


def _return_points(daily_return: float) -> int:
    if daily_return >= 0.03:
        return 2
    if daily_return >= 0.01:
        return 1
    return 0


def _close_position_points(close_position: float) -> int:
    return 1 if close_position >= 0.8 else 0


def compute_technical_score(
    bars: list[DailyBar], lookback: int = LOOKBACK_DAYS
) -> TechnicalScore | None:
    """直近の日次バー列（日付昇順、最後の要素が当日）からテクニカルスコアを計算する。

    直近lookback営業日分の当日より前のデータが揃わない場合や、
    平均出来高・前日終値がゼロの場合はNoneを返す（呼び出し側で除外扱いとする）。
    """
    if len(bars) < lookback + 1:
        return None

    today = bars[-1]
    prior = bars[-(lookback + 1) : -1]
    prev_close = prior[-1].close

    avg_volume = sum(bar.volume for bar in prior) / lookback
    if avg_volume <= 0 or prev_close <= 0:
        return None

    volume_ratio = today.volume / avg_volume
    daily_return = (today.close - prev_close) / prev_close

    if today.high == today.low:
        close_position = 0.5
    else:
        close_position = (today.close - today.low) / (today.high - today.low)

    volume_points = _volume_points(volume_ratio)
    return_points = _return_points(daily_return)
    close_position_points = _close_position_points(close_position)

    reasons = []
    if volume_points > 0:
        reasons.append(f"出来高が{lookback}日平均の{volume_ratio:.2f}倍")
    if return_points > 0:
        reasons.append(f"当日{daily_return * 100:+.2f}%")
    if close_position_points > 0:
        reasons.append(f"高値圏({close_position:.2f})で引け")

    return TechnicalScore(
        volume_ratio=volume_ratio,
        daily_return=daily_return,
        close_position=close_position,
        volume_points=volume_points,
        return_points=return_points,
        close_position_points=close_position_points,
        technical_score=volume_points + return_points + close_position_points,
        reasons=reasons,
    )
