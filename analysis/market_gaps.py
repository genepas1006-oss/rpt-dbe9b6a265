"""日本株全体の夜間ギャップ（前日終値→当日始値）の日次系列。

承認済み（2026-11-09）: 各営業日について、その日と前の足がある銘柄の
(当日始値 - 前日終値) / 前日終値 を平均する。対象銘柄が min_stocks 未満の日は含めない。
"""

import json
from datetime import date
from pathlib import Path

from data_sources.base import DailyBar

MIN_STOCKS = 100


def market_overnight_gaps(
    bars_by_code: dict[str, list[DailyBar]], min_stocks: int = MIN_STOCKS
) -> dict[date, float]:
    sums: dict[date, float] = {}
    counts: dict[date, int] = {}
    for bars in bars_by_code.values():
        for prev, cur in zip(bars, bars[1:]):
            if prev.close <= 0 or cur.open <= 0:
                continue
            d = cur.trade_date
            sums[d] = sums.get(d, 0.0) + (cur.open - prev.close) / prev.close
            counts[d] = counts.get(d, 0) + 1
    return {d: sums[d] / counts[d] for d in sums if counts[d] >= min_stocks}


def save_market_gaps(path: Path, gaps: dict[date, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({d.isoformat(): g for d, g in sorted(gaps.items())}), encoding="utf-8")


def load_market_gaps(path: Path) -> dict[date, float]:
    """壊れている・無い場合は空の辞書（呼び出し側が「不明」として扱う）。"""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {date.fromisoformat(k): float(v) for k, v in raw.items()}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}
