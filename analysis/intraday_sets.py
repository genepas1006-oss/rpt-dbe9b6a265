"""寄り枠・昼の予想の選び方と判定。承認済み設計（2026-11-11）。試験運用で、効果は未確認。

寄り枠（平日9:25作成）: 寄り付きが前日終値比 -1.5%以下→買い / +1.5%以上→売り（境界を含む）。
    ギャップの大きい順に、買い・売り各最大5件（同値は銘柄コード順）。基準価格=寄り付きの始値。
昼の予想（平日11:50作成）: 前場（始値→11:30までの最後の足の終値）が -3%以下→買い / +3%以上→売り（境界を含む）。
    前場の動きの大きい順に、買い・売り各最大10件（超えた分は件数を記録）。基準価格=後場の始値（12:30の最初の価格）。
    過去検証で、5件に絞る並べ方（動きの大きい順・出来高・引け位置など）に一貫した優位性はなかったため、並べ方に優位性は主張しない。
的中: 基準価格→大引けで予想方向（買い=上昇、売り=下落）に動いたか。同値は外れ。約定の成否は問わない。
リターン: 買い (終値-基準)/基準 / 売り (基準-終値)/基準。
"""

from dataclasses import dataclass

OPEN_GAP_THRESHOLD = 0.015
OPEN_MAX_PER_SIDE = 5
AM_MOVE_THRESHOLD = 0.03
LUNCH_MAX_PER_SIDE = 10
EPS = 1e-9  # 境界ちょうどの値が、小数の誤差で外れないようにする


@dataclass(frozen=True)
class IntradayInput:
    code: str
    name: str
    base_close: float  # 寄り枠=前日終値 / 昼=前場の始値
    ref_price: float  # 寄り枠=寄り付きの始値 / 昼=前場終値（11:30までの最後の足の終値）


@dataclass(frozen=True)
class IntradayPick:
    code: str
    name: str
    side: str
    base_close: float
    ref_price: float
    move: float  # 寄り枠=ギャップ / 昼=前場の動き


def move_of(base_close: float, ref_price: float) -> float:
    return ref_price / base_close - 1


def _select(
    inputs: list[IntradayInput], threshold: float, max_per_side: int
) -> tuple[list[IntradayPick], list[IntradayPick], int, int]:
    buys: list[IntradayPick] = []
    sells: list[IntradayPick] = []
    for i in inputs:
        if i.base_close <= 0 or i.ref_price <= 0:
            continue
        m = move_of(i.base_close, i.ref_price)
        if m <= -threshold + EPS:
            buys.append(IntradayPick(i.code, i.name, "buy", i.base_close, i.ref_price, m))
        elif m >= threshold - EPS:
            sells.append(IntradayPick(i.code, i.name, "sell", i.base_close, i.ref_price, m))
    buys.sort(key=lambda p: (-abs(round(p.move, 12)), p.code))
    sells.sort(key=lambda p: (-abs(round(p.move, 12)), p.code))
    return buys[:max_per_side], sells[:max_per_side], max(0, len(buys) - max_per_side), max(0, len(sells) - max_per_side)


def select_open_gap(inputs: list[IntradayInput]) -> tuple[list[IntradayPick], list[IntradayPick], int, int]:
    """（買い, 売り, 買いの超過件数, 売りの超過件数）。ref_price=寄り付きの始値、base_close=前日終値。"""
    return _select(inputs, OPEN_GAP_THRESHOLD, OPEN_MAX_PER_SIDE)


def select_lunch(inputs: list[IntradayInput]) -> tuple[list[IntradayPick], list[IntradayPick], int, int]:
    """（買い, 売り, 買いの超過件数, 売りの超過件数）。ref_price=前場終値、base_close=前場の始値。"""
    return _select(inputs, AM_MOVE_THRESHOLD, LUNCH_MAX_PER_SIDE)


def direction_result(side: str, basis_price: float, close: float) -> tuple[float, bool]:
    """（リターン, 的中）。同値は外れ。"""
    ret = (close - basis_price) / basis_price if side == "buy" else (basis_price - close) / basis_price
    return ret, ret > 0
