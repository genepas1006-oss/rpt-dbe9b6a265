"""外れた予想の検証メモ（miss_reviews）の作成・更新。

承認済み（2026-11-10）。約定したが的中しなかった予測（データ異常を除く）ごとに1件、答え合わせの後に作る。
結果の再計算で的中に変わった行や、データ異常になった行のメモは削除する（何度実行しても結果は同じ）。
"""

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime

from analysis.miss_review import review_miss


def update_miss_reviews(db_path: str) -> int:
    """検証メモを作り直す。新しく作った件数を返す。1件の失敗で全体を止めない。"""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "DELETE FROM miss_reviews WHERE prediction_id NOT IN ("
            "SELECT id FROM predictions WHERE evaluated = 1 AND variant = 'main' AND filled = 1 AND is_win = 0 AND data_anomaly = 0)"
        )
        rows = conn.execute(
            "SELECT p.id, p.side, p.entry_price, p.pred_close, p.pred_daily_return, p.pred_volume_ratio, "
            "p.target_open, p.target_high, p.target_low, p.target_close, p.market_return, p.fundamental_json, "
            "p.earnings_days FROM predictions p LEFT JOIN miss_reviews r ON r.prediction_id = p.id "
            "WHERE p.evaluated = 1 AND p.variant = 'main' AND p.filled = 1 AND p.is_win = 0 AND p.data_anomaly = 0 "
            "AND p.pred_close IS NOT NULL AND r.prediction_id IS NULL"
        ).fetchall()
        created = 0
        for (pid, side, entry, pred_close, pred_dr, pred_vr, t_open, t_high, t_low, t_close, market, fjson, edays) in rows:
            try:
                review = review_miss(
                    side, entry, pred_close, pred_dr or 0.0, pred_vr or 0.0, t_open, t_high, t_low, t_close, market,
                    json.loads(fjson) if fjson else None, edays,
                )
            except Exception:  # noqa: BLE001  1件の計算失敗で全体を止めない
                continue
            conn.execute(
                "INSERT INTO miss_reviews VALUES (?, ?, ?, ?, ?, ?)",
                (pid, review.primary, json.dumps(review.secondary, ensure_ascii=False),
                 json.dumps(asdict(review.metrics)), review.text, datetime.now().isoformat()),
            )
            created += 1
        conn.commit()
        return created
    finally:
        conn.close()
