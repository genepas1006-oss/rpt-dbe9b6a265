"""前場・後場の時間帯別の的中率（承認済み設計 2026-11-20）。

すべての予想を、前場（9:00〜11:30）と後場（12:30〜15:30）の別に、同じ基準（その時間帯の始値→終値の方向）で集計する。
    前場の値動き = 前場の最初の足の始値 → 前場の最後の足の終値 / 後場の値動き = 後場の最初の足の始値 → 最後の足の終値（5分足）
    買いは上昇・売りは下落で的中。同値は外れ。
    除外: 最初の足が時間帯開始の10分後より遅い / 最後の足の終わりが時間帯終了の10分前より早い / 始値が0以下 / データ異常の予想。
    昼の予想の前場は対象外（前場の値動きで選んでいるため）。参考として、全銘柄の上がった（下がった）割合も出す。
5分足は data/bars_5m/YYYY-MM-DD.json.gz（毎日保存）から読む。足りない日は、Yahoo!ファイナンスの直近約60日分から補う。
"""

import gzip
import json
import sqlite3
from datetime import date
from pathlib import Path

DEFAULT_DIR = Path("data/bars_5m")
SESSIONS = {"am": ("09:00", "11:30"), "pm": ("12:30", "15:30")}
EDGE_MIN = 10  # 時間帯の端の許容（分）
BAR_MIN = 5

# (表示名, variant)。昼の予想の前場は対象外
ROWS = [("夜の予想", "main"), ("テスト枠（値動き重視）", "volatile"), ("寄り枠", "opengap"), ("昼の予想", "lunch")]
NOT_APPLICABLE = {("lunch", "am")}


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def session_return(rows: list, session: str) -> float | None:
    """rows=[[HH:MM, 始値, 高値, 安値, 終値, 出来高], ...]（時刻昇順でなくてよい）。時間帯の値動き（割合）。欠損はNone。"""
    start, end = (_minutes(x) for x in SESSIONS[session])
    bars = sorted((r for r in rows if start <= _minutes(r[0]) < end), key=lambda r: _minutes(r[0]))
    if not bars:
        return None
    first, last = bars[0], bars[-1]
    if _minutes(first[0]) > start + EDGE_MIN or _minutes(last[0]) + BAR_MIN < end - EDGE_MIN:
        return None
    if not first[1] or first[1] <= 0:
        return None
    return last[4] / first[1] - 1


def is_hit(side: str, ret: float) -> bool:
    return ret < 0 if side == "sell" else ret > 0


def load_day(out_dir: Path, day: date) -> dict[str, list]:
    try:
        with gzip.open(out_dir / f"{day.isoformat()}.json.gz", "rt", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _count(items: list[tuple[str, float]], side: str) -> dict[str, int]:
    return {"n": len(items), "wins": sum(1 for s, r in items if is_hit(side, r))}


def ensure_5m_history(source, codes: list[str], days: list[date], out_dir: Path = DEFAULT_DIR, workers: int = 6) -> int:
    """days のうち5分足のファイルが無い日を、データ元の履歴から補って保存する。保存した日数を返す。失敗しても止めない。"""
    missing = [d for d in sorted(set(days)) if not (out_dir / f"{d.isoformat()}.json.gz").exists()]
    if not missing or not hasattr(source, "get_intraday_history"):
        return 0
    from concurrent.futures import ThreadPoolExecutor

    def job(code):
        try:
            return code, source.get_intraday_history(code)
        except Exception:  # noqa: BLE001
            return code, []

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(job, codes))
    per_day: dict[date, dict[str, list]] = {d: {} for d in missing}
    for code, bars in results:
        for b in bars:
            d = b.start.date()
            if d in per_day:
                per_day[d].setdefault(code, []).append([b.start.strftime("%H:%M"), b.open, b.high, b.low, b.close, b.volume])
    saved = 0
    for d, data in per_day.items():
        if not data:
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{d.isoformat()}.json.gz"
        tmp = path.with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
        tmp.replace(path)
        saved += 1
    return saved


def prediction_days(db_path: str) -> list[date]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT DISTINCT target_date FROM predictions WHERE evaluated = 1 AND data_anomaly = 0"
        ).fetchall()
    finally:
        conn.close()
    return [date.fromisoformat(r[0]) for r in rows]


def compute_session_table(db_path: str, bars_dir: Path = DEFAULT_DIR) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        preds = conn.execute(
            "SELECT variant, side, code, target_date FROM predictions WHERE evaluated = 1 AND data_anomaly = 0"
        ).fetchall()
    finally:
        conn.close()
    cache: dict[str, dict] = {}

    def day_data(d: str) -> dict:
        if d not in cache:
            cache[d] = load_day(bars_dir, date.fromisoformat(d))
        return cache[d]

    rows_out = []
    for label, variant in ROWS:
        row = {"label": label, "variant": variant}
        for side in ("buy", "sell"):
            row[side] = {}
            for sess in ("am", "pm"):
                if (variant, sess) in NOT_APPLICABLE:
                    row[side][sess] = None
                    continue
                items = []
                for v, sd, code, td in preds:
                    if v != variant or sd != side:
                        continue
                    r = session_return(day_data(td).get(code, []), sess)
                    if r is not None:
                        items.append((side, r))
                row[side][sess] = _count(items, side)
        rows_out.append(row)

    # 参考: 全銘柄の、その時間帯に上がった（下がった）割合。予想の対象日と同じ日のみ
    days = sorted({td for _, _, _, td in preds})
    base = {"label": "全銘柄（参考）", "variant": "all"}
    for side in ("buy", "sell"):
        base[side] = {}
        for sess in ("am", "pm"):
            items = []
            for d in days:
                for code, rows in day_data(d).items():
                    r = session_return(rows, sess)
                    if r is not None:
                        items.append((side, r))
            base[side][sess] = _count(items, side)
    rows_out.append(base)
    return {"rows": rows_out, "days": len(days)}


def save_session_stats(path: Path, table: dict, generated_at: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**table, "generated_at": generated_at}, ensure_ascii=False), encoding="utf-8")


def load_session_stats(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if data.get("rows") else None
    except (OSError, ValueError, AttributeError):
        return None
