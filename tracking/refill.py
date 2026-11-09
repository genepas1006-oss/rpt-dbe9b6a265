"""約定価格の補正（寄り値が指値より有利なら寄り値で約定）を、過去の答え合わせ済み予測にも当てはめる。

承認済み設計（2026-11-09）:
    1. 答え合わせ済みで target_open が空の行は、データ元から寄り値を取得して補う（取得できない行は飛ばす）。
    2. 約定済み（filled=1）で target_open があり fill_price が未記録の行を、
       fill_price / result_return / is_win / miss_causes について再計算する（何度実行しても結果は同じ）。
       不成立の行・寄り値が空の行は変更しない。
"""

import json
import sqlite3
from datetime import date, timedelta

from analysis.miss_analysis import classify_miss
from data_sources.base import DataSource
from tracking.trade_eval import evaluate_trade


OPEN_TOLERANCE = 0.005


def open_is_consistent(open_price: float, low: float | None, high: float | None) -> bool:
    """寄り値が、記録済みの当日の安値〜高値（±0.5%の余裕）に収まるか。

    株式分割のあとにデータ元から取り直した値は、分割で調整されて桁が変わる（記録済みの値とは別の基準になる）。
    その場合は同じ基準の値ではないため、補正に使わない。
    """
    if low is None or high is None:
        return True
    return low * (1 - OPEN_TOLERANCE) <= open_price <= high * (1 + OPEN_TOLERANCE)


def repair_inconsistent_opens(db_path: str) -> int:
    """記録済みの安値〜高値と合わない寄り値（分割調整後の値など）を取り消し、補正前の評価に戻す。件数を返す。"""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, side, entry_price, filled, target_low, target_high, target_close, target_open, "
            "pred_close, pred_daily_return, pred_volume_ratio, market_return FROM predictions "
            "WHERE evaluated = 1 AND target_open IS NOT NULL"
        ).fetchall()
        fixed = 0
        for pid, side, entry, filled, low, high, close, open_, pred_close, pred_ret, pred_vr, market in rows:
            if open_is_consistent(open_, low, high):
                continue
            fixed += 1
            conn.execute(
                "UPDATE predictions SET target_open = NULL, oc_return = NULL, fill_price = NULL WHERE id = ?", (pid,)
            )
            if not filled:
                continue
            result = evaluate_trade(side, entry, low, high, close)
            miss_causes = None
            if result.is_win is False and pred_close is not None:
                miss_causes = json.dumps(
                    classify_miss(side, pred_close, pred_ret or 0.0, pred_vr or 0.0, None, market),
                    ensure_ascii=False,
                )
            conn.execute(
                "UPDATE predictions SET result_return = ?, is_win = ?, miss_causes = ? WHERE id = ?",
                (result.result_return, None if result.is_win is None else int(result.is_win), miss_causes, pid),
            )
        conn.commit()
        return fixed
    finally:
        conn.close()


def backfill_target_open(db_path: str, source: DataSource) -> int:
    """寄り値が空の答え合わせ済み行に、始値を補う。補えた件数を返す。1件の失敗で全体を止めない。"""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, code, side, target_date, target_close, target_low, target_high FROM predictions "
            "WHERE evaluated = 1 AND target_open IS NULL"
        ).fetchall()
    finally:
        conn.close()

    updated = 0
    cache: dict[tuple[str, str], float | None] = {}
    for pid, code, side, target_date, target_close, target_low, target_high in rows:
        key = (code, target_date)
        if key not in cache:
            cache[key] = None
            try:
                d = date.fromisoformat(target_date)
                bars = [b for b in source.get_daily_bars(code, d, d + timedelta(days=1)) if b.trade_date == d]
                if bars and bars[0].open > 0:
                    cache[key] = bars[0].open
            except Exception:  # noqa: BLE001  取得失敗は飛ばす
                cache[key] = None
        open_price = cache[key]
        if open_price is None or not open_is_consistent(open_price, target_low, target_high):
            continue  # 取得できない／株式分割などで記録済みの値と基準が違う寄り値は使わない
        oc_return = (
            (open_price - target_close) / open_price if side == "sell" else (target_close - open_price) / open_price
        )
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "UPDATE predictions SET target_open = ?, oc_return = ? WHERE id = ?",
                (open_price, oc_return, pid),
            )
            conn.commit()
        finally:
            conn.close()
        updated += 1
    return updated


def recompute_fills(db_path: str) -> int:
    """寄り値補正後の約定価格で、約定済みの行の損益を再計算する。更新した件数を返す。"""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, side, entry_price, target_low, target_high, target_close, target_open, "
            "pred_close, pred_daily_return, pred_volume_ratio, market_return FROM predictions "
            "WHERE evaluated = 1 AND filled = 1 AND target_open IS NOT NULL AND fill_price IS NULL"
        ).fetchall()
        for pid, side, entry, low, high, close, open_, pred_close, pred_ret, pred_vr, market in rows:
            if not open_is_consistent(open_, low, high):
                continue
            result = evaluate_trade(side, entry, low, high, close, open_)
            miss_causes = None
            if result.is_win is False and pred_close is not None:
                miss_causes = json.dumps(
                    classify_miss(side, pred_close, pred_ret or 0.0, pred_vr or 0.0, open_, market),
                    ensure_ascii=False,
                )
            conn.execute(
                "UPDATE predictions SET fill_price = ?, result_return = ?, is_win = ?, miss_causes = ? WHERE id = ?",
                (result.fill_price, result.result_return, None if result.is_win is None else int(result.is_win), miss_causes, pid),
            )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def flag_anomalies(db_path: str) -> int:
    """答え合わせ済みで未判定の行に、株式分割などのデータ異常の疑いを付ける。付けた件数を返す（何度実行しても同じ）。"""
    from tracking.predictions_db import is_data_anomaly

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, COALESCE(pred_close, entry_price), target_close FROM predictions "
            "WHERE evaluated = 1 AND data_anomaly = 0"
        ).fetchall()
        ids = [r[0] for r in rows if is_data_anomaly(r[1], r[2])]
        conn.executemany("UPDATE predictions SET data_anomaly = 1 WHERE id = ?", [(i,) for i in ids])
        conn.commit()
        return len(ids)
    finally:
        conn.close()
