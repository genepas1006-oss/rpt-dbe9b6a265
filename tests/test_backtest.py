"""backtest.engine のテスト。

合成データ（手計算できる値動き）で、スコア・約定・リターン・先読みなし・祝日またぎ・
フィルター・集計を検証する。
"""

from datetime import date, timedelta

import pytest

import backtest.engine as engine
from analysis.scoring import CandidateInput
from analysis.technical import TechnicalScore
from backtest.engine import (
    DayCandidate,
    Features,
    Trade,
    TradingDay,
    apply_variant,
    baseline,
    build_trading_days,
    combine,
    market_filter,
    overheat_filter,
    split_days,
    summarize,
)
from data_sources.base import DailyBar
from tracking.trade_eval import evaluate_trade


def _dates(n: int, start: date = date(2026, 1, 5)) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _bars(dates: list[date], rows: list[tuple]) -> list[DailyBar]:
    return [DailyBar(d, o, h, l, c, v) for d, (o, h, l, c, v) in zip(dates, rows)]


FLAT = (100, 100, 100, 100, 100)
N = 30
DATES = _dates(N)
T = 24  # 注目する営業日のインデックス


def _dataset(after: dict[int, tuple] | None = None):
    """A: 上昇+出来高急増 / B: 無変化 / C: 下落+出来高急増。index24が注目日、25が翌営業日。"""
    after = after or {}

    def series(special: dict[int, tuple], tail: tuple) -> list[tuple]:
        rows = []
        for i in range(N):
            rows.append(special.get(i, FLAT if i < T else tail))
        return rows

    a = series({24: (100, 105, 100, 104, 300), 25: (104, 107, 103, 106, 100)}, (106, 106, 106, 106, 100))
    c = series({24: (100, 100, 95, 96, 300), 25: (96, 97, 93, 94, 100)}, (94, 94, 94, 94, 100))
    b = series({}, FLAT)
    for i, row in after.items():
        a[i] = row
    return {
        "A": _bars(DATES, a),
        "B": _bars(DATES, b),
        "C": _bars(DATES, c),
    }


def _index_bars():
    return _bars(DATES, [FLAT] * N)


NAMES = {"A": "銘柄A", "B": "銘柄B", "C": "銘柄C"}


def _days(after=None, earnings=None):
    return build_trading_days(_dataset(after), NAMES, _index_bars(), earnings)


def _day(days, i):
    return next(d for d in days if d.day == DATES[i])


# ---------------- 組み立て・スコア ----------------
def test_one_trading_day_per_index_pair():
    days = _days()
    assert len(days) == N - 1
    assert days[0].next_day == DATES[1]


def test_scores_on_focus_day_match_hand_calc():
    cands = {c.code: c for c in _day(_days(), T).candidates}
    # A: 出来高3.0倍(+2) + 騰落+4%(+2) + 引け位置0.8(+1) = 5
    assert cands["A"].buy.technical.technical_score == 5
    # A売り: 出来高のみ +2（騰落・引け位置は買い方向）
    assert cands["A"].sell.technical.technical_score == 2
    # C売り: 出来高(+2) + 騰落-4%(+2) + 引け位置0.2(+1) = 5 / C買い: 出来高のみ 2
    assert cands["C"].sell.technical.technical_score == 5
    assert cands["C"].buy.technical.technical_score == 2
    # B: 無変化 → 0点
    assert cands["B"].buy.technical.technical_score == 0


def test_features_on_focus_day():
    f = {c.code: c.features for c in _day(_days(), T).candidates}["A"]
    assert f.market_bias == 1  # 指数は全て100: MA=100, 終値100 → +1
    closes = [100.0] * 24 + [104.0]
    assert f.deviation25 == pytest.approx((104 - sum(closes) / 25) / (sum(closes) / 25))
    assert f.rsi14 == 100.0  # 直近14日は変化なし13回 + 上昇1回 → 下落0


# ---------------- 約定・リターンの手計算 ----------------
def test_baseline_trades_on_focus_day_match_hand_calc():
    trades = [t for t in apply_variant(_days(), baseline(), top_n=5) if t.day == DATES[T]]
    by = {(t.side, t.code): t for t in trades}
    assert set(by) == {("buy", "A"), ("buy", "C"), ("sell", "C"), ("sell", "A")}  # Bは0点で除外

    # 指値は本番と同じく 終値×係数 を0.1円単位に丸める（round(…, 1)）
    a_buy = by[("buy", "A")]  # 104*0.995=103.48 → 103.5, 翌日 安値103 → 約定, 終値106
    assert a_buy.entry_price == 103.5
    assert a_buy.filled and a_buy.is_win
    assert a_buy.result_return == pytest.approx((106 - 103.5) / 103.5)

    c_sell = by[("sell", "C")]  # 96*1.005=96.48 → 96.5, 翌日 高値97 → 約定, 終値94
    assert c_sell.entry_price == 96.5
    assert c_sell.result_return == pytest.approx((96.5 - 94) / 96.5)

    a_sell = by[("sell", "A")]  # 104*1.005=104.52 → 104.5, 翌日 高値107 → 約定, 終値106 → 負け
    assert a_sell.entry_price == 104.5
    assert a_sell.filled and a_sell.is_win is False
    assert a_sell.result_return == pytest.approx((104.5 - 106) / 104.5)

    c_buy = by[("buy", "C")]  # 96*0.995=95.52 → 95.5, 翌日 安値93 → 約定, 終値94 → 負け
    assert c_buy.entry_price == 95.5
    assert c_buy.result_return == pytest.approx((94 - 95.5) / 95.5)


def test_top_n_limits_each_side():
    trades = [t for t in apply_variant(_days(), baseline(), top_n=1) if t.day == DATES[T]]
    assert {(t.side, t.code) for t in trades} == {("buy", "A"), ("sell", "C")}


def test_entry_discount_is_applied():
    trades = [t for t in apply_variant(_days(), baseline(), top_n=1, entry_discount=0.01) if t.day == DATES[T]]
    by = {t.side: t for t in trades}
    assert by["buy"].entry_price == 103.0   # 104*0.99=102.96 → 103.0
    assert by["sell"].entry_price == 97.0   # 96*1.01=96.96 → 97.0


def test_unfilled_when_next_day_does_not_reach_entry():
    # 翌日(index25)のAの安値を104にする → 指値103.5に届かず不成立
    days = _days(after={25: (104, 107, 104, 106, 100)})
    a_buy = next(t for t in apply_variant(days, baseline(), top_n=1) if t.day == DATES[T] and t.side == "buy")
    assert (a_buy.filled, a_buy.result_return, a_buy.is_win) == (False, None, None)


# ---------------- 先読みがないこと ----------------
def test_selection_does_not_depend_on_data_after_next_day():
    base = _days()
    # 翌営業日(25)より後のAを極端に変える
    changed = _days(after={26: (1, 9999, 1, 9999, 10**9), 27: (5, 5, 5, 5, 5)})
    # 25日目までの候補（スコア・特徴量・翌日の足を含む）は完全に一致する
    assert [d for d in base if d.day <= DATES[T]] == [d for d in changed if d.day <= DATES[T]]


def test_selection_on_day_ignores_next_day_values():
    base = _days()
    changed = _days(after={25: (104, 200, 1, 150, 999)})  # 翌日の値動きだけを変える
    sel = lambda days: [  # noqa: E731
        (t.side, t.code, round(t.entry_price, 6))
        for t in apply_variant(days, baseline(), top_n=5)
        if t.day == DATES[T]
    ]
    assert sel(base) == sel(changed)  # 選定と指値は同じ
    # 一方で結果は変わる（翌日の足は答え合わせにだけ使われる）
    res = lambda days: [t.result_return for t in apply_variant(days, baseline(), top_n=5) if t.day == DATES[T]]  # noqa: E731
    assert res(base) != res(changed)


def test_future_earnings_dates_are_not_passed_to_scoring(monkeypatch):
    seen = []

    def spy(bars, earnings_dates, *a, **k):
        seen.append((bars[-1].trade_date, list(earnings_dates)))
        return None

    monkeypatch.setattr(engine, "compute_earnings_score", spy)
    monkeypatch.setattr(engine, "compute_short_earnings_score", spy)
    past, future = DATES[3], DATES[28]
    build_trading_days(_dataset(), NAMES, _index_bars(), {"A": [past, future]})
    assert seen
    for day, dates in seen:
        assert all(d <= day for d in dates)  # 将来の決算日は渡らない
    assert any(past in dates for _, dates in seen)  # 過去の決算日は渡る


# ---------------- 祝日またぎ・欠損 ----------------
def test_next_day_is_next_index_date_across_gap():
    ds = [date(2026, 2, 10), date(2026, 2, 13)]  # 間に休場日
    idx = _bars(ds, [FLAT, FLAT])
    bars = {"A": _bars(ds, [FLAT, FLAT])}
    days = build_trading_days(bars, {"A": "A"}, idx)
    assert len(days) == 1
    assert days[0].next_day == date(2026, 2, 13)
    assert days[0].candidates[0].next_bar.trade_date == date(2026, 2, 13)


def test_code_missing_today_or_next_day_bar_is_skipped():
    data = _dataset()
    data["A"] = [b for b in data["A"] if b.trade_date != DATES[T]]  # 注目日の足がない
    data["C"] = [b for b in data["C"] if b.trade_date != DATES[T + 1]]  # 翌営業日の足がない
    days = build_trading_days(data, NAMES, _index_bars())
    codes = {c.code for c in _day(days, T).candidates}
    assert codes == {"B"}


# ---------------- フィルター ----------------
F = Features


def test_market_filter_semantics():
    v = market_filter()
    assert v.allow("buy", F(1, None, None)) and not v.allow("buy", F(-1, None, None))
    assert v.allow("sell", F(-1, None, None)) and not v.allow("sell", F(1, None, None))
    assert v.allow("buy", F(None, None, None)) and v.allow("sell", F(None, None, None))  # 判定なしは通す


def test_overheat_dev_boundaries():
    v = overheat_filter(dev_threshold=0.10)
    assert not v.allow("buy", F(1, 0.10, 50))   # 境界は除外（>=）
    assert v.allow("buy", F(1, 0.0999, 50))
    assert not v.allow("sell", F(-1, -0.10, 50))  # 売りは -閾値 以下を除外
    assert v.allow("sell", F(-1, -0.0999, 50))
    assert v.allow("buy", F(1, -0.5, 50)) and v.allow("sell", F(-1, 0.5, 50))  # 逆方向の乖離は除外しない


def test_overheat_rsi_boundaries_are_symmetric():
    v = overheat_filter(rsi_threshold=70)
    assert not v.allow("buy", F(1, 0, 70)) and v.allow("buy", F(1, 0, 69.99))
    assert not v.allow("sell", F(-1, 0, 30)) and v.allow("sell", F(-1, 0, 30.01))  # 100-70=30


def test_overheat_none_features_are_not_excluded():
    v = overheat_filter(dev_threshold=0.05, rsi_threshold=60)
    assert v.allow("buy", F(1, None, None)) and v.allow("sell", F(-1, None, None))


def test_overheat_dev_or_rsi_either_excludes():
    v = overheat_filter(dev_threshold=0.10, rsi_threshold=70)
    assert not v.allow("buy", F(1, 0.2, 10))
    assert not v.allow("buy", F(1, 0.0, 80))
    assert v.allow("buy", F(1, 0.0, 10))


def test_combine_requires_all_and_names_join():
    v = combine(market_filter(), overheat_filter(dev_threshold=0.10))
    assert v.name == "market+overheat:dev10%"
    assert not v.allow("buy", F(-1, 0.0, 50))   # 地合いで除外
    assert not v.allow("buy", F(1, 0.2, 50))    # 過熱で除外
    assert v.allow("buy", F(1, 0.0, 50))


def _manual_day(items: list[tuple[str, int, Features]]) -> TradingDay:
    """(コード, 買いスコア, 特徴量) から、翌日の足が固定の1日分を作る。売りスコアは0。"""
    cands = []
    for code, score, feat in items:
        tech = TechnicalScore(2.0, 0.0, 0.5, score, 0, 0, score, [])
        zero = TechnicalScore(1.0, 0.0, 0.5, 0, 0, 0, 0, [])
        cands.append(
            DayCandidate(
                code=code,
                features=feat,
                buy=CandidateInput(code, code, 100.0, tech, None),
                sell=CandidateInput(code, code, 100.0, zero, None),
                next_bar=DailyBar(date(2026, 1, 6), 100, 101, 99, 100, 1),
            )
        )
    return TradingDay(date(2026, 1, 5), date(2026, 1, 6), cands)


def test_filter_removes_before_ranking_so_next_candidate_fills_in():
    day = _manual_day([("HOT", 5, F(1, 0.2, 50)), ("OK1", 4, F(1, 0.0, 50)), ("OK2", 3, F(1, 0.0, 50))])
    base = apply_variant([day], baseline(), top_n=1)
    assert [t.code for t in base if t.side == "buy"] == ["HOT"]
    filt = apply_variant([day], overheat_filter(dev_threshold=0.1), top_n=1)
    assert [t.code for t in filt if t.side == "buy"] == ["OK1"]  # 過熱のHOTを除外 → 次点が入る
    two = apply_variant([day], overheat_filter(dev_threshold=0.1), top_n=2)
    assert [t.code for t in two if t.side == "buy"] == ["OK1", "OK2"]


def test_filter_can_leave_no_candidates():
    day = _manual_day([("HOT", 5, F(-1, 0.2, 50))])
    assert apply_variant([day], market_filter(), top_n=5) == []


# ---------------- 集計 ----------------
def _trade(side, entry, low, high, close):
    r = evaluate_trade(side, entry, low, high, close)
    return Trade(date(2026, 1, 5), date(2026, 1, 6), side, "X", entry, r.filled, r.result_return, r.is_win)


SAMPLE = [
    _trade("buy", 995.0, 990, 1010, 1005),    # +1.005% 勝ち
    _trade("buy", 995.0, 975, 1000, 980),     # -1.508% 負け
    _trade("buy", 1990.0, 1995, 2050, 2040),  # 不成立
    _trade("sell", 502.5, 495, 510, 498),     # +0.896% 勝ち
    _trade("sell", 1005.0, 950, 1004, 960),   # 不成立
]


def test_summarize_buy_hand_calc():
    m = summarize(SAMPLE, "buy")
    win, loss = 10 / 995, -15 / 995
    assert (m.count, m.filled, m.wins) == (3, 2, 1)
    assert m.fill_rate == pytest.approx(2 / 3)
    assert m.win_rate == pytest.approx(0.5)
    assert m.avg_return == pytest.approx((win + loss) / 2)  # ≒ -0.251%
    assert m.avg_win == pytest.approx(win) and m.avg_loss == pytest.approx(loss)
    assert m.payoff_ratio == pytest.approx(win / abs(loss))  # ≒ 0.667


def test_summarize_sell_hand_calc_and_sides_are_separate():
    m = summarize(SAMPLE, "sell")
    assert (m.count, m.filled, m.wins) == (2, 1, 1)
    assert m.fill_rate == pytest.approx(0.5) and m.win_rate == pytest.approx(1.0)
    assert m.avg_return == pytest.approx(4.5 / 502.5)
    assert m.avg_loss is None and m.payoff_ratio is None  # 負けなし


def test_summarize_zero_return_is_neither_win_nor_loss():
    m = summarize([_trade("buy", 100.0, 99, 101, 100)], "buy")
    assert (m.filled, m.wins) == (1, 0)
    assert m.win_rate == 0.0 and m.avg_return == 0.0
    assert m.avg_win is None and m.avg_loss is None and m.payoff_ratio is None


def test_summarize_all_unfilled_and_empty():
    unfilled = summarize([_trade("buy", 1990.0, 1995, 2050, 2040)], "buy")
    assert unfilled.count == 1 and unfilled.filled == 0 and unfilled.fill_rate == 0.0
    assert unfilled.win_rate is None and unfilled.avg_return is None
    empty = summarize([], "sell")
    assert empty.count == 0 and empty.fill_rate is None and empty.win_rate is None


# ---------------- 期間分割 ----------------
def _plain_days(n):
    return [TradingDay(d, d, []) for d in _dates(n)]


def test_split_days_70_30():
    train, valid = split_days(_plain_days(10))
    assert (len(train), len(valid)) == (7, 3)
    assert train[-1].day < valid[0].day


def test_split_days_orders_by_date_even_if_shuffled():
    days = list(reversed(_plain_days(10)))
    train, valid = split_days(days)
    assert [d.day for d in train + valid] == sorted(d.day for d in days)


def test_split_days_small_sizes():
    train, valid = split_days(_plain_days(3))
    assert (len(train), len(valid)) == (2, 1)  # int(3*0.7)=2
    assert split_days([]) == ([], [])


def test_split_days_truncates_instead_of_rounding():
    # 4日 × 0.7 = 2.8 → 切り捨てて前半2日（後半を2日確保して検証期間を削らない）
    train, valid = split_days(_plain_days(4))
    assert (len(train), len(valid)) == (2, 2)
