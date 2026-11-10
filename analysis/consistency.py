"""買い候補と売り候補の方向の矛盾を取り除く。承認済み設計（2026-11-10）。

ルール1: 買い候補は当日の騰落率が0%以上、売り候補は0%以下の銘柄に限る（騰落率が不明な銘柄は載せない）。
ルール2: 両方に該当する銘柄（騰落率がちょうど0%）は、総合スコアが高い側だけに残す。同点なら両方から外す。
背景: 出来高の加点は上げ下げを問わず、各条件が独立に足し算されるため、同じ銘柄が買いにも売りにも載ることがあった。
"""

from analysis.scoring import CandidateInput


def _total(c: CandidateInput) -> int:
    return (c.technical.technical_score if c.technical else 0) + (c.earnings.earnings_score if c.earnings else 0)


def resolve_direction_conflicts(
    buy_candidates: list[CandidateInput], sell_candidates: list[CandidateInput]
) -> tuple[list[CandidateInput], list[CandidateInput]]:
    buy = {c.code: c for c in buy_candidates if c.technical is not None and c.technical.daily_return >= 0}
    sell = {c.code: c for c in sell_candidates if c.technical is not None and c.technical.daily_return <= 0}
    for code in set(buy) & set(sell):
        b, s = _total(buy[code]), _total(sell[code])
        if b > s:
            del sell[code]
        elif s > b:
            del buy[code]
        else:
            del buy[code]
            del sell[code]
    return (
        [c for c in buy_candidates if c.code in buy],
        [c for c in sell_candidates if c.code in sell],
    )
