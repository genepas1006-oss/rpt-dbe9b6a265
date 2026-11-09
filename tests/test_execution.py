"""backtest.execution のテスト（約定方法の比較。手計算ケース）。"""

import pytest

from backtest.engine import apply_variant, baseline, reversal, summarize
from backtest.execution import (
    apply_rule,
    close_to_close_rule,
    default_rules,
    limit_rule,
    open_close_rule,
    open_hold_rule,
    open_tp_sl_rule,
)
from backtest.report import build_execution_markdown
from backtest.engine import Metrics
from data_sources.base import DailyBar
from tests.test_backtest import DATES, T, _days

from datetime import date

D = date(2026, 11, 6)


def _bar(o, h, l, c):  # noqa: E741
    return DailyBar(D, o, h, l, c, 1)


# 翌営業日: 始値990 高値1010 安値985 終値1005 / 予測日終値1000
DAY0 = _bar(990, 1010, 985, 1005)


# ---------------- 1本ずつの手計算 ----------------
def test_open_close_buy_and_sell():
    entry, r = open_close_rule().evaluate("buy", 1000.0, [DAY0])
    assert entry == 990 and r.filled and r.is_win
    assert r.result_return == pytest.approx(15 / 990)  # +1.515%
    _, rs = open_close_rule().evaluate("sell", 1000.0, [DAY0])
    assert rs.result_return == pytest.approx(-15 / 990) and rs.is_win is False


def test_open_hold_exit_is_nth_bar_close_and_needs_enough_bars():
    day1 = _bar(1005, 1030, 1000, 1020)
    day2 = _bar(1020, 1040, 1010, 1050)
    _, r2 = open_hold_rule(2).evaluate("buy", 1000.0, [DAY0, day1, day2])
    assert r2.result_return == pytest.approx((1020 - 990) / 990)  # 2日目の終値で決済 +3.03%
    _, r3 = open_hold_rule(3).evaluate("buy", 1000.0, [DAY0, day1, day2])
    assert r3.result_return == pytest.approx((1050 - 990) / 990)
    _, rs = open_hold_rule(2).evaluate("sell", 1000.0, [DAY0, day1])
    assert rs.result_return == pytest.approx(-30 / 990)
    assert open_hold_rule(2).evaluate("buy", 1000.0, [DAY0]) is None  # 足が足りない → 取引なし
    assert open_hold_rule(3).evaluate("buy", 1000.0, [DAY0, day1]) is None


def test_tp_sl_buy_take_profit_only():
    # 利確 990*1.01=999.9 / 損切り 990*0.99=980.1。高値1010>=999.9、安値985>980.1 → 利確 +1.0%
    _, r = open_tp_sl_rule(0.01, 0.01).evaluate("buy", 1000.0, [DAY0])
    assert r.result_return == pytest.approx(0.01) and r.is_win


def test_tp_sl_buy_both_touched_assumes_stop_first():
    both = _bar(990, 1010, 975, 1005)  # 安値975<=980.1 かつ 高値1010>=999.9
    _, r = open_tp_sl_rule(0.01, 0.01).evaluate("buy", 1000.0, [both])
    assert r.result_return == pytest.approx(-0.01) and r.is_win is False


def test_tp_sl_buy_neither_exits_at_close():
    quiet = _bar(990, 995, 985, 993)
    _, r = open_tp_sl_rule(0.01, 0.01).evaluate("buy", 1000.0, [quiet])
    assert r.result_return == pytest.approx(3 / 990)  # +0.303%


def test_tp_sl_sell_mirrored():
    # 売り: 利確 990*0.99=980.1 / 損切り 990*1.01=999.9
    tp_only = _bar(990, 995, 975, 985)
    _, r = open_tp_sl_rule(0.01, 0.01).evaluate("sell", 1000.0, [tp_only])
    assert r.result_return == pytest.approx(0.01)
    both = _bar(990, 1010, 975, 985)
    _, r2 = open_tp_sl_rule(0.01, 0.01).evaluate("sell", 1000.0, [both])
    assert r2.result_return == pytest.approx(-0.01)
    quiet = _bar(990, 995, 985, 988)
    _, r3 = open_tp_sl_rule(0.01, 0.01).evaluate("sell", 1000.0, [quiet])
    assert r3.result_return == pytest.approx(2 / 990)


def test_tp_sl_asymmetric_parameters():
    # 利確2% 損切り1%: 利確 1009.8。高値1010>=1009.8 → +2.0%
    _, r = open_tp_sl_rule(0.02, 0.01).evaluate("buy", 1000.0, [DAY0])
    assert r.result_return == pytest.approx(0.02)


def test_close_to_close_reference():
    entry, r = close_to_close_rule().evaluate("buy", 1000.0, [DAY0])
    assert entry == 1000.0 and r.result_return == pytest.approx(0.005)
    _, rs = close_to_close_rule().evaluate("sell", 1000.0, [DAY0])
    assert rs.result_return == pytest.approx(-0.005)


def test_limit_rules_by_discount():
    # d=0.5%: 指値 995.0 → 安値985<=995 で約定、(1005-995)/995
    e, r = limit_rule(0.005).evaluate("buy", 1000.0, [DAY0])
    assert e == 995.0 and r.result_return == pytest.approx(10 / 995)
    # d=0: 指値 = 終値1000 → 約定、(1005-1000)/1000 = 引け→引けと同じ
    e0, r0 = limit_rule(0.0).evaluate("buy", 1000.0, [DAY0])
    assert e0 == 1000.0 and r0.result_return == pytest.approx(0.005)
    # d=1%: 指値 990.0 → 安値985<=990 で約定、(1005-990)/990
    e1, r1 = limit_rule(0.01).evaluate("buy", 1000.0, [DAY0])
    assert e1 == 990.0 and r1.result_return == pytest.approx(15 / 990)
    # 約定しない例: 安値が指値に届かない
    _, miss = limit_rule(0.01).evaluate("buy", 1000.0, [_bar(995, 1010, 992, 1005)])
    assert miss.filled is False and miss.result_return is None


def test_zero_open_is_skipped():
    assert open_close_rule().evaluate("buy", 1000.0, [_bar(0, 1, 0, 1)]) is None


# ---------------- 合成データでの手計算（日 T: A=上昇+出来高急増, C=下落+出来高急増, B=無変化） ----------------
def _on_day(trades):
    return [t for t in trades if t.day == DATES[T]]


def test_open_close_top1_hand_calc():
    tr = {t.side: t for t in _on_day(apply_rule(_days(), baseline(), open_close_rule(), "top", top_n=1))}
    # 買いA: 始値104→終値106 / 売りC: 始値96→終値94
    assert tr["buy"].code == "A" and tr["buy"].entry_price == 104
    assert tr["buy"].result_return == pytest.approx((106 - 104) / 104)  # +1.92%
    assert tr["sell"].code == "C" and tr["sell"].entry_price == 96
    assert tr["sell"].result_return == pytest.approx((96 - 94) / 96)  # +2.08%


def test_select_all_includes_zero_score_candidates():
    top = _on_day(apply_rule(_days(), baseline(), open_close_rule(), "top", top_n=5))
    allc = _on_day(apply_rule(_days(), baseline(), open_close_rule(), "all"))
    assert {(t.side, t.code) for t in top} == {("buy", "A"), ("buy", "C"), ("sell", "C"), ("sell", "A")}
    assert {(t.side, t.code) for t in allc} == {(s, c) for s in ("buy", "sell") for c in "ABC"}  # Bも含む
    b = next(t for t in allc if t.side == "buy" and t.code == "B")
    assert b.result_return == 0.0 and b.is_win is False  # Bは翌日も無変化


def test_hold_exit_index_matches_days_with_changed_future_bar():
    # Aの27番目(=3日目)の終値だけ120にする: 2日目決済は変わらず、3日目決済は変わる
    days = _days(after={27: (106, 121, 106, 120, 100)})
    one = lambda rule: next(  # noqa: E731
        t for t in _on_day(apply_rule(days, baseline(), rule, "top", top_n=1)) if t.side == "buy"
    )
    assert one(open_hold_rule(2)).result_return == pytest.approx((106 - 104) / 104)
    assert one(open_hold_rule(3)).result_return == pytest.approx((120 - 104) / 104)  # +15.38%


def test_tp_sl_on_synthetic_data():
    # A翌日: 始値104 高値107 安値103。利確1% 105.04 に届き、損切り1% 102.96 には届かない → +1.0%
    buy = lambda days: next(  # noqa: E731
        t for t in _on_day(apply_rule(days, baseline(), open_tp_sl_rule(0.01, 0.01), "top", top_n=1)) if t.side == "buy"
    )
    assert buy(_days()).result_return == pytest.approx(0.01)
    # 安値を102にすると損切り(102.96)にも届く → 保守的に損切り -1.0%
    assert buy(_days(after={25: (104, 107, 102, 106, 100)})).result_return == pytest.approx(-0.01)


def test_close_to_close_on_synthetic_data():
    tr = {t.side: t for t in _on_day(apply_rule(_days(), baseline(), close_to_close_rule(), "top", top_n=1))}
    assert tr["buy"].entry_price == 104 and tr["buy"].result_return == pytest.approx((106 - 104) / 104)
    assert tr["sell"].entry_price == 96 and tr["sell"].result_return == pytest.approx((96 - 94) / 96)


def test_reversal_with_market_open_rule():
    tr = {t.side: t for t in _on_day(apply_rule(_days(), reversal(), open_close_rule(), "top", top_n=1))}
    # 逆張り: 買いはC（下落+出来高急増）、売りはA。買いC: 始値96→終値94 = -2.08%
    assert tr["buy"].code == "C" and tr["buy"].result_return == pytest.approx((94 - 96) / 96)
    assert tr["sell"].code == "A" and tr["sell"].result_return == pytest.approx((104 - 106) / 104)


# ---------------- 整合性・先読みなし ----------------
def test_limit_half_percent_rule_matches_existing_apply_variant_exactly():
    days = _days()
    key = lambda t: (t.day, t.side, t.code, t.entry_price, t.filled, t.result_return)  # noqa: E731
    new = sorted(map(key, apply_rule(days, baseline(), limit_rule(0.005), "top", top_n=5)), key=repr)
    old = sorted(map(key, apply_variant(days, baseline(), top_n=5, entry_discount=0.005)), key=repr)
    assert new == old and len(new) > 0


def test_selection_ignores_future_bars_but_results_use_them():
    base = _days()
    changed = _days(after={26: (1, 9999, 1, 9999, 10**9), 27: (5, 5, 5, 5, 5)})
    sel = lambda days: [  # noqa: E731
        (t.side, t.code) for t in apply_rule(days, baseline(), open_hold_rule(3), "top", top_n=5) if t.day == DATES[T]
    ]
    assert sel(base) == sel(changed)
    res = lambda days: [  # noqa: E731
        t.result_return for t in apply_rule(days, baseline(), open_hold_rule(3), "top", top_n=5) if t.day == DATES[T]
    ]
    assert res(base) != res(changed)


def test_future_bars_are_the_next_three_bars_and_excluded_from_equality():
    cand = next(c for c in next(d for d in _days() if d.day == DATES[T]).candidates if c.code == "A")
    assert [b.trade_date for b in cand.future_bars] == DATES[26:29]
    assert cand.next_bar.trade_date == DATES[25]


def test_invalid_select_raises():
    with pytest.raises(ValueError):
        apply_rule(_days(), baseline(), open_close_rule(), "random")


def test_hold_rules_drop_trades_without_enough_future_bars():
    days = _days()
    n_close = len(apply_rule(days, baseline(), open_close_rule(), "all"))
    n_hold3 = len(apply_rule(days, baseline(), open_hold_rule(3), "all"))
    assert n_hold3 < n_close  # 末尾付近は3日先まで足がなく、取引から除かれる


def test_default_rules_are_unique_and_cover_variations():
    names = [r.name for r in default_rules()]
    assert len(names) == len(set(names)) == 12
    assert {"limit0.5%", "open→close", "open→2日後close", "open+TP1%/SL1%", "close→close(参考)"} <= set(names)


# ---------------- 集計との連携・表 ----------------
def test_summarize_works_on_rule_trades():
    m = summarize(apply_rule(_days(), baseline(), open_close_rule(), "top", top_n=1), "buy")
    assert m.fill_rate == 1.0  # 成行は必ず約定


def _m(avg):
    return Metrics(10, 10, 1.0, 5, 0.5, avg, 0.01, -0.01, 1.0)


def test_execution_markdown_rows_and_double_circle():
    results = {
        "top / open→close": {p: {"buy": _m(0.002), "sell": _m(-0.001)} for p in ("train", "valid")},
        "all / open→close": {p: {"buy": _m(-0.001), "sell": _m(-0.001)} for p in ("train", "valid")},
    }
    md = build_execution_markdown(results, {"train": "前半", "valid": "後半"})
    assert "## 買い / 前半" in md and "## 売り / 後半" in md
    top_buy = [l for l in md.splitlines() if l.startswith("| top / open→close |")]
    assert len(top_buy) == 4 and top_buy[0].rstrip().endswith("◎ |")  # 買いは両期間プラス
    assert top_buy[2].rstrip().endswith("|  |")  # 売りはマイナス → ◎なし
    assert "保証するものではありません" in md


def test_tp_sl_touching_exactly_counts_as_hit():
    entry = 1000.0
    tp_price, sl_price = entry * (1 + 0.01), entry * (1 - 0.01)
    # 買い: 高値が利確価格ちょうど → 利確
    _, r = open_tp_sl_rule(0.01, 0.01).evaluate("buy", entry, [_bar(entry, tp_price, 995, 998)])
    assert r.result_return == pytest.approx(0.01)
    # 買い: 安値が損切り価格ちょうど → 損切り
    _, r2 = open_tp_sl_rule(0.01, 0.01).evaluate("buy", entry, [_bar(entry, 1005, sl_price, 1002)])
    assert r2.result_return == pytest.approx(-0.01)
    # 売り: 安値が利確価格ちょうど、高値が損切り価格ちょうど
    s_tp, s_sl = entry * (1 - 0.01), entry * (1 + 0.01)
    _, r3 = open_tp_sl_rule(0.01, 0.01).evaluate("sell", entry, [_bar(entry, 1005, s_tp, 1002)])
    assert r3.result_return == pytest.approx(0.01)
    _, r4 = open_tp_sl_rule(0.01, 0.01).evaluate("sell", entry, [_bar(entry, s_sl, 995, 998)])
    assert r4.result_return == pytest.approx(-0.01)
    # 届かない（1銭手前）なら終値で決済
    _, r5 = open_tp_sl_rule(0.01, 0.01).evaluate("buy", entry, [_bar(entry, tp_price - 0.01, sl_price + 0.01, 1003)])
    assert r5.result_return == pytest.approx(0.003)


# ---------------- 費用（2026-11-09承認） ----------------
from backtest.engine import Trade  # noqa: E402


def _tr(side, o, c):
    entry, r = open_close_rule().evaluate(side, o, [_bar(o, max(o, c), min(o, c), c)])
    return r.result_return


def _one_day(o, c, cost):
    """始値o→終値c の1銘柄・1日だけのデータで、買い・売りの取引を {side: Trade} で返す。"""
    from analysis.scoring import CandidateInput
    from analysis.technical import TechnicalScore
    from backtest.engine import DayCandidate, Features, TradingDay

    tech = TechnicalScore(2.0, 0.0, 0.5, 5, 0, 0, 5, [])
    ci = CandidateInput("X", "X", 1000.0, tech, None)
    bar = DailyBar(D, o, max(o, c), min(o, c), c, 1)
    day = TradingDay(D, D, [DayCandidate("X", Features(1, None, None), ci, ci, bar)])
    return {t.side: t for t in apply_rule([day], baseline(), open_close_rule(), "all", cost=cost)}


def test_cost_hand_calc_examples():
    # 例1: 買い 990→1005 +1.515% → 費用0.1%で +1.415%（勝ち）
    t = _one_day(990, 1005, 0.001)
    assert t["buy"].result_return == pytest.approx(15 / 990 - 0.001) and t["buy"].is_win is True
    # 例2: 売り 990→1005 -1.515% → -1.615%（負け）
    assert t["sell"].result_return == pytest.approx(-15 / 990 - 0.001) and t["sell"].is_win is False
    # 例3: 買い 1000→1000.5 +0.05% → -0.05%（勝ち→負け）。費用なしなら勝ち
    t3 = _one_day(1000, 1000.5, 0.001)["buy"]
    assert t3.result_return == pytest.approx(0.0005 - 0.001) and t3.is_win is False
    assert _one_day(1000, 1000.5, 0.0)["buy"].is_win is True
    # 例4: 買い 1000→1000 0.0% → -0.1%（負け）
    t4 = _one_day(1000, 1000, 0.001)["buy"]
    assert t4.result_return == pytest.approx(-0.001) and t4.is_win is False


def test_cost_example_average_of_three_trades():
    # 3件(+1.515%, -1.0%, +0.05%) をc=0.1%で: 平均 (1.415 - 1.1 - 0.05)/3 = +0.0883%、的中1件
    rets = [15 / 990, -0.01, 0.0005]
    net = [r - 0.001 for r in rets]
    assert sum(net) / 3 == pytest.approx(0.000883, abs=1e-6)
    assert sum(1 for r in net if r > 0) == 1


def test_cost_zero_is_identical_and_cost_shifts_average_exactly():
    days = _days()
    key = lambda t: (t.day, t.side, t.code, t.entry_price, t.filled, t.result_return, t.is_win)  # noqa: E731
    a = sorted(map(key, apply_rule(days, baseline(), open_close_rule(), "all")), key=repr)
    b = sorted(map(key, apply_rule(days, baseline(), open_close_rule(), "all", cost=0.0)), key=repr)
    assert a == b
    for rule in (open_close_rule(), limit_rule(0.005)):
        m0 = summarize(apply_rule(days, baseline(), rule, "all", cost=0.0), "buy")
        m1 = summarize(apply_rule(days, baseline(), rule, "all", cost=0.001), "buy")
        assert m1.avg_return == pytest.approx(m0.avg_return - 0.001)  # ちょうど費用の分だけ下がる
        assert m1.filled == m0.filled


def test_cost_not_charged_on_unfilled_trades():
    days = _days(after={25: (104, 107, 104, 106, 100)})  # 翌日Aの安値104 → 買い指値103.5に届かず不成立
    t = next(
        t for t in apply_rule(days, baseline(), limit_rule(0.005), "top", top_n=1, cost=0.01)
        if t.day == DATES[T] and t.side == "buy"
    )
    assert (t.filled, t.result_return, t.is_win) == (False, None, None)


def test_cost_lowers_win_rate_monotonically():
    days = _days()
    rates = []
    for c in (0.0, 0.01, 0.03, 0.10):
        m = summarize(apply_rule(days, baseline(), open_close_rule(), "all", cost=c), "buy")
        rates.append(m.win_rate)
    assert rates == sorted(rates, reverse=True)
    assert rates[-1] == 0.0  # 10%の費用では誰も勝てない


def test_execution_markdown_custom_title_and_note():
    md = build_execution_markdown({"x": {p: {"buy": _m(0.0), "sell": _m(0.0)} for p in ("train", "valid")}},
                                  {"train": "前半", "valid": "後半"}, title="費用比較", cost_note="費用を引いている。")
    assert md.startswith("# 費用比較") and "費用を引いている。" in md and "含まない" not in md
