"""候補カードの説明・勝敗の内訳・含み益損のテスト（2026-11-11承認の手計算ケース）。"""

import pytest

from analysis.card_explain import (
    close_position,
    reason_sentence,
    relative_strength_text,
    round_level_text,
    score_rows,
)
from tracking.payoff import compute_payoff, excursions


# --- A. スコア内訳 ---
def _pts(rows):
    return [r.points for r in rows]


def test_a1_buy_breakdown():
    rows = score_rows("buy", 1.72, 0.018, 0.85, 0)
    assert _pts(rows) == [1, 1, 1, 0]
    assert sum(_pts(rows)) == 3
    assert rows[2].actual == "0.85（高値圏）"
    assert rows[0].to_md() == "出来高 | 平均の1.72倍 | 1.5倍以上で+1点・2倍以上で+2点 | +1点"


def test_a2_volume_boundaries():
    assert score_rows("buy", 1.5, 0, 0.5, 0)[0].points == 1
    assert score_rows("buy", 2.0, 0, 0.5, 0)[0].points == 2


def test_a3_return_and_position_boundaries():
    rows = score_rows("buy", 1.0, 0.03, 0.8, 0)
    assert rows[1].points == 2 and rows[2].points == 1


def test_a4_sell_breakdown():
    rows = score_rows("sell", 1.2, -0.034, 0.15, 0)
    assert _pts(rows) == [0, 2, 1, 0]
    assert rows[2].actual == "0.15（安値圏）"


def test_a5_flat_day_close_position():
    assert close_position(100, 100, 100) == 0.5
    assert close_position(1030, 990, 1018) == pytest.approx(0.7)


def test_earnings_points_and_sentence():
    rows = score_rows("buy", 1.72, 0.018, 0.85, 2)
    assert sum(_pts(rows)) == 5
    text = reason_sentence("buy", rows)
    assert "5点（7点満点）" in text and "決算パターン 該当あり" in text and "保証ではありません" in text
    assert reason_sentence("buy", score_rows("buy", 1.0, 0.0, 0.5, 0)) == ""


# --- B. 最大含み益・最大含み損 ---
def test_b1_buy_excursions():
    mfe, mae = excursions("buy", 1000, 1030, 990)
    assert mfe == pytest.approx(0.03) and mae == pytest.approx(0.01)


def test_b2_sell_excursions():
    mfe, mae = excursions("sell", 2000, 2020, 1950)
    assert mfe == pytest.approx(0.025) and mae == pytest.approx(0.01)


def test_b3_gap_fill_excursions():
    mfe, mae = excursions("buy", 980, 995, 975)
    assert mfe == pytest.approx(15 / 980) and round(mfe * 100, 2) == 1.53
    assert round(mae * 100, 2) == 0.51


def test_b4_mae_never_negative():
    assert excursions("buy", 1000, 1010, 1000)[1] == 0.0


# --- C. 勝率・平均利益・平均損失・損益比 ---
def test_c1_payoff():
    s = compute_payoff([0.02, -0.01, 0.005, -0.015, 0.01])
    assert s.win_rate == pytest.approx(0.6)
    assert s.avg_win == pytest.approx(0.035 / 3)
    assert s.avg_loss == pytest.approx(0.0125)
    assert s.payoff_ratio == pytest.approx(0.9333, abs=1e-4)
    assert s.avg_return == pytest.approx(0.002)


def test_c2_all_wins():
    s = compute_payoff([0.01, 0.02])
    assert s.avg_loss is None and s.payoff_ratio is None and s.win_rate == 1.0


def test_c3_all_losses():
    s = compute_payoff([-0.01, -0.03])
    assert s.avg_win is None and s.payoff_ratio == 0.0


def test_c4_zero_counts_as_loss():
    s = compute_payoff([0.01, 0.0])
    assert s.win_rate == pytest.approx(0.5) and s.avg_loss == 0.0 and s.payoff_ratio is None


def test_c5_empty():
    assert compute_payoff([]) is None


# --- D. 気をつける点 ---
def test_d1_stronger_than_index():
    assert relative_strength_text(0.02, 0.005) == "日経平均+0.5%より1.5ポイント強い動き（銘柄固有の動きが大きい）"


def test_d2_same_as_index_and_weaker():
    assert "ほぼ同じ動き" in relative_strength_text(0.006, 0.005)
    assert "ほぼ同じ動き" in relative_strength_text(0.010, 0.005)  # ちょうど0.5ポイント差
    assert "ポイント弱い" in relative_strength_text(-0.01, 0.005)
    assert relative_strength_text(0.01, None) == ""


def test_d3_round_levels():
    assert round_level_text(4870) == "上の節目5,000円（大きな節目）まであと2.7%、下の節目4,500円から8.2%上"
    assert round_level_text(4500) == "終値はちょうど4,500円の節目"
    assert round_level_text(850).startswith("上の節目900円まであと5.9%")
    assert round_level_text(7300).startswith("上の節目8,000円まであと9.6%")


def test_payoff_lines_text():
    from report.generate_report import _payoff_lines

    lines = _payoff_lines(compute_payoff([0.02, -0.01, 0.005, -0.015, 0.01]))
    assert lines[0] == "- 平均利益（勝った場合のリターン）: +1.17%（3件）"
    assert lines[1] == "- 平均損失（負けた場合のリターン）: -1.25%（2件）"
    assert lines[2] == "- 損益比（平均利益÷平均損失）: 0.93"
    assert lines[3] == "- 1件あたりの平均リターン: +0.20%"
    wins_only = _payoff_lines(compute_payoff([0.01, 0.02]))
    assert wins_only[1].endswith("なし（0件）") and wins_only[2].endswith("算出不可")
    assert _payoff_lines(None) == []
