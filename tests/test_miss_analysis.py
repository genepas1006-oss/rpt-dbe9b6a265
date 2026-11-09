"""analysis.miss_analysis のテスト（2026-11-09承認の手計算ケース＋境界）。"""

from analysis.miss_analysis import build_suggestion, classify_miss, count_causes


def _buy(open_, market, daily=0.01, volume=1.0, pred_close=1000.0):
    return classify_miss("buy", pred_close, daily, volume, open_, market)


# ---------------- 承認済みの手計算ケース（買い） ----------------
def test_case1_market_down_and_gap_down():
    # 日経平均-1.5%、始値990（予測日終値1000比-1.0%）、予測時 +1%・1.2倍
    assert _buy(990, -0.015, daily=0.01, volume=1.2) == ["地合い悪化", "寄りで下落"]


def test_case2_surge_reaction():
    # 日経平均+0.2%、始値999（-0.1%）、予測時 +4%・1.1倍 → 急騰後の反動のみ
    assert _buy(999, 0.002, daily=0.04, volume=1.1) == ["急騰後の反動"]


def test_case3_other():
    # 日経平均0.0%、始値1001（+0.1%）、予測時 +1%・1.0倍 → その他
    assert _buy(1001, 0.0, daily=0.01, volume=1.0) == ["その他"]


# ---------------- 境界（買い） ----------------
def test_market_boundary_minus_one_percent_is_included():
    assert "地合い悪化" in _buy(1000, -0.01)
    assert "地合い悪化" not in _buy(1000, -0.0099)


def test_gap_boundary_half_percent_is_included():
    # (995-1000)/1000 = -0.5% ちょうど
    assert "寄りで下落" in _buy(995, 0.0)
    assert "寄りで下落" not in _buy(995.1, 0.0)


def test_surge_boundaries_return_and_volume():
    assert "急騰後の反動" in _buy(1000, 0.0, daily=0.03, volume=1.0)
    assert "急騰後の反動" not in _buy(1000, 0.0, daily=0.0299, volume=1.0)
    assert "急騰後の反動" in _buy(1000, 0.0, daily=0.0, volume=3.0)
    assert "急騰後の反動" not in _buy(1000, 0.0, daily=0.0, volume=2.99)


def test_buy_ignores_opposite_direction_moves():
    # 買いで日経平均+2%、始値+1%、急落でも、タグは付かない
    assert _buy(1010, 0.02, daily=-0.05, volume=1.0) == ["その他"]


def test_all_three_tags_in_fixed_order():
    assert _buy(990, -0.02, daily=0.05, volume=4.0) == ["地合い悪化", "寄りで下落", "急騰後の反動"]


# ---------------- 売り（向きを反転） ----------------
def _sell(open_, market, daily=-0.01, volume=1.0, pred_close=1000.0):
    return classify_miss("sell", pred_close, daily, volume, open_, market)


def test_sell_mirrored_tags():
    assert _sell(1010, 0.015, daily=-0.04, volume=1.2) == ["地合い上昇", "寄りで上昇", "急落後の反発"]


def test_sell_boundaries():
    assert "地合い上昇" in _sell(1000, 0.01) and "地合い上昇" not in _sell(1000, 0.0099)
    assert "寄りで上昇" in _sell(1005, 0.0) and "寄りで上昇" not in _sell(1004.9, 0.0)
    assert "急落後の反発" in _sell(1000, 0.0, daily=-0.03) and "急落後の反発" not in _sell(1000, 0.0, daily=-0.0299)
    assert "急落後の反発" in _sell(1000, 0.0, daily=0.0, volume=3.0)


def test_sell_ignores_opposite_direction_moves():
    assert _sell(990, -0.02, daily=0.05, volume=1.0) == ["その他"]


# ---------------- データ欠損 ----------------
def test_missing_open_and_market_without_other_match_is_no_data():
    assert classify_miss("buy", 1000.0, 0.01, 1.0, None, None) == ["データ不足"]
    assert classify_miss("buy", 1000.0, 0.01, 1.0, 1001.0, None) == ["データ不足"]
    assert classify_miss("buy", 1000.0, 0.01, 1.0, None, 0.0) == ["データ不足"]


def test_missing_values_still_tag_what_is_known():
    assert classify_miss("buy", 1000.0, 0.05, 1.0, None, None) == ["急騰後の反動"]
    assert classify_miss("buy", 1000.0, 0.01, 1.0, None, -0.02) == ["地合い悪化"]


def test_zero_pred_close_does_not_crash():
    assert classify_miss("buy", 0.0, 0.01, 1.0, 990.0, 0.0) == ["その他"]  # 始値比は計算せず、他の値は揃っている


# ---------------- 集計・示唆 ----------------
def test_count_causes_sorted_by_count_then_name():
    lists = [["地合い悪化", "寄りで下落"], ["地合い悪化"], ["その他"], ["寄りで下落"]]
    assert count_causes(lists) == [("地合い悪化", 2), ("寄りで下落", 2), ("その他", 1)]


def test_suggestion_names_top_cause_with_count_and_ratio():
    lists = [["地合い悪化"]] * 6 + [["寄りで下落"]] * 3 + [["その他"]] * 3  # 12件
    text = build_suggestion(lists)
    assert "不的中12件のうち、「地合い悪化」が最多（6件・50%）です。" in text
    assert "地合い（日経平均の向き）の確認が検討候補です。" in text
    assert "参考程度" not in text  # 10件以上


def test_suggestion_small_sample_note():
    assert "（件数が少ないため参考程度です。）" in build_suggestion([["その他"]] * 9)
    assert "参考程度" not in build_suggestion([["その他"]] * 10)


def test_suggestion_empty_and_no_assertive_wording():
    assert build_suggestion([]) == ""
    for tag in ("地合い悪化", "地合い上昇", "寄りで下落", "寄りで上昇", "急騰後の反動", "急落後の反発", "その他", "データ不足"):
        text = build_suggestion([[tag]])
        assert not any(w in text for w in ("必ず", "保証", "確実"))
        assert "検討候補" in text or "確認が必要" in text
