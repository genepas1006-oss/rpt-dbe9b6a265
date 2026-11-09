"""不的中（約定したが的中しなかった）予測の履歴。原因タグ付き。

承認済み（2026-11-09）。原因タグは答え合わせ時に predictions.miss_causes（JSON）へ記録される。
原因の記録を始める前の予測（予測時の値が未記録の行）は、履歴に含めない。
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import date

from analysis.scoring import Side


@dataclass(frozen=True)
class MissedPrediction:
    prediction_date: date
    target_date: date
    code: str
    name: str
    side: Side
    entry_price: float
    target_close: float
    result_return: float
    causes: list[str]
    pred_close: float | None
    target_open: float | None
    market_return: float | None

    @property
    def detail(self) -> str:
        parts = [f"指値{self.entry_price:,.1f}円 → 終値{self.target_close:,.1f}円"]
        if self.market_return is not None:
            parts.append(f"日経平均{self.market_return * 100:+.2f}%")
        if self.target_open is not None and self.pred_close:
            gap = (self.target_open - self.pred_close) / self.pred_close
            parts.append(f"寄り付きは予測日終値比{gap * 100:+.2f}%")
        return "／".join(parts)


def get_missed_predictions(db_path: str, side: Side) -> list[MissedPrediction]:
    """原因タグが記録された不的中を、予測日の新しい順（同日は登録順）で返す。"""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT prediction_date, target_date, code, name, side, entry_price, target_close, "
            "result_return, miss_causes, pred_close, target_open, market_return FROM predictions "
            "WHERE evaluated = 1 AND filled = 1 AND is_win = 0 AND miss_causes IS NOT NULL "
            "AND side = ? ORDER BY prediction_date DESC, id ASC",
            (side,),
        ).fetchall()
    finally:
        conn.close()
    return [
        MissedPrediction(
            prediction_date=date.fromisoformat(r[0]),
            target_date=date.fromisoformat(r[1]),
            code=r[2],
            name=r[3],
            side=r[4],
            entry_price=r[5],
            target_close=r[6],
            result_return=r[7],
            causes=json.loads(r[8]),
            pred_close=r[9],
            target_open=r[10],
            market_return=r[11],
        )
        for r in rows
    ]
