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
