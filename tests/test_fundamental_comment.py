"""ファンダメンタルに基づくコメントのテスト。承認済みの手計算ケース（2026-11-10）。"""

from datetime import date

import pytest

from analysis.fundamental_comment import (
    build_fundamental_outlook,
    build_fundamental_sentence,
    build_items,
    earnings_notice,
)
from data_sources.base import Fundamentals
from report.one_point_summary import build_one_point_with_fundamentals, build_outlook_with_fundamentals

# 取得済みの三井化学（4183）の値。現値1,586円
MITSUI = Fundamentals(per=8.895619, pbr=0.65654796, dividend_yield=0.0433, roe=0.08045, revenue_growth=0.108,
                      earnings_growth=44.629, target_price=2518.0, analyst_count=10, week52_high=2477.5, week52_low=1475.0)


def _texts(f, close=1586.0):
    return [i.text for i in build_items(f, close)]


def test_mitsui_one_point_sentence():
    s = build_fundamental_sentence(MITSUI, 1586.0)
    assert s == ("PER 8.9倍・PBR 0.66倍（1倍割れ）と割安水準、"
                 "売上高成長+10.8%（増収基調）・利益は前年比2倍超（前年が低水準の影響の可能性）、"
                 "アナリスト目標株価2,518円（10名）は現値比+58.8%。")  # 最大3項目（ROE・配当は載せない）


def test_mitsui_sell_outlook_is_contrary():
    s = build_fundamental_outlook(MITSUI, 1586.0, "sell")
    assert s == "ファンダメンタル面は売り方向と逆行する材料が多く（割安・増益基調・目標株価が現値を上回る）、急反発に注意。"
    one = Fundamentals(earnings_growth=-0.2)  # 材料が1つだけのときは「多く」とは書かない
    assert build_fundamental_outlook(one, 1000.0, "sell") == "ファンダメンタル面は売り方向と整合する材料があり（減益基調）、"
    assert build_fundamental_outlook(one, 1000.0, "buy") == "ファンダメンタル面は買い方向と逆行する材料があり（減益基調）、戻り売りに押される可能性に注意。"
    assert build_fundamental_outlook(MITSUI, 1586.0, "buy").startswith("ファンダメンタル面は買い方向と整合する材料が多く（割安・増益基調・目標株価が現値を上回る）、")


@pytest.mark.parametrize("per,label", [(9.9, "と割安水準"), (10.0, "と市場平均並み"), (19.9, "と市場平均並み"),
                                        (20.0, "とやや割高"), (30.0, "とやや割高"), (30.1, "と割高水準")])
def test_per_boundaries(per, label):
    assert _texts(Fundamentals(per=per))[0] == f"PER {per:.1f}倍{label}"


def test_per_missing_uses_pbr_only():
    assert _texts(Fundamentals(pbr=0.8)) == ["PBR 0.80倍（1倍割れ）"]
    assert build_items(Fundamentals(pbr=0.8), 1000.0)[0].stance == "bull"
    assert _texts(Fundamentals(pbr=1.5)) == ["PBR 1.50倍"]


@pytest.mark.parametrize("g,stance", [(0.10, "bull"), (0.099, None), (-0.10, "bear"), (-0.099, None), (1.01, "bull")])
def test_earnings_growth_boundaries(g, stance):
    it = [i for i in build_items(Fundamentals(earnings_growth=g), 1000.0) if "利益" in i.text][0]
    assert it.stance == stance


@pytest.mark.parametrize("target,n,stance,shown", [(1150, 5, "bull", True), (1149, 5, None, True), (950, 5, "bear", True),
                                                   (951, 5, None, True), (1500, 4, None, False)])
def test_target_price_boundaries(target, n, stance, shown):
    items = [i for i in build_items(Fundamentals(target_price=float(target), analyst_count=n), 1000.0) if "目標株価" in i.text]
    assert bool(items) is shown
    if shown:
        assert items[0].stance == stance


def test_target_deviation_text():
    assert "現値比+58.8%" in _texts(Fundamentals(target_price=2518.0, analyst_count=10), 1586.0)[0]  # (2518-1586)/1586


@pytest.mark.parametrize("close,expected", [(1586.0, None), (1500.0, "52週レンジの安値圏"), (2400.0, "52週レンジの高値圏"), (3000.0, None)])
def test_week52_position(close, expected):
    f = Fundamentals(week52_high=2477.5, week52_low=1475.0)  # 1,586 → 0.111 / 1,500 → 0.025 / 2,400 → 0.923 / 3,000 は範囲外
    assert (_texts(f, close) or [None])[0] == expected


def test_roe_and_dividend_only_when_notable():
    assert _texts(Fundamentals(roe=0.07, dividend_yield=0.02)) == []
    assert _texts(Fundamentals(roe=0.12, dividend_yield=0.03)) == ["ROE 12.0%（資本効率は良好）", "配当利回り3.00%（高配当）"]
    assert _texts(Fundamentals(roe=0.049)) == ["ROE 4.9%（低め）"]


def test_mixed_and_no_stance():
    f = Fundamentals(per=8.0, earnings_growth=-0.2)
    assert build_fundamental_outlook(f, 1000.0, "buy") == "ファンダメンタル面は材料が混在しており（割安・減益基調）、"
    assert build_fundamental_outlook(Fundamentals(per=15.0), 1000.0, "buy") is None  # 平均並みは材料なし
    assert build_fundamental_sentence(Fundamentals(), 1000.0) is None


def test_earnings_notice_boundaries():
    assert earnings_notice(0) == "決算発表が本日に予定されており、発表前後の値動きの拡大にも注意。"
    assert "14日後" in earnings_notice(14)
    assert earnings_notice(15) == "" and earnings_notice(None) == "" and earnings_notice(-1) == ""


def test_one_point_and_outlook_composition_and_fallback():
    one = build_one_point_with_fundamentals(1010.0, 900.0, 905.0, 7.21, -0.0987, MITSUI, "従来の文。")
    assert one.startswith("当日-9.87%、出来高は20日平均の7.21倍、安値圏で引けた。PER 8.9倍")
    assert build_one_point_with_fundamentals(1010.0, 900.0, 905.0, 7.21, -0.0987, None, "従来の文。") == "従来の文。"
    out = build_outlook_with_fundamentals("sell", 1010.0, 900.0, 905.0, 7.21, MITSUI, 3)
    assert out.startswith("ファンダメンタル面は売り方向と逆行する材料が多く") and "急反発に注意。戻り売りに押される形で" in out
    assert out.endswith("決算発表が3日後に予定されており、発表前後の値動きの拡大にも注意。")
    # ファンダメンタルも決算も無ければ従来の文のまま
    from report.one_point_summary import build_outlook
    assert build_outlook_with_fundamentals("sell", 1010.0, 900.0, 905.0, 7.21, None, None) == build_outlook("sell", 1010.0, 900.0, 905.0, 7.21)


def test_one_point_omits_nan_daily_return():
    one = build_one_point_with_fundamentals(1010.0, 900.0, 905.0, 7.21, float("nan"), MITSUI, "従来の文。")
    assert one.startswith("出来高は20日平均の7.21倍、") and "nan" not in one


def test_no_assertive_wording():
    text = build_fundamental_outlook(MITSUI, 1586.0, "sell") + build_fundamental_sentence(MITSUI, 1586.0)
    for bad in ("必ず", "確実", "保証", "間違いなく"):
        assert bad not in text


def test_next_earnings_days():
    from run_daily import next_earnings_days

    today = date(2026, 11, 10)
    assert next_earnings_days([date(2026, 11, 5), date(2026, 11, 13), date(2026, 12, 1)], today) == 3
    assert next_earnings_days([date(2026, 11, 10)], today) == 0
    assert next_earnings_days([date(2026, 11, 5)], today) is None


def test_yfinance_fundamentals_normalization(monkeypatch):
    import yfinance as yf

    from data_sources.yfinance_source import YFinanceSource

    class T:
        def __init__(self, s):
            self.info = {"trailingPE": -3.0, "priceToBook": 0.66, "dividendYield": 4.33, "numberOfAnalystOpinions": 10,
                         "targetMeanPrice": 2518.0, "returnOnEquity": None}

    monkeypatch.setattr(yf, "Ticker", T)
    f = YFinanceSource().get_fundamentals("4183")
    assert f.per is None and f.pbr == 0.66 and f.dividend_yield == pytest.approx(0.0433)
    assert f.analyst_count == 10 and f.target_price == 2518.0 and f.roe is None


def test_generate_report_uses_fundamentals():
    from analysis.scoring import RankedCandidate
    from report.generate_report import generate_report
    from tracking.predictions_db import WinRateStats

    st = WinRateStats(1, 1, 1, 1.0)
    c = RankedCandidate(code="4183", name="三井化学", total_score=4, technical_score=3, earnings_score=1, volume_ratio=7.21,
                        entry_price=1594.0, reasons=[], side="sell", day_open=1700.0, day_high=1710.0, day_low=1580.0,
                        day_close=1586.0, day_volume=1, daily_return=-0.0987)
    d = date(2026, 11, 9)
    text = generate_report(d, date(2026, 11, 10), [], [c], st, st, fundamentals={"4183": MITSUI}, earnings_days={"4183": 3})
    assert "- 参考（業績・割安度）: PER 8.9倍" in text  # ファンダメンタルは参考欄に隔離（2026-11-11）
    assert "ファンダメンタル面は売り方向と逆行する材料が多く" in text
    assert "- 気をつける点: 決算発表が3日後に予定されており" in text
    assert "- ワンポイント:" not in text and "- 明日の見通し:" not in text
    plain = generate_report(d, date(2026, 11, 10), [], [c], st, st)
    assert "PER" not in plain  # ファンダメンタルが無ければ従来の文
