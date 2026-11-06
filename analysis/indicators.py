"""価格系列から計算するテクニカル指標（地合い・過熱度）。

承認済み設計（2026-11-06）:
    - 25日移動平均からの乖離率 = (当日終値 - 直近25日終値の単純平均) ÷ その平均
    - RSI(14日, 単純平均版) = 100 - 100 / (1 + 平均上昇幅 ÷ 平均下落幅)
        平均は直近14日の前日比（15本の終値から14個）の単純平均。
        下落が0なら100、上昇も下落も0なら50。
    - 地合い = 指数の終値が25日移動平均以上なら +1、未満なら -1

いずれも、必要な本数が揃わない場合は None（判定なし）を返す。
closes は日付昇順で、最後の要素が当日の終値。
"""

MA_PERIOD = 25
RSI_PERIOD = 14


def ma_deviation(closes: list[float], period: int = MA_PERIOD) -> float | None:
    if len(closes) < period:
        return None
    ma = sum(closes[-period:]) / period
    if ma <= 0:
        return None
    return (closes[-1] - ma) / ma


def rsi_simple(closes: list[float], period: int = RSI_PERIOD) -> float | None:
    if len(closes) < period + 1:
        return None
    window = closes[-(period + 1) :]
    gains = 0.0
    losses = 0.0
    for prev, cur in zip(window, window[1:]):
        diff = cur - prev
        if diff > 0:
            gains += diff
        else:
            losses += -diff
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_gain == 0 and avg_loss == 0:
        return 50.0
    if avg_loss == 0:
        return 100.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def market_bias(index_closes: list[float], period: int = MA_PERIOD) -> int | None:
    deviation = ma_deviation(index_closes, period)
    if deviation is None:
        return None
    return 1 if deviation >= 0 else -1
