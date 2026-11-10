"""テスト枠（値動き重視）の候補の絞り込み。承認済み（2026-11-10）。試験運用で、効果は未確認。

当日値幅率 = (当日の高値 - 安値) ÷ 終値（高値と安値が同じ、または終値が0以下なら0）。
全候補を当日値幅率の高い順に並べ、上位 k 件（k = 全体件数 × 30% の切り上げ）を対象にする。
k 番目と同じ値の銘柄も含める。絞り込み後は、現行と同じスコア・順位の決め方で買い5件・売り5件を選ぶ。
"""

import math

from analysis.scoring import CandidateInput

TOP_RATIO = 0.3


def day_range_ratio(high: float, low: float, close: float) -> float:
    if close <= 0 or high <= low:
        return 0.0
    return (high - low) / close


def select_volatile_pool(candidates: list[CandidateInput], top_ratio: float = TOP_RATIO) -> list[CandidateInput]:
    if not candidates:
        return []
    values = [round(day_range_ratio(c.high, c.low, c.close), 12) for c in candidates]
    k = max(1, math.ceil(len(candidates) * top_ratio - 1e-9))
    threshold = sorted(values, reverse=True)[k - 1]
    return [c for c, v in zip(candidates, values) if v >= threshold]
