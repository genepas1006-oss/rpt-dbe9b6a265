"""予測記録・答え合わせ結果を保存するSQLiteストア。

承認済み設計（2026-08-21、買い）:
    - 約定判定: 対象日の安値 <= 指値 なら「約定した」とみなす
    - 結果リターン: 約定時のみ (対象日終値 - 指値) / 指値 を算出
    - 的中判定: result_return > 0 なら的中
    - 勝率: 約定した予測のうち的中した割合（不成立は分母から除外）

承認済み設計（2026-10-26、売り・ショート）:
    - 約定判定: 対象日の高値 >= 指値 なら「約定した」とみなす
    - 結果リターン: 約定時のみ (指値 - 対象日終値) / 指値 を算出
    - 的中判定は買いと同じ基準（result_return > 0）。
    - predictionsテーブルに side('buy'/'sell') を追加。既存行は全て'buy'扱い。
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from analysis.scoring import RankedCandidate, Side

SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_date TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    side TEXT NOT NULL DEFAULT 'buy',
    total_score INTEGER NOT NULL,
    technical_score INTEGER NOT NULL,
    earnings_score INTEGER NOT NULL,
    entry_price REAL NOT NULL,
    reasons TEXT NOT NULL,
    target_date TEXT NOT NULL,
    evaluated INTEGER NOT NULL DEFAULT 0,
    filled INTEGER,
    target_low REAL,
    target_high REAL,
    target_close REAL,
    result_return REAL,
    is_win INTEGER,
    created_at TEXT NOT NULL
);
"""


def init_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(SCHEMA)
        existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(predictions)")}
        if "side" not in existing_columns:
            conn.execute("ALTER TABLE predictions ADD COLUMN side TEXT NOT NULL DEFAULT 'buy'")
        conn.commit()
    finally:
        conn.close()


def save_predictions(
    db_path: str,
    prediction_date: date,
    target_date: date,
    candidates: list[RankedCandidate],
) -> None:
    conn = sqlite3.connect(db_path)
    try:
        now = datetime.now().isoformat()
        conn.executemany(
            """
            INSERT INTO predictions (
                prediction_date, code, name, side, total_score, technical_score,
                earnings_score, entry_price, reasons, target_date,
                evaluated, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            [
                (
                    prediction_date.isoformat(),
                    c.code,
                    c.name,
                    c.side,
                    c.total_score,
                    c.technical_score,
                    c.earnings_score,
                    c.entry_price,
                    json.dumps(c.reasons, ensure_ascii=False),
                    target_date.isoformat(),
                    now,
                )
                for c in candidates
            ],
        )
        conn.commit()
    finally:
        conn.close()


@dataclass(frozen=True)
class PendingPrediction:
    id: int
    code: str
    side: Side
    entry_price: float
    target_date: date


def get_pending_predictions(db_path: str, as_of: date) -> list[PendingPrediction]:
    """target_date <= as_of かつ未評価の予測を取得する。"""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, code, side, entry_price, target_date FROM predictions "
            "WHERE evaluated = 0 AND target_date <= ?",
            (as_of.isoformat(),),
        ).fetchall()
    finally:
        conn.close()
    return [
        PendingPrediction(
            id=r[0],
            code=r[1],
            side=r[2],
            entry_price=r[3],
            target_date=date.fromisoformat(r[4]),
        )
        for r in rows
    ]


def record_evaluation(
    db_path: str,
    prediction_id: int,
    target_low: float,
    target_high: float,
    target_close: float,
) -> None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT entry_price, side FROM predictions WHERE id = ?", (prediction_id,)
        ).fetchone()
        entry_price, side = row

        if side == "sell":
            filled = target_high >= entry_price
            result_return = (entry_price - target_close) / entry_price if filled else None
        else:
            filled = target_low <= entry_price
            result_return = (target_close - entry_price) / entry_price if filled else None
        is_win = result_return > 0 if filled else None

        conn.execute(
            """
            UPDATE predictions
            SET evaluated = 1, filled = ?, target_low = ?, target_high = ?,
                target_close = ?, result_return = ?, is_win = ?
            WHERE id = ?
            """,
            (
                int(filled),
                target_low,
                target_high,
                target_close,
                result_return,
                None if is_win is None else int(is_win),
                prediction_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


@dataclass(frozen=True)
class WinRateStats:
    total_predictions: int
    filled_count: int
    win_count: int
    win_rate: float | None  # filled_countが0の場合はNone


def get_win_rate_stats(db_path: str, side: Side | None = None) -> WinRateStats:
    """side指定時はその方向のみ、省略時は買い売り合算で集計する。"""
    conn = sqlite3.connect(db_path)
    try:
        where = "WHERE evaluated = 1" + (" AND side = ?" if side else "")
        params = (side,) if side else ()
        total = conn.execute(
            f"SELECT COUNT(*) FROM predictions {where}", params
        ).fetchone()[0]
        filled = conn.execute(
            f"SELECT COUNT(*) FROM predictions {where} AND filled = 1", params
        ).fetchone()[0]
        wins = conn.execute(
            f"SELECT COUNT(*) FROM predictions {where} AND is_win = 1", params
        ).fetchone()[0]
    finally:
        conn.close()

    win_rate = wins / filled if filled > 0 else None
    return WinRateStats(
        total_predictions=total, filled_count=filled, win_count=wins, win_rate=win_rate
    )
