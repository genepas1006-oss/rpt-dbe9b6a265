"""report.build_site のテスト。"""

from datetime import date
from pathlib import Path

from analysis.scoring import RankedCandidate
from report.build_site import build_index
from report.generate_report import generate_report
from tracking.predictions_db import WinRateStats

STATS = WinRateStats(total_predictions=10, filled_count=8, win_count=4, win_rate=0.5)


def _write_report(reports_dir: Path, day: str, buy: list, sell: list) -> None:
    text = generate_report(
        date.fromisoformat(day),
        date.fromisoformat(day),
        buy,
        sell,
        STATS,
        STATS,
    )
    (reports_dir / f"{day}.md").write_text(text, encoding="utf-8")


def _candidate(side: str) -> RankedCandidate:
    return RankedCandidate(
        code="6954",
        name="ファナック",
        total_score=3,
        technical_score=2,
        earnings_score=1,
        volume_ratio=2.45,
        entry_price=5608.8,
        reasons=["当日+3.89%"],
        side=side,
        day_open=5400.0,
        day_high=5650.0,
        day_low=5380.0,
        day_close=5610.0,
        day_volume=12_000_000,
    )


def test_latest_report_shows_buy_and_sell_badges_with_colored_deltas(tmp_path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    docs_dir = tmp_path / "docs"
    _write_report(reports_dir, "2026-10-26", [_candidate("buy")], [_candidate("sell")])

    index_path = build_index(reports_dir, docs_dir, "2026-10-26 16:00")
    html_text = index_path.read_text(encoding="utf-8")

    assert '<span class="side-badge buy">買い・スコア3/7点</span>' in html_text
    assert '<span class="side-badge sell">売り・スコア3/7点</span>' in html_text
    assert '<span style="color:var(--up)">+3.89%</span>' in html_text
    assert "タップでスコアの内訳と気をつける点を見る" in html_text
    assert '<table class="score-table">' in html_text  # スコアの内訳
    assert "高値5,650.0円" in html_text


def test_history_entries_are_collapsed(tmp_path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    docs_dir = tmp_path / "docs"
    _write_report(reports_dir, "2026-10-25", [_candidate("buy")], [])
    _write_report(reports_dir, "2026-10-26", [_candidate("buy")], [])

    index_path = build_index(reports_dir, docs_dir, "2026-10-26 16:00")
    html_text = index_path.read_text(encoding="utf-8")

    assert '<details class="day-row" name="history"><summary>' in html_text
    assert '<span class="d-date">10/25<small>2026 日</small></span>' in html_text
    assert "10/25" not in html_text.split('<div class="history-head">')[0]


def test_history_is_grouped_by_month_with_sidebar_links(tmp_path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    docs_dir = tmp_path / "docs"
    _write_report(reports_dir, "2026-09-30", [_candidate("buy")], [])
    _write_report(reports_dir, "2026-10-05", [_candidate("buy")], [])
    _write_report(reports_dir, "2026-10-26", [_candidate("buy")], [])

    index_path = build_index(reports_dir, docs_dir, "2026-10-26 16:00")
    html_text = index_path.read_text(encoding="utf-8")

    assert 'href="#m-2026-10" data-month="2026-10">2026年10月</a>' in html_text
    assert 'href="#m-2026-09" data-month="2026-09">2026年9月</a>' in html_text
    assert 'id="m-2026-10"' in html_text
    assert 'id="m-2026-09"' in html_text
    # 新しい月が先に来る
    assert html_text.index('id="m-2026-10"') < html_text.index('id="m-2026-09"')


def test_no_reports_shows_placeholder_message(tmp_path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    docs_dir = tmp_path / "docs"

    index_path = build_index(reports_dir, docs_dir, "2026-10-26 16:00")
    html_text = index_path.read_text(encoding="utf-8")

    assert "まだレポートが生成されていません。" in html_text


def test_card_shows_score_breakdown_and_watch_points(tmp_path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    docs_dir = tmp_path / "docs"
    _write_report(reports_dir, "2026-10-26", [_candidate("buy")], [_candidate("sell")])

    html_text = build_index(reports_dir, docs_dir, "2026-10-26 16:00").read_text(encoding="utf-8")

    assert "<caption>スコアの内訳（値動き・出来高5点＋決算2点＝7点満点）</caption>" in html_text
    assert "<th>出来高</th>" in html_text
    assert '<div class="watch"><b>気をつける点</b>' in html_text
    assert "スコアと成績の見方" in html_text  # 見方の説明


def test_old_format_report_still_renders_one_point_and_outlook(tmp_path):
    """過去分（ワンポイント・明日の見通し付きの旧フォーマット）も表示できる。"""
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    docs_dir = tmp_path / "docs"
    (reports_dir / "2026-10-26.md").write_text(
        "# 日本株デイクローズ・リサーチレポート 2026-10-26\n\n"
        "## 本日の買い候補（2026-10-27向け・参考指値）\n\n"
        "### 1位 ファナック（6954） - スコア3点\n"
        "- 内訳: 値動き・出来高2点 / 決算パターン1点\n"
        "- 参考指値: 5,608.8円\n"
        "- 根拠: 当日+3.89%\n"
        "- 当日の値動き: 始値1円 / 高値2円 / 安値1円 / 終値2円 / 出来高1株\n"
        "- ワンポイント: 寄り付きから上昇して、高値圏で引けた。\n"
        "- 明日の見通し: 方向感は定まっておらず、寄り付きの強弱を見極めたい。\n",
        encoding="utf-8",
    )

    html_text = build_index(reports_dir, docs_dir, "2026-10-26 16:00").read_text(encoding="utf-8")

    assert '<p class="outlook buy"><span class="outlook-label">明日の見通し</span>' in html_text
    assert "ワンポイント:</span>寄り付きから上昇して、高値圏で引けた。</p>" in html_text


def test_unfilled_history_button_and_reasons(tmp_path):
    from tracking.unfilled import UnfilledPrediction

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    docs_dir = tmp_path / "docs"
    sell_unfilled = [
        UnfilledPrediction(
            prediction_date=date(2026, 10, 27), target_date=date(2026, 10, 28), code="6841",
            name="横河電機", side="sell", entry_price=4051.2,
            target_low=3900.0, target_high=4040.0, target_close=3950.0,
        )
    ]
    text = generate_report(
        date(2026, 10, 28), date(2026, 10, 29), [_candidate("buy")], [_candidate("sell")],
        STATS, STATS, [], sell_unfilled,
    )
    (reports_dir / "2026-10-28.md").write_text(text, encoding="utf-8")

    html_text = build_index(reports_dir, docs_dir, "t").read_text(encoding="utf-8")

    assert '<span class="uf-count">1件</span>' in html_text
    assert "横河電機" in html_text
    assert "対象日の高値4,040.0円が参考指値4,051.2円まで上がらず（差11.2円・0.28%）" in html_text
    assert "あと0.28%" in html_text
    assert "当日の高値</span>4,040.0円" in html_text
    assert "2026-10-27 予測 → 10/28 向け" in html_text
    assert html_text.count('class="uf-count"') == 1  # 買いは不成立なしのため非表示


def test_fund_block_shows_balance_and_day_change(tmp_path):
    from datetime import date as d
    from report.build_site import _fund_block
    from tracking.virtual_fund import FundDay, VirtualFund

    day = FundDay(d(2026, 11, 9), d(2026, 11, 10), 1_000_000, 1600.0, 1500.0, 100.0, 6, 1_001_600.0)
    html_ = _fund_block(VirtualFund(1_000_000.0, [day]))
    assert "1,001,600円" in html_
    assert "+1,600円" in html_ and "+0.16%" in html_
    assert "保証するものではありません" in html_


def test_fund_block_before_first_result_and_none():
    from report.build_site import _fund_block
    from tracking.virtual_fund import VirtualFund

    html_ = _fund_block(VirtualFund(1_000_000.0, []))
    assert "1,000,000円" in html_ and "—" in html_
    assert _fund_block(None) == ""


def test_premarket_empty_report_is_hidden_but_other_empty_reports_stay(tmp_path):
    from tracking.previous import PreviousItem, PreviousResults

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    _write_report(reports_dir, "2026-10-26", [_candidate("buy")], [_candidate("sell")])
    pending = PreviousResults(
        date(2026, 10, 26), date(2026, 10, 27),
        [PreviousItem(1, "6954", "ファナック", 5608.8, "pending", None, None, None, None)],
    )
    # 取引前に作られた空のレポート: 候補なし、前営業日の結果は全て未確定
    (reports_dir / "2026-10-27.md").write_text(
        generate_report(date(2026, 10, 27), date(2026, 10, 28), [], [], STATS, STATS, buy_previous=pending),
        encoding="utf-8",
    )
    # 前営業日の情報がない空のレポートは、従来どおり載せる
    _write_report(reports_dir, "2026-10-29", [], [])
    page = build_index(reports_dir, tmp_path / "docs", "x").read_text(encoding="utf-8")
    assert "<b>2026-10-27</b>" not in page
    assert "10/26" in page and "<b>2026-10-29</b>" in page


def test_stock_names_link_to_yahoo_chart():
    from report.build_site import _stock_link

    a = _stock_link("ファナック（6954）")
    assert 'href="https://finance.yahoo.co.jp/quote/6954.T/chart"' in a and ">ファナック（6954）</a>" in a
    assert 'target="_blank"' in a and 'rel="noopener noreferrer"' in a
    assert "href" in _stock_link("キオクシアホールディングス（285A）")  # 英字を含むコード
    assert _stock_link("コード無し") == "コード無し"  # コードが分からなければリンクにしない
    assert _stock_link('A"<b>（6954）', None).count("<b>") == 0  # 名前はエスケープされる


def test_candidate_card_name_is_linked(tmp_path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    _write_report(reports_dir, "2026-10-26", [_candidate("buy")], [_candidate("sell")])
    page = build_index(reports_dir, tmp_path / "docs", "x").read_text(encoding="utf-8")
    assert '<span class="card-name"><a class="stock-link" href="https://finance.yahoo.co.jp/quote/6954.T/chart"' in page
