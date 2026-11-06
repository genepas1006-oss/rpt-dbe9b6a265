"""過去データでスコアリングを検証するバックテスト。

承認済み設計（2026-11-06）:
    - 各営業日 t について、t までのデータだけで今と同じ方法で買い・売りTOP Nを選ぶ。
    - 答え合わせは、指数の営業日列における次の営業日の足で、本番と同じ約定ルール
      （tracking.trade_eval）を使う。祝日をまたいでも次の営業日の足を使う。
    - 候補の特徴量（地合い・乖離率・RSI）は t までの終値だけから計算し、
      Variant（フィルター）で候補プールから除外してからTOP Nを選ぶ。
    - 手数料・スリッページは含まない。
"""

from dataclasses import dataclass
from datetime import date
from typing import Callable

from analysis.earnings import compute_earnings_score, compute_short_earnings_score
from analysis.indicators import ma_deviation, market_bias, rsi_simple
from analysis.scoring import CandidateInput, Side, rank_candidates
from analysis.technical import compute_short_technical_score, compute_technical_score
from config import ENTRY_DISCOUNT, TOP_N
from data_sources.base import DailyBar
from tracking.trade_eval import evaluate_trade


@dataclass(frozen=True)
class Features:
    market_bias: int | None
    deviation25: float | None
    rsi14: float | None


@dataclass(frozen=True)
class DayCandidate:
    code: str
    features: Features
    buy: CandidateInput
    sell: CandidateInput
    next_bar: DailyBar


@dataclass(frozen=True)
class TradingDay:
    day: date
    next_day: date
    candidates: list[DayCandidate]


@dataclass(frozen=True)
class Trade:
    day: date
    next_day: date
    side: Side
    code: str
    entry_price: float
    filled: bool
    result_return: float | None
    is_win: bool | None


def build_trading_days(
    bars_by_code: dict[str, list[DailyBar]],
    names: dict[str, str],
    index_bars: list[DailyBar],
    earnings_by_code: dict[str, list[date]] | None = None,
) -> list[TradingDay]:
    """各営業日の候補（スコア・特徴量・翌営業日の足）を、その日までのデータだけから組み立てる。"""
    earnings_by_code = earnings_by_code or {}
    index_closes = [b.close for b in index_bars]
    position = {
        code: {b.trade_date: i for i, b in enumerate(bars)} for code, bars in bars_by_code.items()
    }

    days: list[TradingDay] = []
    for i in range(len(index_bars) - 1):
        today = index_bars[i].trade_date
        next_day = index_bars[i + 1].trade_date
        bias = market_bias(index_closes[: i + 1])

        candidates = []
        for code, bars in bars_by_code.items():
            idx = position[code].get(today)
            next_idx = position[code].get(next_day)
            if idx is None or next_idx is None:
                continue  # 当日または翌営業日の足がない銘柄は対象外（欠損で全体を止めない）

            history = bars[: idx + 1]
            # t時点で既に判明している決算日だけを使う（将来の決算日を見ない）
            known_earnings = [d for d in earnings_by_code.get(code, []) if d <= today]
            closes = [b.close for b in history]
            bar = bars[idx]

            def make(tech, earn):
                return CandidateInput(
                    code=code,
                    name=names.get(code, code),
                    close=bar.close,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    volume=bar.volume,
                    technical=tech,
                    earnings=earn,
                )

            candidates.append(
                DayCandidate(
                    code=code,
                    features=Features(
                        market_bias=bias,
                        deviation25=ma_deviation(closes),
                        rsi14=rsi_simple(closes),
                    ),
                    buy=make(
                        compute_technical_score(history),
                        compute_earnings_score(history, known_earnings),
                    ),
                    sell=make(
                        compute_short_technical_score(history),
                        compute_short_earnings_score(history, known_earnings),
                    ),
                    next_bar=bars[next_idx],
                )
            )
        days.append(TradingDay(day=today, next_day=next_day, candidates=candidates))
    return days


@dataclass(frozen=True)
class Variant:
    name: str
    allow: Callable[[Side, Features], bool]


def baseline() -> Variant:
    return Variant("baseline", lambda side, f: True)


def market_filter() -> Variant:
    """買いは地合い+1のとき、売りは地合い-1のときだけ候補にする（判定なしは通す）。"""

    def allow(side: Side, f: Features) -> bool:
        if f.market_bias is None:
            return True
        return f.market_bias == (1 if side == "buy" else -1)

    return Variant("market", allow)


def overheat_filter(dev_threshold: float | None = None, rsi_threshold: float | None = None) -> Variant:
    """過熱した銘柄を除外する。

    買い: 乖離率 >= dev_threshold または RSI >= rsi_threshold を除外。
    売り: 乖離率 <= -dev_threshold または RSI <= 100 - rsi_threshold を除外。
    判定なし（None）の特徴量では除外しない。
    """

    def allow(side: Side, f: Features) -> bool:
        if side == "buy":
            if dev_threshold is not None and f.deviation25 is not None and f.deviation25 >= dev_threshold:
                return False
            if rsi_threshold is not None and f.rsi14 is not None and f.rsi14 >= rsi_threshold:
                return False
        else:
            if dev_threshold is not None and f.deviation25 is not None and f.deviation25 <= -dev_threshold:
                return False
            if rsi_threshold is not None and f.rsi14 is not None and f.rsi14 <= 100 - rsi_threshold:
                return False
        return True

    parts = []
    if dev_threshold is not None:
        parts.append(f"dev{dev_threshold * 100:g}%")
    if rsi_threshold is not None:
        parts.append(f"rsi{rsi_threshold:g}")
    return Variant("overheat:" + "+".join(parts), allow)


def combine(*variants: Variant) -> Variant:
    return Variant(
        "+".join(v.name for v in variants),
        lambda side, f: all(v.allow(side, f) for v in variants),
    )


def apply_variant(
    days: list[TradingDay],
    variant: Variant,
    top_n: int = TOP_N,
    entry_discount: float = ENTRY_DISCOUNT,
) -> list[Trade]:
    """フィルターで候補プールを絞ってからTOP Nを選び、翌営業日の足で答え合わせする。"""
    trades: list[Trade] = []
    for d in days:
        for side in ("buy", "sell"):
            pool = [
                (c.buy if side == "buy" else c.sell)
                for c in d.candidates
                if variant.allow(side, c.features)
            ]
            next_bars = {c.code: c.next_bar for c in d.candidates}
            for ranked in rank_candidates(pool, top_n=top_n, entry_discount=entry_discount, side=side):
                nb = next_bars[ranked.code]
                result = evaluate_trade(side, ranked.entry_price, nb.low, nb.high, nb.close)
                trades.append(
                    Trade(
                        day=d.day,
                        next_day=d.next_day,
                        side=side,
                        code=ranked.code,
                        entry_price=ranked.entry_price,
                        filled=result.filled,
                        result_return=result.result_return,
                        is_win=result.is_win,
                    )
                )
    return trades


@dataclass(frozen=True)
class Metrics:
    count: int
    filled: int
    fill_rate: float | None
    wins: int
    win_rate: float | None
    avg_return: float | None
    avg_win: float | None
    avg_loss: float | None
    payoff_ratio: float | None


def summarize(trades: list[Trade], side: Side) -> Metrics:
    """約定した取引の成績を集計する。

    的中 = リターン>0、負け = リターン<0。リターンちょうど0は的中でも負けでもない。
    """
    mine = [t for t in trades if t.side == side]
    filled = [t for t in mine if t.filled]
    returns = [t.result_return for t in filled]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]

    avg_win = sum(wins) / len(wins) if wins else None
    avg_loss = sum(losses) / len(losses) if losses else None
    payoff = avg_win / abs(avg_loss) if avg_win is not None and avg_loss is not None else None
    return Metrics(
        count=len(mine),
        filled=len(filled),
        fill_rate=len(filled) / len(mine) if mine else None,
        wins=len(wins),
        win_rate=len(wins) / len(filled) if filled else None,
        avg_return=sum(returns) / len(returns) if returns else None,
        avg_win=avg_win,
        avg_loss=avg_loss,
        payoff_ratio=payoff,
    )


def split_days(days: list[TradingDay], train_ratio: float = 0.7) -> tuple[list[TradingDay], list[TradingDay]]:
    """日付順に、前半（水準決め用）と後半（確認用）に分ける。"""
    ordered = sorted(days, key=lambda d: d.day)
    cut = int(len(ordered) * train_ratio)
    return ordered[:cut], ordered[cut:]
