"""日経225先物（CME・夜間）の動きから、日本株全体の想定ギャップ（引け→寄り）の目安を出す。

承認済み設計（2026-11-13。売買の助言ではなく、環境認識の目安）:
    先物の動き = 当日8:30（日本時間）以前で最後に完結した1時間足の終値 ÷ 前営業日15:30以前で最後に完結した1時間足の終値 − 1
        足は start から1時間。完結 = start + 1時間 <= 基準の時刻。
        当日側の足の終了が8:30の3時間より前（古い。月曜はCMEの週末休場のため60時間まで許す）、
        前営業日側の足の終了が15:30の3時間より前なら「不明」。
    前営業日 = ギャップ系列（日本株の営業日）で for_date より前の最新の日。
    傾き        = Σ(x×y) / Σ(x×x)（切片なしの最小二乗。x=先物の動き、y=日本株全体の平均ギャップ）。直近250組、60組未満は判定しない。
    想定ギャップ = 傾き × 先物の動き。過去の精度は各日をその日より前の組だけで予測して測る（先読みなし）。
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from analysis.macro_gap import MIN_N, WINDOW, ForecastEval, evaluate_forecasts, expected_gap, fit_slope
from data_sources.base import HourBar

JST = timezone(timedelta(hours=9))
MAX_STALE = timedelta(hours=3)
MAX_STALE_MONDAY = timedelta(hours=60)  # 月曜の朝は、CMEの週末休場（土曜早朝〜月曜8:00）のため直近の足が古くて当然
TARGET_HM = (8, 30)   # 当日側の基準時刻
BASE_HM = (15, 30)    # 前営業日側の基準時刻


@dataclass(frozen=True)
class FuturesGap:
    symbol: str
    move: float            # 先物の動き（事実）
    base_time: str         # 前営業日側に使った足の終了時刻
    target_time: str       # 当日側に使った足の終了時刻
    slope: float
    expected_gap: float    # 推測
    n_fit: int
    eval_n: int
    corr: float | None
    mae: float | None
    mae_zero: float | None
    direction_acc: float | None


def last_completed(bars: list[HourBar], at: datetime) -> HourBar | None:
    """at 以前に完結した（start+1時間 <= at）最後の足。bars は時刻昇順。"""
    found = None
    for b in bars:
        if b.start + timedelta(hours=1) <= at:
            found = b
        else:
            break
    return found


def _at(day: date, hm: tuple[int, int]) -> datetime:
    return datetime(day.year, day.month, day.day, hm[0], hm[1], tzinfo=JST)


def futures_move(bars: list[HourBar], day: date, prev_day: date) -> tuple[float, HourBar, HourBar] | None:
    """prev_day 15:30 → day 8:30 の先物の動き。足が無い・古い・価格が0以下なら None。"""
    t_at, b_at = _at(day, TARGET_HM), _at(prev_day, BASE_HM)
    target, base = last_completed(bars, t_at), last_completed(bars, b_at)
    if target is None or base is None or base.close <= 0:
        return None
    limit = MAX_STALE_MONDAY if day.weekday() == 0 else MAX_STALE
    if t_at - (target.start + timedelta(hours=1)) > limit or b_at - (base.start + timedelta(hours=1)) > MAX_STALE:
        return None
    return target.close / base.close - 1, base, target


def compute_futures_gap(
    bars: list[HourBar],
    gaps: dict[date, float],
    for_date: date,
    symbol: str,
    window: int = WINDOW,
    min_n: int = MIN_N,
) -> tuple[FuturesGap | None, str | None]:
    """for_date 向けの想定ギャップ（先物ベース）。計算できなければ (None, 理由)。"""
    if not bars:
        return None, "先物の取得に失敗しました（取得制限・休場など）"
    past = sorted(d for d in gaps if d < for_date)
    if not past:
        return None, "日本株の過去のギャップがありません"
    now_move = futures_move(bars, for_date, past[-1])
    if now_move is None:
        return None, "先物の最新値が古い、または基準の足がありません"
    x, base, target = now_move

    pairs: list[tuple[date, float, float]] = []  # (日付, 先物の動き, ギャップ)
    for prev, d in zip(past, past[1:]):
        m = futures_move(bars, d, prev)
        if m is not None:
            pairs.append((d, m[0], gaps[d]))
    fit = [(px, py) for _, px, py in pairs][-window:]
    if len(fit) < min_n:
        return None, f"傾きを出すためのデータが足りません（{len(fit)}件、必要 {min_n}件）"
    slope = fit_slope(fit)
    if slope is None:
        return None, "傾きを計算できませんでした"

    forecasts = []
    for i, (d, px, py) in enumerate(pairs):
        prior = [(a, b) for _, a, b in pairs[:i]][-window:]
        if len(prior) < min_n:
            continue
        s = fit_slope(prior)
        if s is not None:
            forecasts.append((d, expected_gap(s, px), py))
    ev: ForecastEval = evaluate_forecasts(forecasts)
    end = lambda b: (b.start + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")  # noqa: E731
    return (
        FuturesGap(
            symbol=symbol,
            move=x,
            base_time=end(base),
            target_time=end(target),
            slope=slope,
            expected_gap=expected_gap(slope, x),
            n_fit=len(fit),
            eval_n=ev.n,
            corr=ev.corr,
            mae=ev.mae,
            mae_zero=ev.mae_zero,
            direction_acc=ev.direction_acc,
        ),
        None,
    )
