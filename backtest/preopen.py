"""寄り付き前に分かる情報（前日の確定値＋想定始値＋地合い）で、デイトレの値動きを検証する。

承認済み前提（2026-11-09。ご提示のルールを、無料の日次データで検証できる形にしたもの）:
    確定値: 前日終値・前日出来高・前日までのATR(14日単純平均)・前日までの日足
    見込み値: 想定始値 = 当日の実際の始値で代用する（寄り前気配と少しずれるため、やや楽観的）
    ATR       = 直近14本の True Range の単純平均。True Range = max(高-安, |高-前日終値|, |安-前日終値|)
    gap_atr   = (当日始値 - 前日終値) / ATR   （ギャップの方向と、ATR比での大きさ）
    atr_pct   = ATR / 前日終値                 （想定値幅の余地）
    vol_ratio = 前日出来高 / その前20営業日の平均出来高
    地合い    = 米国(S&P500)・ドル円・日経平均の前日比。米国・ドル円は「当日より前の最新の日」の値
    結果      = oc = (当日終値 - 始値) / 始値。買いは oc>0、売りは oc<0 が的中。
    偶然との区別: 日単位のブートストラップ（日ごとにまとめて再標本化）で、平均リターンの差の信頼区間とp値を出す。
    PTS・ADR・寄り前気配・適時開示・SNSは無料データで取得できないため検証に含めない。
"""

from bisect import bisect_left
from dataclasses import dataclass
from datetime import date
from math import sqrt

import numpy as np

from data_sources.base import DailyBar

ATR_PERIOD = 14
VOL_PERIOD = 20


def true_range(prev_close: float, high: float, low: float) -> float:
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def atr(bars: list[DailyBar], period: int = ATR_PERIOD) -> float | None:
    """bars（日付昇順）の最後の period 本の True Range の単純平均。前日終値が必要なので period+1 本以上要る。"""
    if len(bars) < period + 1:
        return None
    window = bars[-(period + 1) :]
    trs = [true_range(prev.close, cur.high, cur.low) for prev, cur in zip(window, window[1:])]
    return sum(trs) / period


@dataclass(frozen=True)
class Sample:
    day: date
    code: str
    prev_close: float
    open: float
    close: float
    gap_atr: float
    atr_pct: float
    vol_ratio: float
    breakout20: bool  # 前日終値が、その前20営業日の終値の最高値を上回った（日足の上抜け）
    us_ret: float | None
    fx_ret: float | None
    nk_prev_ret: float | None

    @property
    def oc(self) -> float:
        return (self.close - self.open) / self.open


def _returns_by_date(bars: list[DailyBar]) -> tuple[list[date], list[float]]:
    dates, rets = [], []
    for prev, cur in zip(bars, bars[1:]):
        if prev.close > 0:
            dates.append(cur.trade_date)
            rets.append((cur.close - prev.close) / prev.close)
    return dates, rets


def latest_return_before(day: date, dates: list[date], rets: list[float]) -> float | None:
    """day より前（当日は含めない）の最新の日の前日比。"""
    i = bisect_left(dates, day)
    return rets[i - 1] if i > 0 else None


def build_samples(
    bars_by_code: dict[str, list[DailyBar]],
    index_bars: list[DailyBar],
    us_bars: list[DailyBar],
    fx_bars: list[DailyBar],
) -> list[Sample]:
    """各銘柄・各営業日の、寄り前特徴量と当日の結果（oc）を作る。特徴量は前日までのデータと当日の始値だけを使う。"""
    us_dates, us_rets = _returns_by_date(us_bars)
    fx_dates, fx_rets = _returns_by_date(fx_bars)
    nk_dates, nk_rets = _returns_by_date(index_bars)

    samples: list[Sample] = []
    for code, bars in bars_by_code.items():
        for t in range(ATR_PERIOD + 1, len(bars)):
            today = bars[t]
            prev = bars[t - 1]
            history = bars[:t]  # 前日まで
            a = atr(history)
            if a is None or a <= 0 or prev.close <= 0 or today.open <= 0:
                continue
            prior_vols = [b.volume for b in bars[max(0, t - 1 - VOL_PERIOD) : t - 1]]
            if len(prior_vols) < VOL_PERIOD or sum(prior_vols) <= 0:
                continue
            prior_closes = [b.close for b in bars[max(0, t - 1 - VOL_PERIOD) : t - 1]]
            samples.append(
                Sample(
                    day=today.trade_date,
                    code=code,
                    prev_close=prev.close,
                    open=today.open,
                    close=today.close,
                    gap_atr=(today.open - prev.close) / a,
                    atr_pct=a / prev.close,
                    vol_ratio=prev.volume / (sum(prior_vols) / VOL_PERIOD),
                    breakout20=prev.close > max(prior_closes),
                    us_ret=latest_return_before(today.trade_date, us_dates, us_rets),
                    fx_ret=latest_return_before(today.trade_date, fx_dates, fx_rets),
                    nk_prev_ret=latest_return_before(today.trade_date, nk_dates, nk_rets),
                )
            )
    return samples


# ---------------- 統計 ----------------
def wilson_interval(wins: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n <= 0:
        return None
    p = wins / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - half) / denom, (centre + half) / denom


@dataclass(frozen=True)
class BootResult:
    mean: float | None
    ci_low: float | None
    ci_high: float | None
    p_not_positive: float | None  # 差がプラスでない確率（片側）。小さいほど「プラスは偶然でない」


def cluster_bootstrap_diff(
    day_stats: dict[date, tuple[float, int, float, int]],
    resamples: int = 10_000,
    seed: int = 0,
) -> BootResult:
    """日ごとの (選んだ分の合計, 件数, 全体の合計, 件数) を、日単位で再標本化し、
    「選んだ分の平均 - 全体の平均」の信頼区間を出す。同じ日の銘柄は連動するため、日をまとめて扱う。"""
    days = sorted(day_stats)
    if not days:
        return BootResult(None, None, None, None)
    s_sum = np.array([day_stats[d][0] for d in days], dtype=float)
    s_n = np.array([day_stats[d][1] for d in days], dtype=float)
    a_sum = np.array([day_stats[d][2] for d in days], dtype=float)
    a_n = np.array([day_stats[d][3] for d in days], dtype=float)
    if s_n.sum() == 0 or a_n.sum() == 0:
        return BootResult(None, None, None, None)

    point = s_sum.sum() / s_n.sum() - a_sum.sum() / a_n.sum()
    rng = np.random.default_rng(seed)
    counts = rng.multinomial(len(days), np.full(len(days), 1 / len(days)), size=resamples).astype(float)
    sel_n = counts @ s_n
    all_n = counts @ a_n
    valid = (sel_n > 0) & (all_n > 0)
    diffs = (counts @ s_sum)[valid] / sel_n[valid] - (counts @ a_sum)[valid] / all_n[valid]
    if diffs.size == 0:
        return BootResult(point, None, None, None)
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return BootResult(
        mean=float(point), ci_low=float(lo), ci_high=float(hi), p_not_positive=float((diffs <= 0).mean())
    )


# ---------------- 検討ルール（事前に決めた固定の組み合わせ） ----------------
@dataclass(frozen=True)
class Strategy:
    name: str
    direction: int  # +1=買い（寄りで買い、引けで決済） / -1=売り
    predicate: "callable"


def _f_atr(s: Sample) -> bool:  # 想定値幅: ATR基準で3%以上の余地
    return s.atr_pct >= 0.03


def _f_gap(s: Sample) -> bool:  # ギャップが過大すぎない: |gap|がATRの1倍以下
    return abs(s.gap_atr) <= 1.0


def _f_vol(s: Sample) -> bool:  # 前日出来高が平均の2倍以上
    return s.vol_ratio >= 2.0


SIGNALS: list[tuple[str, int, "callable"]] = [
    ("gapup_cont", +1, lambda s: 0.3 <= s.gap_atr <= 1.0),
    ("gapup_fade", -1, lambda s: 0.3 <= s.gap_atr <= 1.0),
    ("gapdown_cont", -1, lambda s: -1.0 <= s.gap_atr <= -0.3),
    ("gapdown_fade", +1, lambda s: -1.0 <= s.gap_atr <= -0.3),
    ("panic_fade", +1, lambda s: s.gap_atr <= -1.5),
    ("panic_cont", -1, lambda s: s.gap_atr <= -1.5),
    ("breakout_cont", +1, lambda s: s.breakout20),
    ("breakout_fade", -1, lambda s: s.breakout20),
    ("us_up_long", +1, lambda s: s.us_ret is not None and s.us_ret >= 0.005),
    ("us_down_short", -1, lambda s: s.us_ret is not None and s.us_ret <= -0.005),
    ("fx_up_long", +1, lambda s: s.fx_ret is not None and s.fx_ret >= 0.005),
    ("fx_down_short", -1, lambda s: s.fx_ret is not None and s.fx_ret <= -0.005),
]

FILTER_SETS: list[tuple[str, list]] = [
    ("", []),
    ("+atr3", [_f_atr]),
    ("+atr3+gap1", [_f_atr, _f_gap]),
    ("+vol2", [_f_vol]),
]


def build_strategies() -> list[Strategy]:
    """基準（全件の買い・全件の売り）と、シグナル×フィルターの組み合わせ（12×4=48通り）。"""
    out = [Strategy("ALL_long", +1, lambda s: True), Strategy("ALL_short", -1, lambda s: True)]
    for sig_name, direction, sig in SIGNALS:
        for suffix, filters in FILTER_SETS:
            out.append(
                Strategy(
                    sig_name + suffix,
                    direction,
                    (lambda sig, filters: lambda s: sig(s) and all(f(s) for f in filters))(sig, filters),
                )
            )
    return out


@dataclass(frozen=True)
class StrategyResult:
    name: str
    n: int
    win_rate: float | None
    wilson: tuple[float, float] | None
    avg_gross: float | None
    avg_net: float | None
    ret_boot: BootResult  # 平均リターンの、基準（同じ向きの全件）との差
    win_boot: BootResult  # 的中率の、基準との差


def _day_stats(selected: list[tuple[date, float]], baseline: list[tuple[date, float]]):
    days: dict[date, list[float]] = {}
    for d, v in selected:
        days.setdefault(d, [0.0, 0, 0.0, 0])
        days[d][0] += v
        days[d][1] += 1
    for d, v in baseline:
        days.setdefault(d, [0.0, 0, 0.0, 0])
        days[d][2] += v
        days[d][3] += 1
    return {d: tuple(v) for d, v in days.items()}


def evaluate_strategy(
    samples: list[Sample],
    strategy: Strategy,
    cost: float = 0.001,
    resamples: int = 10_000,
    seed: int = 0,
) -> StrategyResult:
    """向きを付けたリターン r = direction × oc。的中は r>0。基準は、同じ向きの全サンプル。"""
    base_r = [(s.day, strategy.direction * s.oc) for s in samples]
    sel = [(s.day, strategy.direction * s.oc) for s in samples if strategy.predicate(s)]
    n = len(sel)
    wins = sum(1 for _, r in sel if r > 0)
    ret_boot = cluster_bootstrap_diff(_day_stats(sel, base_r), resamples, seed)
    win_boot = cluster_bootstrap_diff(
        _day_stats([(d, 1.0 if r > 0 else 0.0) for d, r in sel], [(d, 1.0 if r > 0 else 0.0) for d, r in base_r]),
        resamples,
        seed,
    )
    avg = sum(r for _, r in sel) / n if n else None
    return StrategyResult(
        name=strategy.name,
        n=n,
        win_rate=wins / n if n else None,
        wilson=wilson_interval(wins, n),
        avg_gross=avg,
        avg_net=None if avg is None else avg - cost,
        ret_boot=ret_boot,
        win_boot=win_boot,
    )


MIN_TRADES = 200
BONFERRONI_TESTS = 48


def is_candidate(train: StrategyResult, valid: StrategyResult, n_tests: int = BONFERRONI_TESTS) -> bool:
    """採用候補の条件（事前に固定）:
    前半で、基準との平均リターン差のp値が 0.05/検定数 未満（多重比較の補正）、
    後半で p<0.05、両期間で 差>0・費用後の平均>0・件数が MIN_TRADES 以上。
    """
    for r in (train, valid):
        if r.n < MIN_TRADES or r.avg_net is None or r.avg_net <= 0:
            return False
        if r.ret_boot.mean is None or r.ret_boot.mean <= 0 or r.ret_boot.p_not_positive is None:
            return False
    return train.ret_boot.p_not_positive < 0.05 / n_tests and valid.ret_boot.p_not_positive < 0.05


def split_samples(samples: list[Sample], train_ratio: float = 0.7) -> tuple[list[Sample], list[Sample]]:
    """日付の古い順に、前半（条件を決める期間）と後半（確かめる期間）へ日単位で分ける。"""
    days = sorted({s.day for s in samples})
    cut = int(len(days) * train_ratio)
    train_days = set(days[:cut])
    return [s for s in samples if s.day in train_days], [s for s in samples if s.day not in train_days]
