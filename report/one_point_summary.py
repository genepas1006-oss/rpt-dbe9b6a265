"""当日の値動き（寄り・引け・出来高）からワンポイント要約文を組み立てる。

既存の承認済みしきい値（analysis.technical の出来高倍率・引け位置の基準）を
そのまま再利用したテンプレート文で、新たな数値判定ロジックは追加しない。
LLM等の外部API呼び出しは行わない（無料・即時表示）。
"""

from analysis.fundamental_comment import build_fundamental_outlook, build_fundamental_sentence, earnings_notice
from data_sources.base import Fundamentals


def build_one_point_summary(
    day_open: float, day_high: float, day_low: float, day_close: float, volume_ratio: float
) -> str:
    parts = []

    if day_close > day_open:
        parts.append("寄り付きから上昇して")
    elif day_close < day_open:
        parts.append("寄り付きから下落して")
    else:
        parts.append("寄り付き水準からほぼ横ばいで")

    if volume_ratio >= 2.0:
        parts.append("出来高が急増し")
    elif volume_ratio >= 1.5:
        parts.append("出来高がやや増加し")

    if day_high == day_low:
        close_position = 0.5
    else:
        close_position = (day_close - day_low) / (day_high - day_low)

    if close_position >= 0.8:
        parts.append("高値圏で引けた")
    elif close_position <= 0.2:
        parts.append("安値圏で引けた")
    else:
        parts.append("中間圏で引けた")

    return "、".join(parts) + "。"


def build_outlook(
    side: str, day_high: float, day_low: float, day_close: float, volume_ratio: float
) -> str:
    """今日の引け位置・出来高から、翌日の見通しを1文で組み立てる。

    承認済み（2026-10-28）。断定表現は使わず「可能性」「注視」の範囲に留める。
    side="buy"は上昇継続、side="sell"は下落継続の可能性を軸に書く。
    """
    if day_high == day_low:
        close_position = 0.5
    else:
        close_position = (day_close - day_low) / (day_high - day_low)

    high_volume = volume_ratio >= 1.5

    if side == "sell":
        if close_position <= 0.2:
            if high_volume:
                return "戻り売りに押される形で、翌日も続落する可能性がある。ただし急反発（リバウンド）にも注意。"
            return "出来高を伴わない下落のため、続落には出来高の増加が条件。"
        if close_position >= 0.8:
            return "高値圏で引けており、売り方向とは逆行している。翌日の反落の有無を見極めたい。"
        return "方向感は定まっておらず、寄り付きの強弱を見極めたい。"

    if close_position >= 0.8:
        if high_volume:
            return "買いの勢いが翌日に持ち越され、続伸する可能性がある。ただし利益確定売りで寄り付き後に押す場面にも注意。"
        return "出来高を伴わない上昇のため、続伸には出来高の増加が条件。"
    if close_position <= 0.2:
        return "売りに押された形で、翌日は戻りが鈍い可能性がある。"
    return "方向感は定まっておらず、寄り付きの強弱を見極めたい。"


def _position_label(day_high: float, day_low: float, day_close: float) -> str:
    pos = 0.5 if day_high == day_low else (day_close - day_low) / (day_high - day_low)
    return "高値圏" if pos >= 0.8 else "安値圏" if pos <= 0.2 else "中間圏"


def build_one_point_with_fundamentals(
    day_high: float,
    day_low: float,
    day_close: float,
    volume_ratio: float,
    daily_return: float | None,
    fundamentals: Fundamentals | None,
    fallback: str,
) -> str:
    """値動き（数字付き）とファンダメンタルの要点。ファンダメンタルを書けなければ従来の文（fallback）を返す。"""
    sentence = build_fundamental_sentence(fundamentals, day_close) if fundamentals else None
    if sentence is None:
        return fallback
    day = f"当日{daily_return * 100:+.2f}%、" if daily_return is not None and daily_return == daily_return else ""
    move = f"{day}出来高は20日平均の{volume_ratio:.2f}倍、{_position_label(day_high, day_low, day_close)}で引けた。"
    return move + sentence


def build_outlook_with_fundamentals(
    side: str,
    day_high: float,
    day_low: float,
    day_close: float,
    volume_ratio: float,
    fundamentals: Fundamentals | None,
    earnings_days: int | None,
) -> str:
    """ファンダメンタル面の整合・逆行 + 従来の値動きの見通し + 決算が近い場合の注意。"""
    tech = build_outlook(side, day_high, day_low, day_close, volume_ratio)
    fund = build_fundamental_outlook(fundamentals, day_close, side) if fundamentals else None
    notice = earnings_notice(earnings_days)
    if fund is None and not notice:
        return tech
    return (fund or "") + tech + (notice and " " + notice)
