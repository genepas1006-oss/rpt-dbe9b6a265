"""SBI証券の取引結果CSVから、日ごとの実現損益を集計する（損益カレンダー用）。

承認済み設計（2026-11-20）:
    日の損益 = その日（約定日）に約定した「信用返済」の行の「受渡金額・決済損益」の合計。
        SBI証券が出す値そのままで、手数料を引いた後の金額。新規建て（損益の値がない行）は含めない。
        日をまたいで持ち越した建玉は、返済した日に計上する。
    保存するのは日付・損益・返済の件数だけ（銘柄名・株数・単価・約定価格は保存しない）。
    同じ日付が再び取り込まれたら、その日を置き換える（何度取り込んでも同じ結果）。
"""

import csv
import io
import json
from datetime import date, datetime
from pathlib import Path

CODE_COL, TYPE_COL, DATE_COL, FEE_COL, PNL_COL = 0, 3, 6, 10, 12


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp932"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("CSVの文字コードを判別できません（UTF-8またはShift-JISのみ対応）")


def _num(s: str) -> int | None:
    s = s.replace(",", "").replace("，", "").replace("−", "-").replace("▲", "-").strip()
    if s in ("", "--", "-"):
        return None
    try:
        return int(round(float(s)))
    except ValueError:
        return None


def parse_daily_pnl(raw: bytes | str) -> dict[str, dict[str, int]]:
    """CSVの中身から {日付(YYYY-MM-DD): {"pnl": 損益, "trades": 返済の件数}} を作る。"""
    text = raw if isinstance(raw, str) else _decode(raw)
    rows = list(csv.reader(io.StringIO(text)))
    days: dict[str, dict[str, int]] = {}
    for r in rows[1:]:
        if len(r) <= PNL_COL or "返済" not in r[TYPE_COL]:
            continue
        pnl = _num(r[PNL_COL])
        if pnl is None:
            continue
        try:
            d = datetime.strptime(r[DATE_COL].strip(), "%Y/%m/%d").date().isoformat()
        except ValueError:
            continue
        cur = days.setdefault(d, {"pnl": 0, "trades": 0})
        cur["pnl"] += pnl
        cur["trades"] += 1
    return days


def load_daily_pnl(path: Path) -> dict[str, dict[str, int]]:
    """無い・壊れている場合は空の辞書。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {k: {"pnl": int(v["pnl"]), "trades": int(v.get("trades", 0))} for k, v in data.get("days", {}).items()}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return {}


def merge_daily_pnl(existing: dict[str, dict[str, int]], new: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    """新しいCSVに含まれる日付は置き換え、含まれない日付は残す。"""
    merged = dict(existing)
    merged.update(new)
    return dict(sorted(merged.items()))


def save_daily_pnl(path: Path, days: dict[str, dict[str, int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"updated": date.today().isoformat(), "days": dict(sorted(days.items()))}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
