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
from analysis.miss_analysis import classify_miss
from config import ENTRY_DISCOUNT
from tracking.trade_eval import base_price_of, evaluate_trade, is_direction_hit

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
    created_at TEXT NOT NULL,
    pred_close REAL,
    pred_daily_return REAL,
    pred_volume_ratio REAL,
    target_open REAL,
    market_return REAL,
    miss_causes TEXT,
    oc_return REAL,
    fill_price REAL,
    data_anomaly INTEGER NOT NULL DEFAULT 0
);
"""

# 2026-11-09: 不的中の原因分析用に追加した列（既存DBは init_db で追加する）
EXTRA_COLUMNS = {
    "pred_close": "REAL",
    "pred_daily_return": "REAL",
    "pred_volume_ratio": "REAL",
    "target_open": "REAL",
    "market_return": "REAL",
    "miss_causes": "TEXT",
    "oc_return": "REAL",  # 2026-11-09: 成行（寄り→引け）のリターン（参考）
    "fill_price": "REAL",  # 2026-11-09: 寄り値補正後の約定価格（NULLは補正前の評価）
    "data_anomaly": "INTEGER NOT NULL DEFAULT 0",  # 2026-11-10: 株式分割などの疑いで成績から除外する行
    "fundamental_json": "TEXT",  # 2026-11-10: 予測時のファンダメンタルの材料（外れた予想の分析用）
    "earnings_days": "INTEGER",  # 2026-11-10: 予測時点での次回決算までの日数
    "variant": "TEXT NOT NULL DEFAULT 'main'",  # 2026-11-10: 'main'=本番 / 'volatile'=テスト枠（値動き重視）
}

MAIN = "main"
VOLATILE = "volatile"

MISS_REVIEWS_SCHEMA = """
CREATE TABLE IF NOT EXISTS miss_reviews (
    prediction_id INTEGER PRIMARY KEY,
    primary_cause TEXT NOT NULL,
    secondary_causes TEXT NOT NULL,
    metrics TEXT NOT NULL,
    review_text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

# 承認済み（2026-11-10）: 予測日終値に対する対象日終値の比 r が、r < 0.65 または r > 1.5 なら
# 株式分割などによるデータ異常の疑いとして成績・仮想資金・全銘柄平均との比較から除外する。
ANOMALY_LOW = 0.65
ANOMALY_HIGH = 1.5


def is_data_anomaly(pred_close: float | None, target_close: float | None) -> bool:
    if not pred_close or pred_close <= 0 or target_close is None:
        return False
    ratio = target_close / pred_close
    return ratio < ANOMALY_LOW or ratio > ANOMALY_HIGH


def init_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(SCHEMA)
        conn.execute(MISS_REVIEWS_SCHEMA)
        existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(predictions)")}
        if "side" not in existing_columns:
            conn.execute("ALTER TABLE predictions ADD COLUMN side TEXT NOT NULL DEFAULT 'buy'")
        for column, column_type in EXTRA_COLUMNS.items():
            if column not in existing_columns:
                conn.execute(f"ALTER TABLE predictions ADD COLUMN {column} {column_type}")
        conn.commit()
    finally:
        conn.close()


def save_predictions(
    db_path: str,
    prediction_date: date,
    target_date: date,
    candidates: list[RankedCandidate],
    extras: dict[str, tuple[str | None, int | None]] | None = None,
    variant: str = MAIN,
) -> None:
    """variant: 'main'（本番）/ 'volatile'（テスト枠）。extras: 銘柄コード → (予測時のファンダメンタル材料のJSON, 次回決算までの日数)。外れた予想の分析用に記録する。"""
    extras = extras or {}
    conn = sqlite3.connect(db_path)
    try:
        now = datetime.now().isoformat()
        conn.executemany(
            """
            INSERT INTO predictions (
                prediction_date, code, name, side, total_score, technical_score,
                earnings_score, entry_price, reasons, target_date,
                evaluated, created_at, pred_close, pred_daily_return, pred_volume_ratio,
                fundamental_json, earnings_days, variant
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)
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
                    c.day_close or None,
                    c.daily_return,
                    c.volume_ratio,
                    extras.get(c.code, (None, None))[0],
                    extras.get(c.code, (None, None))[1],
                    variant,
                )
                for c in candidates
            ],
        )
        conn.commit()
    finally:
        conn.close()


def replace_predictions(
    db_path: str,
    prediction_date: date,
    target_date: date,
    side: Side,
    candidates: list[RankedCandidate],
    extras: dict[str, tuple[str | None, int | None]] | None = None,
    variant: str = MAIN,
) -> None:
    """同じ予測日・同じside（・同じ区分）の予測を最新の1セットに置き換える（再実行しても二重登録しない）。

    承認済み（2026-11-06）:
        - その予測日・sideに答え合わせ済みの予測があれば、何も変更しない。
        - なければ未評価の予測を削除してから登録する（candidatesが空なら削除のみ）。
    """
    conn = sqlite3.connect(db_path)
    try:
        evaluated = conn.execute(
            "SELECT COUNT(*) FROM predictions "
            "WHERE prediction_date = ? AND side = ? AND variant = ? AND evaluated = 1",
            (prediction_date.isoformat(), side, variant),
        ).fetchone()[0]
        if evaluated > 0:
            return
        conn.execute(
            "DELETE FROM predictions WHERE prediction_date = ? AND side = ? AND variant = ? AND evaluated = 0",
            (prediction_date.isoformat(), side, variant),
        )
        conn.commit()
    finally:
        conn.close()
    if candidates:
        save_predictions(db_path, prediction_date, target_date, candidates, extras, variant)


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
    actual_date: date | None = None,
    target_open: float | None = None,
    market_return: float | None = None,
) -> None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT entry_price, side, pred_close, pred_daily_return, pred_volume_ratio "
            "FROM predictions WHERE id = ?",
            (prediction_id,),
        ).fetchone()
        entry_price, side, pred_close, pred_daily_return, pred_volume_ratio = row

        result = evaluate_trade(side, entry_price, target_low, target_high, target_close, target_open)
        filled, result_return, is_win = result.filled, result.result_return, result.is_win

        # 約定したが的中しなかった予測にだけ原因タグを付ける（予測時の値が記録されている行のみ）
        miss_causes = None
        if filled and is_win is False and pred_close is not None:
            miss_causes = json.dumps(
                classify_miss(
                    side,
                    pred_close,
                    pred_daily_return or 0.0,
                    pred_volume_ratio or 0.0,
                    target_open,
                    market_return,
                ),
                ensure_ascii=False,
            )

        # 成行（翌営業日の始値で入り、同日の終値で決済）の参考リターン。必ず約定する前提
        oc_return = None
        if target_open is not None and target_open > 0:
            oc_return = (
                (target_open - target_close) / target_open
                if side == "sell"
                else (target_close - target_open) / target_open
            )

        anomaly = int(is_data_anomaly(pred_close or entry_price, target_close))  # 予測日終値が未記録なら指値で代用
        conn.execute(
            """
            UPDATE predictions
            SET evaluated = 1, filled = ?, target_low = ?, target_high = ?,
                target_close = ?, result_return = ?, is_win = ?,
                target_date = COALESCE(?, target_date),
                target_open = ?, market_return = ?, miss_causes = ?, oc_return = ?,
                fill_price = ?, data_anomaly = ?
            WHERE id = ?
            """,
            (
                int(filled),
                target_low,
                target_high,
                target_close,
                result_return,
                None if is_win is None else int(is_win),
                None if actual_date is None else actual_date.isoformat(),
                target_open,
                market_return,
                miss_causes,
                oc_return,
                result.fill_price,
                anomaly,
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
    excluded_count: int = 0  # データ異常（株式分割の疑い）で除外した件数
    direction_total: int = 0  # 方向の的中率の分母（答え合わせ済みの全予測。データ異常は除く）
    direction_hits: int = 0  # 予測日の終値から見て、予想した向きに動いた件数


def get_win_rate_stats(db_path: str, side: Side | None = None, variant: str = MAIN) -> WinRateStats:
    """side指定時はその方向のみ、省略時は買い売り合算で集計する。"""
    conn = sqlite3.connect(db_path)
    try:
        where = "WHERE evaluated = 1 AND data_anomaly = 0 AND variant = ?" + (" AND side = ?" if side else "")
        params = (variant, side) if side else (variant,)
        total = conn.execute(
            f"SELECT COUNT(*) FROM predictions {where}", params
        ).fetchone()[0]
        filled = conn.execute(
            f"SELECT COUNT(*) FROM predictions {where} AND filled = 1", params
        ).fetchone()[0]
        wins = conn.execute(
            f"SELECT COUNT(*) FROM predictions {where} AND is_win = 1", params
        ).fetchone()[0]
        excluded = conn.execute(
            "SELECT COUNT(*) FROM predictions WHERE evaluated = 1 AND data_anomaly = 1 AND variant = ?"
            + (" AND side = ?" if side else ""),
            params,
        ).fetchone()[0]
    finally:
        conn.close()

    win_rate = wins / filled if filled > 0 else None
    dir_conn = sqlite3.connect(db_path)
    try:
        dir_rows = dir_conn.execute(
            "SELECT side, pred_close, entry_price, target_close FROM predictions "
            "WHERE evaluated = 1 AND data_anomaly = 0 AND variant = ? AND target_close IS NOT NULL"
            + (" AND side = ?" if side else ""),
            params,
        ).fetchall()
    finally:
        dir_conn.close()
    direction_hits = sum(
        is_direction_hit(s, base_price_of(s, pc, ep, ENTRY_DISCOUNT), tc) for s, pc, ep, tc in dir_rows
    )
    return WinRateStats(
        total_predictions=total,
        filled_count=filled,
        win_count=wins,
        win_rate=win_rate,
        excluded_count=excluded,
        direction_total=len(dir_rows),
        direction_hits=direction_hits,
    )


@dataclass(frozen=True)
class MarketOrderStats:
    """成行（寄り→引け）で入った場合の参考成績（始値が記録された予測のみ）。"""

    count: int
    wins: int
    win_rate: float | None
    avg_return: float | None
    limit_avg_return: float | None  # 同じ予測のうち、指値が約定した分の平均リターン


def get_market_order_stats(db_path: str, side: Side, variant: str = MAIN) -> MarketOrderStats:
    """成行は必ず約定する前提のため、指値が不成立だった予測も件数に含める。的中はリターン>0。"""
    conn = sqlite3.connect(db_path)
    try:
        count, wins, avg = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(oc_return > 0), 0), AVG(oc_return) FROM predictions "
            "WHERE evaluated = 1 AND data_anomaly = 0 AND variant = ? AND oc_return IS NOT NULL AND side = ?",
            (variant, side),
        ).fetchone()
        limit_avg = conn.execute(
            "SELECT AVG(result_return) FROM predictions "
            "WHERE evaluated = 1 AND data_anomaly = 0 AND variant = ? AND filled = 1 AND oc_return IS NOT NULL AND side = ?",
            (variant, side),
        ).fetchone()[0]
    finally:
        conn.close()
    return MarketOrderStats(
        count=count,
        wins=wins,
        win_rate=wins / count if count else None,
        avg_return=avg,
        limit_avg_return=limit_avg,
    )
