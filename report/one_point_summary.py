"""当日の値動き（寄り・引け・出来高）からワンポイント要約文を組み立てる。

既存の承認済みしきい値（analysis.technical の出来高倍率・引け位置の基準）を
そのまま再利用したテンプレート文で、新たな数値判定ロジックは追加しない。
LLM等の外部API呼び出しは行わない（無料・即時表示）。
"""


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
