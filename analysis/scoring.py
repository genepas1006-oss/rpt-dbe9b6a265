"""総合スコアリング・TOP N選出・参考指値算出。

承認済み設計（2026-08-21、買い）:
    total_score = technical_score(0〜5) + earnings_score(0〜2)
    total_score = 0 の銘柄は候補から除外する（水増ししない）。
    順位は total_score 降順、同点は volume_ratio 降順でタイブレークする。
    参考指値 = 当日終値 × (1 - ENTRY_DISCOUNT)。

承認済み設計（2026-10-26、売り・ショート）:
    total_score・順位ロジックは買いと共通。
    参考売り指値 = 当日終値 × (1 + ENTRY_DISCOUNT)（終値より高く空売りする）。
"""

from dataclasses import dataclass, field
from typing import Literal

from analysis.earnings import EarningsScore
from analysis.technical import TechnicalScore
from config import ENTRY_DISCOUNT, TOP_N

Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class CandidateInput:
    code: str
    name: str
    close: float
    technical: TechnicalScore | None
    earnings: EarningsScore | None
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: float = 0.0


@dataclass(frozen=True)
class RankedCandidate:
    code: str
    name: str
    total_score: int
    technical_score: int
    earnings_score: int
    volume_ratio: float
    entry_price: float
    reasons: list[str] = field(default_factory=list)
    side: Side = "buy"
    day_open: float = 0.0
    day_high: float = 0.0
    day_low: float = 0.0
    day_close: float = 0.0
    day_volume: float = 0.0


def rank_candidates(
    candidates: list[CandidateInput],
    top_n: int = TOP_N,
    entry_discount: float = ENTRY_DISCOUNT,
    side: Side = "buy",
) -> list[RankedCandidate]:
    """候補銘柄群からtotal_score>0のものだけをスコアリングし、上位top_n件を返す。

    side="buy"なら終値より安く買う参考指値、side="sell"なら終値より高く空売りする
    参考指値を算出する。スコアリング・順位ロジック自体はside共通
    （呼び出し側でside別のtechnical/earningsスコアを渡し分ける）。
    """
    price_multiplier = (1 - entry_discount) if side == "buy" else (1 + entry_discount)

    scored = []
    for c in candidates:
        technical_score = c.technical.technical_score if c.technical else 0
        earnings_score = c.earnings.earnings_score if c.earnings else 0
        total_score = technical_score + earnings_score
        if total_score <= 0:
            continue

        volume_ratio = c.technical.volume_ratio if c.technical else 0.0
        reasons = list(c.technical.reasons) if c.technical else []
        if c.earnings:
            reasons += c.earnings.reasons

        scored.append(
            RankedCandidate(
                code=c.code,
                name=c.name,
                total_score=total_score,
                technical_score=technical_score,
                earnings_score=earnings_score,
                volume_ratio=volume_ratio,
                entry_price=round(c.close * price_multiplier, 1),
                reasons=reasons,
                side=side,
                day_open=c.open,
                day_high=c.high,
                day_low=c.low,
                day_close=c.close,
                day_volume=c.volume,
            )
        )

    scored.sort(key=lambda r: (-r.total_score, -r.volume_ratio))
    return scored[:top_n]
