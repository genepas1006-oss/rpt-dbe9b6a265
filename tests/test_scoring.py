"""analysis.scoring のテスト。

承認済みのサンプルデータ手計算（2026-08-21合意分、6銘柄ケース）をテストケース化する。
"""

from analysis.earnings import EarningsScore
from analysis.scoring import CandidateInput, rank_candidates
from analysis.technical import TechnicalScore


def _tech(score: int, volume_ratio: float) -> TechnicalScore:
    return TechnicalScore(
        volume_ratio=volume_ratio,
        daily_return=0.0,
        close_position=0.0,
        volume_points=0,
        return_points=0,
        close_position_points=0,
        technical_score=score,
    )


def _earn(score: int) -> EarningsScore:
    return EarningsScore(
        days_since_earnings=0,
        in_reaction_window=True,
        post_earnings_drift_avg=None,
        earnings_score=score,
    )


def test_six_stock_ranking_sample():
    candidates = [
        CandidateInput("AAA", "銘柄AAA", 3000, _tech(5, 2.25), _earn(2)),
        CandidateInput("BBB", "銘柄BBB", 1500, _tech(3, 1.8), _earn(2)),
        CandidateInput("CCC", "銘柄CCC", 800, _tech(3, 1.6), _earn(1)),
        CandidateInput("DDD", "銘柄DDD", 1200, _tech(2, 2.1), _earn(2)),
        CandidateInput("EEE", "銘柄EEE", 500, _tech(1, 1.2), _earn(0)),
        CandidateInput("FFF", "銘柄FFF", 2000, _tech(0, 1.0), _earn(0)),
    ]

    result = rank_candidates(candidates)

    assert [r.code for r in result] == ["AAA", "BBB", "DDD", "CCC", "EEE"]

    by_code = {r.code: r for r in result}
    assert by_code["AAA"].total_score == 7
    assert by_code["AAA"].entry_price == 2985.0
    assert by_code["BBB"].total_score == 5
    assert by_code["BBB"].entry_price == 1492.5
    assert by_code["DDD"].total_score == 4
    assert by_code["DDD"].entry_price == 1194.0
    assert by_code["CCC"].total_score == 4
    assert by_code["CCC"].entry_price == 796.0
    assert by_code["EEE"].total_score == 1
    assert by_code["EEE"].entry_price == 497.5


def test_zero_score_candidates_are_excluded():
    candidates = [
        CandidateInput("ZZZ", "銘柄ZZZ", 1000, _tech(0, 1.0), _earn(0)),
        CandidateInput("YYY", "銘柄YYY", 1000, None, None),
    ]

    result = rank_candidates(candidates)

    assert result == []


def test_fewer_than_top_n_qualified_returns_fewer():
    candidates = [
        CandidateInput("AAA", "銘柄AAA", 1000, _tech(1, 1.0), _earn(0)),
    ]

    result = rank_candidates(candidates)

    assert len(result) == 1


def test_sell_side_entry_price_is_above_close():
    candidates = [
        CandidateInput("AAA", "銘柄AAA", 1000, _tech(5, 2.25), _earn(2)),
    ]

    result = rank_candidates(candidates, side="sell")

    assert len(result) == 1
    assert result[0].side == "sell"
    assert result[0].entry_price == 1005.0
