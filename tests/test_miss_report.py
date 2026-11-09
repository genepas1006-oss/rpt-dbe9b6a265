"""不的中の履歴: レポート出力 → パース → サイト表示のテスト。"""

from datetime import date

from analysis.scoring import RankedCandidate
from report.build_site import build_index
from report.generate_report import generate_report
from report.parse_report import parse_report
from tracking.missed import MissedPrediction
from tracking.predictions_db import WinRateStats

STATS = WinRateStats(total_predictions=10, filled_count=8, win_count=4, win_rate=0.5)


def _miss(code="8058", name="三菱商事", pd=date(2026, 11, 5), td=date(2026, 11, 6), causes=None, side="buy"):
    return MissedPrediction(
        prediction_date=pd, target_date=td, code=code, name=name, side=side,
        entry_price=995.0, target_close=980.0, result_return=(980 - 995.0) / 995.0,
        causes=causes or ["地合い悪化", "寄りで下落"], pred_close=1000.0, target_open=990.0, market_return=-0.015,
    )


def _report(buy_missed=None, sell_missed=None):
    cand = RankedCandidate(
        code="6954", name="ファナック", total_score=3, technical_score=2, earnings_score=1,
        volume_ratio=2.0, entry_price=100.0, reasons=[], side="buy",
        day_open=100, day_high=101, day_low=99, day_close=100, day_volume=1,
    )
    return generate_report(
        date(2026, 11, 6), date(2026, 11, 9), [cand], [], STATS, STATS, None, None, buy_missed, sell_missed
    )


def test_report_text_section_format():
    text = _report(buy_missed=[_miss()])
    assert "## 不的中の履歴（買い）" in text
    assert (
        "- 2026-11-05 | 2026-11-06 | 三菱商事（8058） | 995.0円 | -1.51% | 地合い悪化・寄りで下落 | "
        "指値995.0円 → 終値980.0円／日経平均-1.50%／寄り付きは予測日終値比-1.00%"
    ) in text
    assert "不的中の履歴（売り）" not in text  # 空の側は出さない


def test_no_misses_means_no_section():
    assert "不的中の履歴" not in _report()


def test_parse_roundtrip():
    parsed = parse_report(_report(buy_missed=[_miss(), _miss(code="7203", name="トヨタ自動車", causes=["その他"])]))
    assert [m.name for m in parsed.buy_missed] == ["三菱商事（8058）", "トヨタ自動車（7203）"]
    first = parsed.buy_missed[0]
    assert first.causes == ["地合い悪化", "寄りで下落"]
    assert first.result_return == "-1.51%" and first.entry_price == "995.0円"
    assert "日経平均-1.50%" in first.detail
    assert parsed.sell_missed == []


def test_parse_old_reports_without_section_still_work():
    parsed = parse_report(_report())
    assert parsed.buy_missed == [] and parsed.sell_missed == []


def _site(tmp_path, buy_missed=None, sell_missed=None):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "2026-11-06.md").write_text(_report(buy_missed, sell_missed), encoding="utf-8")
    return build_index(reports, tmp_path / "docs", "t").read_text(encoding="utf-8")


def test_site_shows_misses_with_tags_summary_and_suggestion(tmp_path):
    missed = [_miss(), _miss(code="7203", name="トヨタ自動車", causes=["地合い悪化"]), _miss(code="9984", name="ソフトバンクG", causes=["その他"])]
    page = _site(tmp_path, buy_missed=missed)
    assert '<details class="unfilled misses"><summary><span>不的中の履歴</span><span class="uf-count">3件</span>' in page
    assert '<span class="chip">地合い悪化 2件</span>' in page  # タグ別件数（多い順）
    assert page.index("地合い悪化 2件") < page.index("寄りで下落 1件")
    assert "不的中3件のうち、「地合い悪化」が最多（2件・67%）です。" in page
    assert "（件数が少ないため参考程度です。）" in page
    assert "2026-11-05 予測 → 11/06 向け" in page
    assert '<span class="uf-gap">-1.51%</span>' in page
    assert "三菱商事" in page and "寄り付きは予測日終値比-1.00%" in page


def test_site_without_misses_has_no_block(tmp_path):
    assert 'class="unfilled misses"' not in _site(tmp_path)


def test_site_misses_are_separated_by_side(tmp_path):
    page = _site(tmp_path, buy_missed=[_miss()], sell_missed=[_miss(code="6841", name="横河電機", causes=["地合い上昇"], side="sell")])
    buy_part = page.split('id="side-sell"')[0]
    sell_part = page.split('id="side-sell"')[1]
    assert "三菱商事" in buy_part and "横河電機" not in buy_part
    assert "横河電機" in sell_part and "地合い上昇 1件" in sell_part


def test_site_escapes_html_in_detail(tmp_path):
    page = _site(tmp_path, buy_missed=[_miss(name="A&B<社>")])
    assert "A&amp;B&lt;社&gt;" in page and "A&B<社>" not in page
