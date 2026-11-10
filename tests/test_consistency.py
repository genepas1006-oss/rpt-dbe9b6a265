"""買いと売りの方向の矛盾の排除。承認済みの手計算ケース S1〜S3（2026-11-10）。"""

from analysis.consistency import resolve_direction_conflicts
from analysis.earnings import EarningsScore
from analysis.scoring import CandidateInput, rank_candidates
from analysis.technical import TechnicalScore


def _c(code, daily_return, tech_score, earn_score=0, no_tech=False):
    tech = None if no_tech else TechnicalScore(volume_ratio=2.0, daily_return=daily_return, close_position=0.5,
                                               volume_points=0, return_points=0, close_position_points=0,
                                               technical_score=tech_score)
    earn = EarningsScore(1, True, 0.0, earn_score) if earn_score else None
    return CandidateInput(code=code, name=code, close=1000.0, technical=tech, earnings=earn)


def _both(code, ret, buy_total, sell_total):
    # 買いは技術点＋決算点、売りも同様。総合スコア（合計）だけを指定する
    return _c(code, ret, buy_total), _c(code, ret, sell_total)


def test_s1_kikkoman_only_sell_remains():
    buy = [_c("2801", -0.1063, 3, 2)]   # 買いスコア 3+2=5
    sell = [_c("2801", -0.1063, 4)]     # 売りスコア 4
    b, s = resolve_direction_conflicts(buy, sell)
    assert b == [] and [c.code for c in s] == ["2801"]
    assert [r.code for r in rank_candidates(s, side="sell")] == ["2801"]


def test_s2_zero_return_resolved_by_higher_score():
    for bt, st, exp_buy, exp_sell in ((3, 3, [], []), (4, 3, ["Z"], []), (2, 3, [], ["Z"])):
        b, s = resolve_direction_conflicts([_c("Z", 0.0, bt)], [_c("Z", 0.0, st)])
        assert [c.code for c in b] == exp_buy and [c.code for c in s] == exp_sell


def test_s3_boundaries():
    b, s = resolve_direction_conflicts([_c("P", 0.005, 3)], [_c("P", 0.005, 3)])
    assert [c.code for c in b] == ["P"] and s == []          # +0.5% → 買いは対象、売りは対象外
    b, s = resolve_direction_conflicts([_c("M", -0.0001, 3)], [_c("M", -0.0001, 3)])
    assert b == [] and [c.code for c in s] == ["M"]          # -0.01% → 買いは対象外、売りは対象


def test_unknown_return_and_input_order_are_handled():
    b, s = resolve_direction_conflicts([_c("N", 0.0, 3, no_tech=True), _c("A", 0.01, 3), _c("B", 0.02, 2)],
                                       [_c("N", 0.0, 3, no_tech=True), _c("C", -0.01, 3)])
    assert [c.code for c in b] == ["A", "B"] and [c.code for c in s] == ["C"]  # 騰落率が不明な銘柄は載せない。順序は保たれる


def test_no_stock_is_in_both_lists():
    import random

    random.seed(1)
    buy = [_c(f"S{i}", random.uniform(-0.1, 0.1), random.randint(0, 5)) for i in range(200)]
    sell = [_c(f"S{i}", b.technical.daily_return, random.randint(0, 5)) for i, b in enumerate(buy)]
    b, s = resolve_direction_conflicts(buy, sell)
    assert not ({c.code for c in b} & {c.code for c in s})
