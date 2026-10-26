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
