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


def backfill_target_open(db_path: str, source: DataSource) -> int:
    """寄り値が空の答え合わせ済み行に、始値を補う。補えた件数を返す。1件の失敗で全体を止めない。"""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, code, side, target_date, target_close FROM predictions "
            "WHERE evaluated = 1 AND target_open IS NULL"
        ).fetchall()
    finally:
        conn.close()

    updated = 0
    cache: dict[tuple[str, str], float | None] = {}
    for pid, code, side, target_date, target_close in rows:
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
        if open_price is None:
            continue
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
