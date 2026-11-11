"""同日の全銘柄平均との比較（スコアの効果の目安）。

承認済み設計（2026-11-09）:
    - 予測日の全銘柄に、本番と同じ指値（終値 ± ENTRY_DISCOUNT、呼値に丸め。2026-11-11〜）と
      同じ約定ルール（寄り値が有利なら寄り値で約定）を当てはめ、約定した銘柄のリターンを平均する。
      決済は各銘柄の「予測日の次の足」の終値。次の足がない銘柄・日は対象外。
    - スコアの効果 = 日ごとの（TOP5の約定分の平均 − 全銘柄平均）の平均。
      TOP5の約定が0件の日と、全銘柄平均の記録がない日は除く。
"""

import sqlite3
from dataclasses import dataclass
from datetime import date

from analysis.scoring import Side
from analysis.tick import limit_price
from config import ENTRY_DISCOUNT
from data_sources.base import DailyBar
from tracking.trade_eval import evaluate_trade

SCHEMA = """
CREATE TABLE IF NOT EXISTS benchmarks (
    prediction_date TEXT NOT NULL,
    side TEXT NOT NULL,
    avg_return REAL NOT NULL,
    filled_count INTEGER NOT NULL,
    universe_count INTEGER NOT NULL,
    PRIMARY KEY (prediction_date, side)
);
"""


@dataclass(frozen=True)
class UniverseReturn:
    avg_return: float
    filled_count: int
    universe_count: int


def compute_universe_return(
    side: Side,
    bars_by_code: dict[str, list[DailyBar]],
    prediction_date: date,
    entry_discount: float = ENTRY_DISCOUNT,
) -> UniverseReturn | None:
    returns: list[float] = []
    universe = 0
    for code, bars in bars_by_code.items():
        idx = next((i for i, b in enumerate(bars) if b.trade_date == prediction_date), None)
        if idx is None or idx + 1 >= len(bars):
            continue
        close = bars[idx].close
        nb = bars[idx + 1]
        if close <= 0:
            continue
        universe += 1
        entry = limit_price(close, side, code, entry_discount)
        result = evaluate_trade(side, entry, nb.low, nb.high, nb.close, nb.open)
        if result.filled and result.result_return is not None:
            returns.append(result.result_return)
    if universe == 0 or not returns:
        return None
    return UniverseReturn(sum(returns) / len(returns), len(returns), universe)


def init_benchmarks(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def compute_missing_benchmarks(db_path: str, bars_by_code: dict[str, list[DailyBar]]) -> int:
    """答え合わせ済みの予測日のうち、全銘柄平均が未記録の（日, 方向）を計算して保存する。件数を返す。"""
    init_benchmarks(db_path)
    conn = sqlite3.connect(db_path)
    try:
        todo = conn.execute(
            "SELECT DISTINCT p.prediction_date, p.side FROM predictions p "
            "LEFT JOIN benchmarks b ON b.prediction_date = p.prediction_date AND b.side = p.side "
            "WHERE p.evaluated = 1 AND b.prediction_date IS NULL"
        ).fetchall()
        saved = 0
        for pred_date, side in todo:
            ur = compute_universe_return(side, bars_by_code, date.fromisoformat(pred_date))
            if ur is None:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO benchmarks VALUES (?, ?, ?, ?, ?)",
                (pred_date, side, ur.avg_return, ur.filled_count, ur.universe_count),
            )
            saved += 1
        conn.commit()
        return saved
    finally:
        conn.close()


@dataclass(frozen=True)
class ScoreEffect:
    days: int
    top_avg: float
    bench_avg: float
    excess: float


def get_score_effect(db_path: str, side: Side, variant: str = "main") -> ScoreEffect | None:
    init_benchmarks(db_path)
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT p.prediction_date, AVG(p.result_return), b.avg_return FROM predictions p "
            "JOIN benchmarks b ON b.prediction_date = p.prediction_date AND b.side = p.side "
            "WHERE p.evaluated = 1 AND p.data_anomaly = 0 AND p.variant = ? AND p.filled = 1 AND p.result_return IS NOT NULL AND p.side = ? "
            "GROUP BY p.prediction_date",
            (variant, side),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return None
    n = len(rows)
    top = sum(r[1] for r in rows) / n
    bench = sum(r[2] for r in rows) / n
    return ScoreEffect(days=n, top_avg=top, bench_avg=bench, excess=sum(r[1] - r[2] for r in rows) / n)
