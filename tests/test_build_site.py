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

    assert '<details class="day"><summary>2026-10-25</summary>' in html_text
    assert "2026-10-25" not in html_text.split("<h2>過去のレポート</h2>")[0]


def test_history_is_grouped_by_month_with_sidebar_links(tmp_path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    docs_dir = tmp_path / "docs"
    _write_report(reports_dir, "2026-09-30", [_candidate("buy")], [])
    _write_report(reports_dir, "2026-10-05", [_candidate("buy")], [])
    _write_report(reports_dir, "2026-10-26", [_candidate("buy")], [])

    index_path = build_index(reports_dir, docs_dir, "2026-10-26 16:00")
    html_text = index_path.read_text(encoding="utf-8")

    assert '<a href="#m-2026-10">2026年10月</a>' in html_text
    assert '<a href="#m-2026-09">2026年9月</a>' in html_text
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
