"""reports/*.md から外出先閲覧用の静的HTMLページ（docs/index.html）を生成する。

GitHub Pagesで公開することを想定し、外部サービス・ログイン・サーバー実行を
一切必要としない単一の静的HTMLファイルとして出力する。

承認済み配色ルール（2026-10-26）:
    - 買い候補＝赤系、売り候補＝緑系で視覚的に区別する（一目で買い/売りが分かるように）。
    - プラス符号の数値は赤、マイナス符号の数値は緑で統一する（日本の相場表示の慣例）。
    「買いは上昇期待＝赤」「売りは下落期待＝緑」で、候補の色分けと数値の色分けが
    同じ意味（赤=強気/緑=弱気）になるよう揃えている。

2026-10-26: 各候補カードをクリック（タップ）すると、当日の値動き（寄り・高値・
    安値・引け・出来高）とワンポイント要約を表示するように変更。
2026-10-26: 過去レポートを月別にグルーピングし、サイドバー（モバイルでは
    横スクロールの月チップ）から各月にジャンプできるようにした。
"""

import html
from collections import defaultdict
from pathlib import Path

from report.md_to_html import color_deltas
from report.parse_report import ParsedCandidate, ParsedReport, parse_report

PAGE_TITLE = "日本株デイクローズ・リサーチ"

_STYLE = """
:root {
  --bg: #fafafa; --surface: #ffffff; --surface-2: #f2f1ee;
  --text: #1a1a1a; --text-muted: #666666; --border: #dddddd;
  --up: #c0392b; --down: #1e8449;
  --buy-bg: #fbeae7; --buy-text: #9c2b1c;
  --sell-bg: #e8f3ec; --sell-text: #1b5e3a;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #121212; --surface: #1c1c1c; --surface-2: #242424;
    --text: #eaeaea; --text-muted: #9a9a9a; --border: #333333;
    --up: #ff7b72; --down: #56d364;
    --buy-bg: #3a1f1c; --buy-text: #ff9e95;
    --sell-bg: #16301f; --sell-text: #7ee2a0;
  }
}
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       max-width: 880px; margin: 0 auto; padding: 16px; line-height: 1.6;
       color: var(--text); background: var(--bg); }
h1 { font-size: 1.4rem; margin-bottom: 4px; }
h2 { font-size: 1.05rem; margin: 1.4em 0 0.6em; }
h3 { font-size: 0.95rem; margin: 1.2em 0 0.4em; color: var(--text-muted); }
.updated { color: var(--text-muted); font-size: 0.85rem; margin-top: 0; }
.latest { background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
          padding: 12px 16px; margin: 16px 0; }
.disclaimer { color: var(--text-muted); font-size: 0.85rem; }
.side-heading { font-size: 0.95rem; font-weight: bold; margin: 1em 0 0.5em;
                padding: 2px 10px; border-radius: 6px; display: inline-block; }
.side-heading.buy { background: var(--buy-bg); color: var(--buy-text); }
.side-heading.sell { background: var(--sell-bg); color: var(--sell-text); }
.stat-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 12px; }
.stat-tile { background: var(--surface-2); border-radius: 6px; padding: 8px 10px; }
.stat-tile .cap { font-size: 0.75rem; color: var(--text-muted); display: block; }
.stat-tile .val { font-size: 1.05rem; font-weight: bold; }
.card-grid { display: grid; gap: 10px; margin-bottom: 1em; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; }
.card.rank1.buy { border-color: var(--buy-text); border-width: 2px; }
.card.rank1.sell { border-color: var(--sell-text); border-width: 2px; }
.card > summary { list-style: none; cursor: pointer; padding: 10px 14px; font-weight: normal; }
.card > summary::-webkit-details-marker { display: none; }
.card-head { display: flex; align-items: center; gap: 8px; }
.rank-badge { width: 20px; height: 20px; border-radius: 50%; background: var(--surface-2);
              color: var(--text-muted); font-size: 0.75rem; font-weight: bold;
              display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.card-name { font-weight: bold; font-size: 0.95rem; }
.side-badge { margin-left: auto; font-size: 0.7rem; padding: 2px 8px; border-radius: 6px;
              font-weight: bold; white-space: nowrap; }
.side-badge.buy { background: var(--buy-bg); color: var(--buy-text); }
.side-badge.sell { background: var(--sell-bg); color: var(--sell-text); }
.card-price { font-size: 1.2rem; font-weight: bold; margin: 6px 0 2px; }
.card-reasons { font-size: 0.85rem; color: var(--text-muted); margin: 0; font-weight: normal; }
.card-expand-hint { font-size: 0.75rem; color: var(--text-muted); margin: 6px 0 0; }
.card-detail { border-top: 1px solid var(--border); padding: 10px 14px 12px; font-size: 0.85rem; }
.card-detail .day-summary { color: var(--text-muted); margin: 0 0 6px; }
.card-detail .one-point { margin: 0; }
.card-detail .one-point-label { font-weight: bold; margin-right: 4px; }
.empty-msg { color: var(--text-muted); font-size: 0.9rem; }
.history-layout { display: flex; gap: 20px; align-items: flex-start; }
.history-nav { flex: 0 0 130px; position: sticky; top: 12px; display: flex;
               flex-direction: column; gap: 4px; }
.history-nav a { font-size: 0.85rem; color: var(--text); text-decoration: none;
                  padding: 4px 8px; border-radius: 6px; }
.history-nav a:hover { background: var(--surface-2); }
.history-content { flex: 1; min-width: 0; }
.month-section { margin-bottom: 1.2em; }
details.day { margin: 8px 0; border: 1px solid var(--border); border-radius: 6px; padding: 8px 12px; }
details.day > summary { cursor: pointer; font-weight: bold; }
details.day > .latest { border: none; padding: 0; margin: 8px 0 0; }
@media (max-width: 640px) {
  .history-layout { flex-direction: column; }
  .history-nav { flex-direction: row; overflow-x: auto; position: static;
                 width: 100%; padding-bottom: 6px; gap: 6px; }
  .history-nav a { flex: 0 0 auto; border: 1px solid var(--border); white-space: nowrap; }
}
"""


def _stat_row(lines: list[str]) -> str:
    tiles = []
    for line in lines:
        if ":" in line:
            cap, val = line.split(":", 1)
        else:
            cap, val = "", line
        tiles.append(
            f'<div class="stat-tile"><span class="cap">{html.escape(cap.strip())}</span>'
            f'<span class="val">{color_deltas(html.escape(val.strip()))}</span></div>'
        )
    return f'<div class="stat-row">{"".join(tiles)}</div>'


def _candidate_card(c: ParsedCandidate, side: str) -> str:
    rank1_class = f" rank1 {side}" if c.rank == 1 else ""
    side_label = "買い" if side == "buy" else "売り"
    reasons_html = ""
    if c.reasons:
        reasons_text = " / ".join(color_deltas(html.escape(r)) for r in c.reasons)
        reasons_html = f'<p class="card-reasons">{reasons_text}</p>'

    detail_html = ""
    expand_hint_html = ""
    if c.day_summary or c.one_point:
        day_summary_html = (
            f'<p class="day-summary">{color_deltas(html.escape(c.day_summary))}</p>'
            if c.day_summary
            else ""
        )
        one_point_html = (
            f'<p class="one-point"><span class="one-point-label">ワンポイント:</span>'
            f"{html.escape(c.one_point)}</p>"
            if c.one_point
            else ""
        )
        detail_html = f'<div class="card-detail">{day_summary_html}{one_point_html}</div>'
        expand_hint_html = '<p class="card-expand-hint">タップで当日の値動きを見る</p>'

    return f"""<details class="card{rank1_class}">
<summary>
<div class="card-head">
<span class="rank-badge">{c.rank}</span>
<span class="card-name">{html.escape(c.name)}（{html.escape(c.code)}）</span>
<span class="side-badge {side}">{side_label}・スコア{c.score}</span>
</div>
<p class="card-price">{html.escape(c.entry_price)}</p>
{reasons_html}
{expand_hint_html}
</summary>
{detail_html}
</details>"""


def _side_section(
    heading: str, side: str, stats_lines: list[str], candidates: list[ParsedCandidate]
) -> str:
    parts = [f'<h2 class="side-heading {side}">{heading}</h2>']
    if stats_lines:
        parts.append(_stat_row(stats_lines))
    if candidates:
        cards = "".join(_candidate_card(c, side) for c in candidates)
        parts.append(f'<div class="card-grid">{cards}</div>')
    else:
        parts.append('<p class="empty-msg">本日は基準を満たす候補がありませんでした。</p>')
    return "".join(parts)


def _render_report(parsed: ParsedReport) -> str:
    out = _side_section("買い候補", "buy", parsed.buy_stats_lines, parsed.buy_candidates)
    if parsed.has_sell_section:
        out += _side_section("売り候補", "sell", parsed.sell_stats_lines, parsed.sell_candidates)
    return out


def _month_label(year_month: str) -> str:
    year, month = year_month.split("-")
    return f"{year}年{int(month)}月"


def build_index(reports_dir: Path, docs_dir: Path, generated_at: str) -> Path:
    docs_dir.mkdir(parents=True, exist_ok=True)

    report_files = sorted(reports_dir.glob("*.md"), reverse=True)

    latest_html = ""
    history_by_month: dict[str, list[str]] = defaultdict(list)

    for i, path in enumerate(report_files):
        parsed = parse_report(path.read_text(encoding="utf-8"))
        body = _render_report(parsed)
        if i == 0:
            latest_html = f'<div class="latest">{body}</div>'
        else:
            year_month = path.stem[:7]
            history_by_month[year_month].append(
                f'<details class="day"><summary>{path.stem}</summary>'
                f'<div class="latest">{body}</div></details>'
            )

    if not report_files:
        latest_html = "<p>まだレポートが生成されていません。</p>"

    history_section = "<p>履歴なし</p>"
    if history_by_month:
        months = sorted(history_by_month.keys(), reverse=True)
        nav_links = "".join(
            f'<a href="#m-{ym}">{_month_label(ym)}</a>' for ym in months
        )
        month_sections = "".join(
            f'<section class="month-section" id="m-{ym}"><h3>{_month_label(ym)}</h3>'
            f'{"".join(history_by_month[ym])}</section>'
            for ym in months
        )
        history_section = f"""<div class="history-layout">
<nav class="history-nav">{nav_links}</nav>
<div class="history-content">{month_sections}</div>
</div>"""

    page = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{PAGE_TITLE}</title>
<style>{_STYLE}</style>
</head>
<body>
<h1>{PAGE_TITLE}</h1>
<p class="updated">最終更新: {html.escape(generated_at)}</p>
<p class="disclaimer">本ページは根拠付きスコアリングによる分析結果であり、翌日の値動きや勝率を保証するものではありません。実発注は行っていません（デモ検証フェーズ）。</p>
{latest_html}
<h2>過去のレポート</h2>
{history_section}
</body>
</html>
"""

    index_path = docs_dir / "index.html"
    index_path.write_text(page, encoding="utf-8")
    return index_path
