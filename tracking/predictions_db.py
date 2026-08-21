"""予測記録・答え合わせ結果を保存するSQLiteストア。

承認済み設計（2026-08-21）:
    - 約定判定: 対象日の安値 <= 指値 なら「約定した」とみなす
    - 結果リターン: 約定時のみ (対象日終値 - 指値) / 指値 を算出
    - 的中判定: result_return > 0 なら的中
    - 勝率: 約定した予測のうち的中した割合（不成立は分母から除外）
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from analysis.scoring import RankedCandidate

SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_date TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
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
                prediction_date, code, name, total_score, technical_score,
                earnings_score, entry_price, reasons, target_date,
                evaluated, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            [
                (
                    prediction_date.isoformat(),
                    c.code,
                    c.name,
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
    entry_price: float
    target_date: date


def get_pending_predictions(db_path: str, as_of: date) -> list[PendingPrediction]:
    """target_date <= as_of かつ未評価の予測を取得する。"""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, code, entry_price, target_date FROM predictions "
            "WHERE evaluated = 0 AND target_date <= ?",
            (as_of.isoformat(),),
        ).fetchall()
    finally:
        conn.close()
    return [
        PendingPrediction(
            id=r[0], code=r[1], entry_price=r[2], target_date=date.fromisoformat(r[3])
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
            "SELECT entry_price FROM predictions WHERE id = ?", (prediction_id,)
        ).fetchone()
        entry_price = row[0]

        filled = target_low <= entry_price
        if filled:
            result_return = (target_close - entry_price) / entry_price
            is_win = result_return > 0
        else:
            result_return = None
            is_win = None

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


def get_win_rate_stats(db_path: str) -> WinRateStats:
    conn = sqlite3.connect(db_path)
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM predictions WHERE evaluated = 1"
        ).fetchone()[0]
        filled = conn.execute(
            "SELECT COUNT(*) FROM predictions WHERE evaluated = 1 AND filled = 1"
        ).fetchone()[0]
        wins = conn.execute(
            "SELECT COUNT(*) FROM predictions WHERE evaluated = 1 AND is_win = 1"
        ).fetchone()[0]
    finally:
        conn.close()

    win_rate = wins / filled if filled > 0 else None
    return WinRateStats(
        total_predictions=total, filled_count=filled, win_count=wins, win_rate=win_rate
    )
