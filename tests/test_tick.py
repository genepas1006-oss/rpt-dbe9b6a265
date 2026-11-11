"""呼値に丸めた参考指値のテスト（2026-11-11承認の手計算ケース）。"""

from decimal import Decimal

import pytest

from analysis.scoring import CandidateInput, rank_candidates
from analysis.tick import limit_price, round_to_tick, tick_size
from analysis.technical import TechnicalScore


@pytest.mark.parametrize(
    "side, close, code, expected",
    [
        ("buy", 850.0, "1111", 845.8),  # 845.75 → 0.1刻み、ちょうど中間は切り上げ
        ("buy", 2160.0, "1111", 2149.0),  # 2,149.2 → 0.5刻み
        ("buy", 1350.0, "1111", 1343.5),  # 1,343.25 → 中間は切り上げ
        ("sell", 3858.9, "1111", 3878.0),  # 3,878.1945 → 1円刻み
        ("buy", 7300.0, "1111", 7264.0),  # 7,263.5 → 中間は切り上げ
        ("sell", 12300.0, "1111", 12360.0),  # 12,361.5 → 5円刻み
        ("buy", 2400.0, "7004", 2388.0),  # その他の銘柄（日立造船）: 1円刻み
        ("buy", 4010.0, "7004", 3990.0),  # その他の銘柄: 3,989.95 → 5円刻み
    ],
)
def test_limit_price(side, close, code, expected):
    assert limit_price(close, side, code) == pytest.approx(expected)


def test_tick_band_boundaries():
    assert tick_size(3000) == Decimal("0.5")  # 「以下」を含む
    assert tick_size(3000.5) == Decimal("1")
    assert tick_size(1000) == Decimal("0.1")
    assert tick_size(1000.1) == Decimal("0.5")
    assert tick_size(5000, "6103") == Decimal("5")
    assert tick_size(5001, "6103") == Decimal("10")


def test_round_to_tick_direct():
    assert round_to_tick(1343.25) == 1343.5
    assert round_to_tick(1343.2) == 1343.0
    assert round_to_tick(845.74) == 845.7


def test_rank_candidates_uses_tick_rounded_limit():
    tech = TechnicalScore(2.0, 0.03, 0.9, 2, 2, 1, 5, ["x"])
    c = CandidateInput(code="1111", name="a", close=2160.0, technical=tech, earnings=None)
    [r] = rank_candidates([c], side="buy")
    assert r.entry_price == 2149.0
    [r] = rank_candidates([CandidateInput(code="1111", name="a", close=3858.9, technical=tech, earnings=None)], side="sell")
    assert r.entry_price == 3878.0
