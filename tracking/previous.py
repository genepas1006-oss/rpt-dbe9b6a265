"""前営業日に出した予想の結果（的中・不的中・不成立・未確定）を、予想と一緒に確認するための取得。

承認済み（2026-11-09）:
    today より前で、その側（買い/売り）の予測が最後にある予測日を「前営業日」とする。
    各予測の状態: 未評価=未確定 / 約定なし=不成立 / 約定かつリターン>0=的中 / それ以外=不的中。
    順位は、その予測日・側の登録順（登録は順位順）。
"""

import sqlite3
from dataclasses import dataclass
from datetime import date

from analysis.scoring import Side
from config import ENTRY_DISCOUNT
from tracking.trade_eval import DIRECTION_NOTE, base_price_of, is_direction_hit

STATUS_LABEL = {"win": "的中", "loss": "不的中", "unfilled": "不成立", "pending": "未確定"}
STATUS_ORDER = ("win", "loss", "unfilled", "pending")


@dataclass(frozen=True)
class PreviousItem:
    rank: int
    code: str
    name: str
    entry_price: float
    status: str
    result_return: float | None
    target_open: float | None
    target_close: float | None
    oc_return: float | None
    side: Side = "buy"
    pred_close: float | None = None

    @property
    def note(self) -> str:
        """的中（利益）なのに、予測日の終値から見て予想と逆に動いていた場合の注記（寄りのギャップで有利に約定）。"""
        if self.status != "win" or self.target_close is None:
            return ""
        base = base_price_of(self.side, self.pred_close, self.entry_price, ENTRY_DISCOUNT)
        return "" if is_direction_hit(self.side, base, self.target_close) else DIRECTION_NOTE


@dataclass(frozen=True)
class PreviousResults:
    prediction_date: date
    target_date: date
    items: list[PreviousItem]

    def counts(self) -> dict[str, int]:
        return {s: sum(1 for i in self.items if i.status == s) for s in STATUS_ORDER}


def _status(evaluated: int, filled: int | None, is_win: int | None) -> str:
    if not evaluated:
        return "pending"
    if not filled:
        return "unfilled"
    return "win" if is_win else "loss"


def get_previous_results(db_path: str, side: Side, before: date) -> PreviousResults | None:
    conn = sqlite3.connect(db_path)
    try:
        last = conn.execute(
            "SELECT MAX(prediction_date) FROM predictions WHERE variant = 'main' AND side = ? AND prediction_date < ?",
            (side, before.isoformat()),
        ).fetchone()[0]
        if last is None:
            return None
        rows = conn.execute(
            "SELECT target_date, code, name, entry_price, evaluated, filled, is_win, result_return, "
            "target_open, target_close, oc_return, pred_close FROM predictions "
            "WHERE variant = 'main' AND side = ? AND prediction_date = ? ORDER BY id ASC",
            (side, last),
        ).fetchall()
    finally:
        conn.close()
    items = [
        PreviousItem(
            rank=i,
            code=r[1],
            name=r[2],
            entry_price=r[3],
            status=_status(r[4], r[5], r[6]),
            result_return=r[7],
            target_open=r[8],
            target_close=r[9],
            oc_return=r[10],
            side=side,
            pred_close=r[11],
        )
        for i, r in enumerate(rows, start=1)
    ]
    return PreviousResults(
        prediction_date=date.fromisoformat(last),
        target_date=date.fromisoformat(max(r[0] for r in rows)),
        items=items,
    )
