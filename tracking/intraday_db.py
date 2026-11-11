"""寄り枠・昼の予想（日中の試験運用枠）の記録と答え合わせ。承認済み設計（2026-11-11）。

predictions に variant='opengap'（寄り枠）/ 'lunch'（昼の予想）で記録する。本番の成績・仮想資金には含めない。
    entry_price = 基準価格（寄り枠=寄り付きの始値 / 昼=前場終値の参考値）。pred_close = 前日終値（寄り枠）/ 前場の始値（昼）。
    答え合わせ: 寄り枠の基準=寄り付きの始値、昼の基準=後場の始値（12:30の最初の価格）。大引けの終値と比べる。
    的中=予想方向に動いた（同値は外れ）。約定の成否は問わない（filled=1 固定）。
"""

import json
import sqlite3
from datetime import date, datetime, time

from analysis.intraday_sets import IntradayPick, direction_result
from data_sources.base import DataSource
from report.forecast_set import JST, ForecastSet

OPEN_GAP = "opengap"
LUNCH = "lunch"
INTRADAY_VARIANTS = (OPEN_GAP, LUNCH)
FINAL_CLOSE_TIME = time(15, 35)  # これより前は、当日の大引けが確定していない
PM_OPEN_TIME = time(12, 30)


def save_intraday_picks(db_path: str, day: date, variant: str, picks: list[IntradayPick], fset: ForecastSet) -> None:
    """同じ日・同じ区分の未評価の記録を置き換えて保存する（再実行しても二重登録しない）。答え合わせ済みがあれば何もしない。"""
    conn = sqlite3.connect(db_path)
    try:
        for side in ("buy", "sell"):
            done = conn.execute(
                "SELECT COUNT(*) FROM predictions WHERE prediction_date = ? AND side = ? AND variant = ? AND evaluated = 1",
                (day.isoformat(), side, variant),
            ).fetchone()[0]
            if done:
                return
        conn.execute(
            "DELETE FROM predictions WHERE prediction_date = ? AND variant = ? AND evaluated = 0",
            (day.isoformat(), variant),
        )
        now = datetime.now(JST).isoformat()
        conn.executemany(
            "INSERT INTO predictions (prediction_date, code, name, side, total_score, technical_score, earnings_score, "
            "entry_price, reasons, target_date, evaluated, created_at, pred_close, variant, slot, valid_from, "
            "valid_until, data_as_of) VALUES (?, ?, ?, ?, 0, 0, 0, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)",
            [
                (day.isoformat(), p.code, p.name, p.side, p.ref_price, json.dumps([f"{p.move * 100:+.2f}%"], ensure_ascii=False),
                 day.isoformat(), now, p.base_close, variant, fset.slot, fset.valid_from.isoformat(),
                 fset.valid_until.isoformat(), fset.data_as_of.isoformat())
                for p in picks
            ],
        )
        conn.commit()
    finally:
        conn.close()


def _pm_open(source: DataSource, code: str, day: date) -> float | None:
    bars = [b for b in source.get_intraday_bars(code, day) if b.start.astimezone(JST).time() >= PM_OPEN_TIME]
    return min(bars, key=lambda b: b.start).open if bars else None


def evaluate_intraday_predictions(db_path: str, source: DataSource, now: datetime | None = None) -> int:
    """答え合わせ待ちの寄り枠・昼の予想を、大引けの終値で判定する。件数を返す。1件の失敗で全体を止めない。"""
    now = (now or datetime.now(JST)).astimezone(JST)
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, code, side, entry_price, target_date, variant FROM predictions "
            f"WHERE evaluated = 0 AND variant IN ({','.join('?' * len(INTRADAY_VARIANTS))})",
            INTRADAY_VARIANTS,
        ).fetchall()
    finally:
        conn.close()
    done = 0
    for pid, code, side, entry, target_date, variant in rows:
        day = date.fromisoformat(target_date)
        if day > now.date() or (day == now.date() and now.time() < FINAL_CLOSE_TIME):
            continue  # 大引けが確定するまで待つ
        try:
            daily = [b for b in source.get_daily_bars(code, day, day) if b.trade_date == day]
            if not daily:
                continue
            bar = daily[0]
            basis = entry if variant == OPEN_GAP else _pm_open(source, code, day)
            if not basis or basis <= 0:
                continue
        except Exception:  # noqa: BLE001
            continue
        ret, win = direction_result(side, basis, bar.close)
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "UPDATE predictions SET evaluated = 1, filled = 1, target_open = ?, target_high = ?, target_low = ?, "
                "target_close = ?, result_return = ?, is_win = ?, fill_price = ?, oc_return = ? WHERE id = ?",
                (basis, bar.high, bar.low, bar.close, ret, int(win), basis, ret, pid),
            )
            conn.commit()
        finally:
            conn.close()
        done += 1
    return done


def get_intraday_stats(db_path: str, variant: str, side: str) -> tuple[int, int]:
    """（答え合わせ済みの件数, 方向的中の件数）。データ異常は除く。"""
    conn = sqlite3.connect(db_path)
    try:
        n, hits = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(is_win = 1), 0) FROM predictions "
            "WHERE evaluated = 1 AND data_anomaly = 0 AND variant = ? AND side = ?",
            (variant, side),
        ).fetchone()
    finally:
        conn.close()
    return n, hits
