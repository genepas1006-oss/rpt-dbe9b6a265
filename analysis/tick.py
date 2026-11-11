"""呼値（注文できる価格の刻み）に合わせた指値の計算。

承認済み（2026-11-11）:
    指値 = 終値 × (1 ∓ ENTRY_DISCOUNT)（買いは−、売りは+）を、その価格帯の呼値に丸める。
    丸めは最も近い刻みへ。ちょうど中間のときは切り上げ。価格帯の上限は「以下」を含む。
    TOPIX500構成銘柄は TICK_BANDS_TOPIX500、NON_TOPIX500_CODES の銘柄は TICK_BANDS_OTHER の表を使う。
    計算は誤差が出ないよう Decimal で行う。
"""

import math
from decimal import ROUND_FLOOR, Decimal

from typing import Literal

from config import ENTRY_DISCOUNT, NON_TOPIX500_CODES, TICK_BANDS_OTHER, TICK_BANDS_TOPIX500

Side = Literal["buy", "sell"]


def tick_size(price: float | Decimal, code: str | None = None) -> Decimal:
    bands = TICK_BANDS_OTHER if code in NON_TOPIX500_CODES else TICK_BANDS_TOPIX500
    p = Decimal(str(price))
    for upper, tick in bands:
        if math.isinf(upper) or p <= Decimal(upper):
            return Decimal(tick)
    return Decimal(bands[-1][1])


def round_to_tick(price: float | Decimal, code: str | None = None) -> float:
    p = Decimal(str(price))
    tick = tick_size(p, code)
    return float(((p / tick + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR)) * tick)


def limit_price(close: float, side: Side, code: str | None = None, discount: float = ENTRY_DISCOUNT) -> float:
    """参考指値（呼値に丸め済み）。"""
    d = Decimal(str(discount))
    mult = (Decimal(1) - d) if side == "buy" else (Decimal(1) + d)
    return round_to_tick(Decimal(str(close)) * mult, code)
