"""手数料込みリターンと、利確・損切りの試算。

承認済み設計（2026-11-11）:
    手数料込みリターン = 手数料前リターン - 往復コスト率（不成立 None はそのまま None）。
    利確・損切り（約定価格 F、利確幅 t、損切り幅 s）:
        買い: 利確価格 F*(1+t) / 損切り価格 F*(1-s)
        売り: 利確価格 F*(1-t) / 損切り価格 F*(1+s)
        高値・安値が価格に「ちょうど届いた」場合も到達とみなす。
        利確のみ到達 → +t / 損切りのみ到達 → -s / どちらも未到達 → 終値で決済。
        日足では順序が分からないため、両方に到達した日は損切りが先だったものとして -s（判定不能として別集計）。
    日足の値からの試算であり、日中の値動きの順序は反映できない。
"""

import sqlite3
from dataclasses import dataclass
from typing import Literal

from analysis.scoring import Side
from config import COST_RATE, EXIT_RULES
from tracking.trade_eval import evaluate_trade

Outcome = Literal["tp", "sl", "close", "ambiguous"]
_EPS = 1e-9  # 浮動小数点の誤差で「ちょうど届いた」を取りこぼさないための許容


@dataclass(frozen=True)
class ExitResult:
    result_return: float
    outcome: Outcome


@dataclass(frozen=True)
class ExitStats:
    take_profit: float
    stop_loss: float
    count: int
    wins: int
    avg_return: float | None
    tp_count: int
    sl_count: int
    close_count: int
    ambiguous_count: int

    @property
    def win_rate(self) -> float | None:
        return self.wins / self.count if self.count else None


def apply_cost(result_return: float | None, cost_rate: float = COST_RATE) -> float | None:
    """手数料前リターンから往復コスト率を引く。不成立（None）はそのまま。"""
    return None if result_return is None else result_return - cost_rate


def simulate_exit(
    side: Side,
    fill_price: float,
    high: float,
    low: float,
    close: float,
    take_profit: float,
    stop_loss: float,
) -> ExitResult:
    if side == "sell":
        tp_hit = low <= fill_price * (1 - take_profit) * (1 + _EPS)
        sl_hit = high >= fill_price * (1 + stop_loss) * (1 - _EPS)
        close_return = (fill_price - close) / fill_price
    else:
        tp_hit = high >= fill_price * (1 + take_profit) * (1 - _EPS)
        sl_hit = low <= fill_price * (1 - stop_loss) * (1 + _EPS)
        close_return = (close - fill_price) / fill_price
    if tp_hit and sl_hit:
        return ExitResult(-stop_loss, "ambiguous")
    if tp_hit:
        return ExitResult(take_profit, "tp")
    if sl_hit:
        return ExitResult(-stop_loss, "sl")
    return ExitResult(close_return, "close")


def get_exit_stats(
    db_path: str,
    side: Side,
    variant: str = "main",
    rules: list[tuple[float, float]] | None = None,
    cost_rate: float = COST_RATE,
) -> list[ExitStats]:
    """約定済みの予測（データ異常を除く）に、利確・損切りの各組み合わせを当てはめた試算。"""
    rules = EXIT_RULES if rules is None else rules
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT entry_price, target_open, target_high, target_low, target_close FROM predictions "
            "WHERE evaluated = 1 AND filled = 1 AND data_anomaly = 0 AND variant = ? AND side = ? "
            "AND target_high IS NOT NULL AND target_low IS NOT NULL AND target_close IS NOT NULL",
            (variant, side),
        ).fetchall()
    finally:
        conn.close()
    fills = []
    for entry, open_, high, low, close in rows:
        trade = evaluate_trade(side, entry, low, high, close, open_)
        if trade.filled and trade.fill_price:
            fills.append((trade.fill_price, high, low, close))

    stats = []
    for tp, sl in rules:
        results = [simulate_exit(side, f, h, lo, c, tp, sl) for f, h, lo, c in fills]
        nets = [apply_cost(r.result_return, cost_rate) for r in results]
        stats.append(
            ExitStats(
                take_profit=tp,
                stop_loss=sl,
                count=len(results),
                wins=sum(n > 0 for n in nets),
                avg_return=sum(nets) / len(nets) if nets else None,
                tp_count=sum(r.outcome == "tp" for r in results),
                sl_count=sum(r.outcome == "sl" for r in results),
                close_count=sum(r.outcome == "close" for r in results),
                ambiguous_count=sum(r.outcome == "ambiguous" for r in results),
            )
        )
    return stats
