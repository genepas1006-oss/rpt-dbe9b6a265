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
from tracking.payoff import excursions
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
    target_high: float | None = None
    target_low: float | None = None

    @property
    def fill_price(self) -> float | None:
        """実際の約定価格。寄りが指値より有利なら寄り値（買いは安い方、売りは高い方）。不成立・未確定はNone。"""
        if self.status not in ("win", "loss"):
            return None
        if not self.target_open:
            return self.entry_price
        return max(self.entry_price, self.target_open) if self.side == "sell" else min(self.entry_price, self.target_open)

    def explain_lines(self) -> list[str]:
        """結果を ①約定 ②損益 ③補足 の3行で説明する（承認済み 2026-11-11）。未確定は空。"""
        if self.status == "pending":
            return []
        sell = self.side == "sell"
        verb = "売り" if sell else "買い"
        edge, edge_label = (self.target_high, "高値") if sell else (self.target_low, "安値")
        reach = "上がって" if sell else "下がって"
        if self.status == "unfilled":
            if edge is None:
                return []
            return [f"約定: {edge_label}{edge:,.1f}円が指値{self.entry_price:,.1f}円まで届かず、{verb}は不成立（損益なし）"]
        fp = self.fill_price
        if fp is None:
            return []
        if abs(fp - self.entry_price) > 1e-9 and self.target_open:
            fill_text = (
                f"始値{self.target_open:,.1f}円が指値{self.entry_price:,.1f}円より{'高い' if sell else '安い'}ため、"
                f"始値{fp:,.1f}円で{verb}が成立（有利）"
            )
        elif edge is not None:
            fill_text = f"{edge_label}{edge:,.1f}円が指値{self.entry_price:,.1f}円まで{reach}、{fp:,.1f}円で{verb}が成立"
        else:
            fill_text = f"{fp:,.1f}円で{verb}が成立"
        lines = [f"約定: {fill_text}"]
        if self.target_close is not None and self.result_return is not None:
            diff = self.target_close - fp
            move = "変わらず" if diff == 0 else f"{abs(diff):,.1f}円{'上がった' if diff > 0 else '下がった'}"
            outcome = "利益" if self.result_return > 0 else "損失" if self.result_return < 0 else "損益なし"
            lines.append(
                f"損益: {fp:,.1f}円で{verb} → 終値{self.target_close:,.1f}円。1株あたり{move}ので"
                f"{self.result_return * 100:+.2f}%の{outcome}"
            )
        extras = []
        if self.target_high is not None and self.target_low is not None:
            mfe, mae = excursions(self.side, fp, self.target_high, self.target_low)
            extras.append(
                f"日中の最大含み益+{mfe * 100:.2f}%・最大含み損-{mae * 100:.2f}%"
                "（日足の高値・安値から。どちらが先かは分かりません）"
            )
        if self.note:
            extras.append("予測日の終値から見ると予想と逆に動いており、方向の的中率では外れ扱いです")
        if extras:
            lines.append("補足: " + "。".join(extras))
        return lines

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
            "target_open, target_close, oc_return, pred_close, target_high, target_low FROM predictions "
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
            target_high=r[12],
            target_low=r[13],
        )
        for i, r in enumerate(rows, start=1)
    ]
    return PreviousResults(
        prediction_date=date.fromisoformat(last),
        target_date=date.fromisoformat(max(r[0] for r in rows)),
        items=items,
    )
