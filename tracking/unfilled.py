"""不成立（指値が約定しなかった）予測の履歴と、その理由文の組み立て。

承認済み（2026-11-05）。約定条件は predictions_db と同じ:
    買い: 対象日の安値 <= 指値 で約定 / 売り: 対象日の高値 >= 指値 で約定
不成立の理由は、対象日の値動きが指値に届かなかった差（円・指値比%）で示す。
"""

import sqlite3
from dataclasses import dataclass
from datetime import date

from analysis.scoring import Side


@dataclass(frozen=True)
class UnfilledPrediction:
    prediction_date: date
    target_date: date
    code: str
    name: str
    side: Side
    entry_price: float
    target_low: float
    target_high: float
    target_close: float

    @property
    def reason(self) -> str:
        return build_unfilled_reason(
            self.side, self.entry_price, self.target_low, self.target_high
        )


def build_unfilled_reason(side: Side, entry_price: float, target_low: float, target_high: float) -> str:
    if side == "sell":
        gap = entry_price - target_high
        extreme = f"対象日の高値{target_high:,.1f}円が参考指値{entry_price:,.1f}円まで上がらず"
    else:
        gap = target_low - entry_price
        extreme = f"対象日の安値{target_low:,.1f}円が参考指値{entry_price:,.1f}円まで下がらず"
    pct = gap / entry_price * 100
    return f"{extreme}（差{gap:,.1f}円・{pct:.2f}%）"


def get_unfilled_predictions(db_path: str, side: Side) -> list[UnfilledPrediction]:
    """答え合わせ済みで約定しなかった予測を、予測日の新しい順（同日は登録順）で返す。"""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT prediction_date, target_date, code, name, side, entry_price, "
            "target_low, target_high, target_close FROM predictions "
            "WHERE evaluated = 1 AND filled = 0 AND side = ? "
            "ORDER BY prediction_date DESC, id ASC",
            (side,),
        ).fetchall()
    finally:
        conn.close()
    return [
        UnfilledPrediction(
            prediction_date=date.fromisoformat(r[0]),
            target_date=date.fromisoformat(r[1]),
            code=r[2],
            name=r[3],
            side=r[4],
            entry_price=r[5],
            target_low=r[6],
            target_high=r[7],
            target_close=r[8],
        )
        for r in rows
    ]
