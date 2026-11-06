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

    assert '<span class="side-badge buy">買い・スコア3</span>' in html_text
    assert '<span class="side-badge sell">売り・スコア3</span>' in html_text
    assert '<span style="color:var(--up)">+3.89%</span>' in html_text
    assert "タップで当日の値動きを見る" in html_text
    assert '<span class="one-point-label">ワンポイント:</span>' in html_text
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


def test_outlook_is_rendered_as_separate_block(tmp_path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    docs_dir = tmp_path / "docs"
    _write_report(reports_dir, "2026-10-26", [_candidate("buy")], [_candidate("sell")])

    html_text = build_index(reports_dir, docs_dir, "2026-10-26 16:00").read_text(encoding="utf-8")

    assert '<p class="outlook buy"><span class="outlook-label">明日の見通し</span>' in html_text
    assert '<p class="outlook sell"><span class="outlook-label">明日の見通し</span>' in html_text
    # ワンポイント側には見通しが混ざらない
    assert "ワンポイント:</span>寄り付きから上昇して、出来高が急増し、高値圏で引けた。</p>" in html_text


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
