"""寄り前の環境認識（米国市場→日本株全体の想定ギャップの目安）。売買の助言ではない。

承認済み設計（2026-11-09）。事実／推測／不明を区別し、出所と基準日を付ける。
朝（米国市場の確定後）に run_premarket.py が計算して reports/premarket.json に保存し、
サイトの上部に表示する。対象日向けの値が無い場合は「不明（理由）」と表示する。
"""

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from analysis.macro_gap import (
    MIN_N,
    WINDOW,
    evaluate_forecasts,
    expected_gap,
    fit_slope,
    latest_before,
    previous_weekday,
    returns_from_bars,
    rolling_forecasts,
)
from data_sources.base import DailyBar


@dataclass(frozen=True)
class Premarket:
    for_date: date          # 想定ギャップの対象日（日本の営業日）
    us_date: date           # 使った米国市場の基準日
    us_return: float        # その日の前日比（事実）
    slope: float
    expected_gap: float     # 推測
    n_fit: int              # 傾きを出した組の数
    eval_n: int             # 過去の精度の検証日数
    eval_start: date | None
    eval_end: date | None
    corr: float | None
    mae: float | None
    mae_zero: float | None
    direction_acc: float | None
    generated_at: str

    def to_json(self) -> str:
        d = asdict(self)
        for k in ("for_date", "us_date", "eval_start", "eval_end"):
            d[k] = None if d[k] is None else d[k].isoformat()
        return json.dumps(d, ensure_ascii=False)

    @staticmethod
    def from_dict(d: dict) -> "Premarket":
        def dt(v):
            return None if v is None else date.fromisoformat(v)

        return Premarket(
            for_date=date.fromisoformat(d["for_date"]),
            us_date=date.fromisoformat(d["us_date"]),
            us_return=float(d["us_return"]),
            slope=float(d["slope"]),
            expected_gap=float(d["expected_gap"]),
            n_fit=int(d["n_fit"]),
            eval_n=int(d["eval_n"]),
            eval_start=dt(d.get("eval_start")),
            eval_end=dt(d.get("eval_end")),
            corr=d.get("corr"),
            mae=d.get("mae"),
            mae_zero=d.get("mae_zero"),
            direction_acc=d.get("direction_acc"),
            generated_at=str(d.get("generated_at", "")),
        )


def save_premarket(path: Path, pm: Premarket) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(pm.to_json(), encoding="utf-8")


def load_premarket(path: Path) -> Premarket | None:
    """無い・壊れている場合は None（表示側が「不明」として扱う）。"""
    try:
        return Premarket.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def compute_premarket(
    gaps: dict[date, float],
    us_bars: list[DailyBar],
    for_date: date,
    generated_at: str,
    window: int = WINDOW,
    min_n: int = MIN_N,
) -> tuple[Premarket | None, str | None]:
    """for_date（日本の営業日）向けの想定ギャップ。計算できなければ (None, 理由)。

    米国市場の基準日は、for_date の前の平日（月曜なら金曜）でなければならない。
    それより古い場合は、米国市場の更新前、または米国の休場として「不明」にする。
    """
    us_returns = returns_from_bars(us_bars)
    required = previous_weekday(for_date)
    latest = latest_before(for_date, us_returns)
    if latest is None or latest[0] != required:
        return None, f"米国市場の基準日 {required.isoformat()} の値がありません（未更新、または米国の休場）"
    us_date, us_ret = latest

    past_gaps = {d: g for d, g in gaps.items() if d < for_date}
    pairs = []
    for d in sorted(past_gaps):
        hit = latest_before(d, us_returns)
        if hit is not None:
            pairs.append((hit[1], past_gaps[d]))
    pairs = pairs[-window:]
    if len(pairs) < min_n:
        return None, f"傾きを出すためのデータが足りません（{len(pairs)}件、必要 {min_n}件）"
    slope = fit_slope(pairs)
    if slope is None:
        return None, "傾きを計算できませんでした（米国の値動きがありません）"

    ev = evaluate_forecasts(rolling_forecasts(us_returns, past_gaps, window, min_n))
    return (
        Premarket(
            for_date=for_date,
            us_date=us_date,
            us_return=us_ret,
            slope=slope,
            expected_gap=expected_gap(slope, us_ret),
            n_fit=len(pairs),
            eval_n=ev.n,
            eval_start=ev.start,
            eval_end=ev.end,
            corr=ev.corr,
            mae=ev.mae,
            mae_zero=ev.mae_zero,
            direction_acc=ev.direction_acc,
            generated_at=generated_at,
        ),
        None,
    )
