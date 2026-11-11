"""勝ちの平均利益・負けの平均損失・損益比、および日中の最大含み益・最大含み損。

承認済み（2026-11-11）:
    勝ち = 約定してリターン > 0。0以下（同値を含む）は負けに数える。
    平均利益 = 勝ちのリターンの平均 / 平均損失 = 負けの損失幅（正の値）の平均 / 損益比 = 平均利益 ÷ 平均損失。
    負けがない・平均損失が0なら損益比はNone、勝ちがなければ平均利益はNone・損益比は0。
    最大含み益・最大含み損は約定価格を基準にした日足の高値・安値からの値（高値と安値のどちらが先かは分からない）。
        買い: 含み益=(高値-約定)/約定 / 含み損=(約定-安値)/約定
        売り: 含み益=(約定-安値)/約定 / 含み損=(高値-約定)/約定
        マイナスになる場合は0にする。
"""

import sqlite3
from dataclasses import dataclass

from analysis.scoring import Side


@dataclass(frozen=True)
class PayoffStats:
    count: int
    wins: int
    losses: int
    win_rate: float
    avg_win: float | None
    avg_loss: float | None  # 損失幅（正の値）
    payoff_ratio: float | None
    avg_return: float


def compute_payoff(returns: list[float]) -> PayoffStats | None:
    if not returns:
        return None
    wins = [r for r in returns if r > 0]
    losses = [-r for r in returns if r <= 0]
    avg_win = sum(wins) / len(wins) if wins else None
    avg_loss = sum(losses) / len(losses) if losses else None
    if avg_loss is None or avg_loss == 0:
        ratio = None
    elif avg_win is None:
        ratio = 0.0
    else:
        ratio = avg_win / avg_loss
    return PayoffStats(
        count=len(returns),
        wins=len(wins),
        losses=len(losses),
        win_rate=len(wins) / len(returns),
        avg_win=avg_win,
        avg_loss=avg_loss,
        payoff_ratio=ratio,
        avg_return=sum(returns) / len(returns),
    )


def get_payoff_stats(db_path: str, side: Side, variant: str = "main") -> PayoffStats | None:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT result_return FROM predictions WHERE evaluated = 1 AND filled = 1 AND data_anomaly = 0 "
            "AND variant = ? AND side = ? AND result_return IS NOT NULL",
            (variant, side),
        ).fetchall()
    finally:
        conn.close()
    return compute_payoff([r[0] for r in rows])


def excursions(side: Side, fill_price: float, high: float, low: float) -> tuple[float, float]:
    """(最大含み益, 最大含み損)。どちらも0以上の割合。"""
    if side == "sell":
        mfe, mae = (fill_price - low) / fill_price, (high - fill_price) / fill_price
    else:
        mfe, mae = (high - fill_price) / fill_price, (fill_price - low) / fill_price
    return max(mfe, 0.0), max(mae, 0.0)
