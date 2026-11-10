"""1件の予測（指値）を翌営業日の値動きで答え合わせする共通ロジック。

predictions_db（本番の答え合わせ）と backtest（過去検証）で同じ判定を使う。

承認済み設計（2026-08-21 買い / 2026-10-26 売り）:
    買い: 対象日の安値 <= 指値 で約定。リターン = (終値 - 指値) / 指値
    売り: 対象日の高値 >= 指値 で約定。リターン = (指値 - 終値) / 指値
    的中 = 約定かつリターン > 0。不成立のリターン・的中は None。

承認済み設計（2026-11-09、約定価格の補正）:
    寄り付きが指値より有利な価格で始まった場合、指値注文は寄り値で約定する。
    買い: 約定価格 = min(指値, 寄り値) / 売り: 約定価格 = max(指値, 寄り値)。
    寄り値が分からない（None）場合は、従来どおり指値で約定したものとして扱う。
    約定条件（買いは安値<=指値、売りは高値>=指値）は変えない。
"""

from dataclasses import dataclass

from analysis.scoring import Side


@dataclass(frozen=True)
class TradeResult:
    filled: bool
    result_return: float | None
    is_win: bool | None
    fill_price: float | None = None


DIRECTION_NOTE = "ギャップで有利に約定"


def is_direction_hit(side: Side, base_price: float | None, target_close: float | None) -> bool:
    """予測日の終値から見て、予想した向きに動いたか（買いは上昇、売りは下落。同値は外れ）。約定・損益は問わない。

    承認済み（2026-11-10）。
    """
    if not base_price or base_price <= 0 or target_close is None:
        return False
    return target_close < base_price if side == "sell" else target_close > base_price


def base_price_of(side: Side, pred_close: float | None, entry_price: float, entry_discount: float) -> float:
    """予測日の終値。未記録の古い行は、指値から逆算して代用する（買い 指値÷(1-d) / 売り 指値÷(1+d)）。"""
    if pred_close:
        return pred_close
    return entry_price / ((1 + entry_discount) if side == "sell" else (1 - entry_discount))


def evaluate_trade(
    side: Side,
    entry_price: float,
    low: float,
    high: float,
    close: float,
    open_price: float | None = None,
) -> TradeResult:
    if side == "sell":
        filled = high >= entry_price
        fill_price = max(entry_price, open_price) if filled and open_price else entry_price
        result_return = (fill_price - close) / fill_price if filled else None
    else:
        filled = low <= entry_price
        fill_price = min(entry_price, open_price) if filled and open_price else entry_price
        result_return = (close - fill_price) / fill_price if filled else None
    is_win = result_return > 0 if filled else None
    return TradeResult(
        filled=filled,
        result_return=result_return,
        is_win=is_win,
        fill_price=fill_price if filled else None,
    )
