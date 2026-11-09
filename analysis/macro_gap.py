"""米国市場の前日比から、翌営業日の日本株全体の想定ギャップ（引け→寄り）の目安を出す。

承認済み設計（2026-11-09。売買の助言ではなく、環境認識の目安）:
    傾き        = Σ(x×y) / Σ(x×x)   （切片なしの最小二乗。x=米国の前日比、y=日本株全体の平均ギャップ）
    想定ギャップ = 傾き × 米国の前日比
    傾きは直近 window(=250) 営業日の組から出す。組が min_n(=60) 未満なら判定しない。
    米国の前日比 = 日本の営業日より前（当日を含まない）で最新の米国営業日の前日比。
    過去の精度は、各日をその日より前のデータだけで予測して測る（先読みなし）:
        平均誤差(MAE)・方向一致率・相関。基準として「常に0と予測」のMAEも併記する。
"""

from dataclasses import dataclass
from datetime import date, timedelta
from math import sqrt

from data_sources.base import DailyBar

WINDOW = 250
MIN_N = 60


def returns_from_bars(bars: list[DailyBar]) -> dict[date, float]:
    """日付昇順のバーから、日付→前日比（終値ベース）。先頭日と、前日終値が0以下の日は含めない。"""
    out: dict[date, float] = {}
    for prev, cur in zip(bars, bars[1:]):
        if prev.close > 0:
            out[cur.trade_date] = (cur.close - prev.close) / prev.close
    return out


def fit_slope(pairs: list[tuple[float, float]]) -> float | None:
    sxx = sum(x * x for x, _ in pairs)
    if not pairs or sxx == 0:
        return None
    return sum(x * y for x, y in pairs) / sxx


def expected_gap(slope: float, us_return: float) -> float:
    return slope * us_return


def previous_weekday(day: date) -> date:
    d = day - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def latest_before(day: date, series: dict[date, float]) -> tuple[date, float] | None:
    """series のうち、day より前（当日を含まない）で最新の日付と値。"""
    earlier = [d for d in series if d < day]
    if not earlier:
        return None
    d = max(earlier)
    return d, series[d]


@dataclass(frozen=True)
class ForecastEval:
    n: int
    corr: float | None
    mae: float | None
    mae_zero: float | None  # 常に0と予測した場合のMAE（比較用）
    direction_acc: float | None  # 予測と実際の符号が一致した割合（実際が0の日は除く）
    mean_error: float | None  # 予測 - 実際 の平均（偏り）
    start: date | None
    end: date | None


def _corr(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sqrt(sxx * syy)


def rolling_forecasts(
    us_returns: dict[date, float],
    gaps: dict[date, float],
    window: int = WINDOW,
    min_n: int = MIN_N,
) -> list[tuple[date, float, float]]:
    """日本の各営業日 t を、t より前のデータだけで予測する。(日付, 予測, 実際) の一覧を返す。"""
    days = sorted(gaps)
    x_for: dict[date, float] = {}
    for d in days:
        hit = latest_before(d, us_returns)
        if hit is not None:
            x_for[d] = hit[1]

    out = []
    for i, d in enumerate(days):
        if d not in x_for:
            continue
        past = [(x_for[p], gaps[p]) for p in days[:i] if p in x_for][-window:]
        if len(past) < min_n:
            continue
        slope = fit_slope(past)
        if slope is None:
            continue
        out.append((d, expected_gap(slope, x_for[d]), gaps[d]))
    return out


def evaluate_forecasts(forecasts: list[tuple[date, float, float]]) -> ForecastEval:
    if not forecasts:
        return ForecastEval(0, None, None, None, None, None, None, None)
    preds = [p for _, p, _ in forecasts]
    actuals = [a for _, _, a in forecasts]
    n = len(forecasts)
    nonzero = [(p, a) for p, a in zip(preds, actuals) if a != 0]
    dir_acc = (
        sum(1 for p, a in nonzero if (p > 0) == (a > 0) and p != 0) / len(nonzero) if nonzero else None
    )
    return ForecastEval(
        n=n,
        corr=_corr(preds, actuals),
        mae=sum(abs(p - a) for p, a in zip(preds, actuals)) / n,
        mae_zero=sum(abs(a) for a in actuals) / n,
        direction_acc=dir_acc,
        mean_error=sum(p - a for p, a in zip(preds, actuals)) / n,
        start=forecasts[0][0],
        end=forecasts[-1][0],
    )
