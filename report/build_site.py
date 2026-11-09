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
import re
from collections import defaultdict
from pathlib import Path

from report.md_to_html import color_deltas
from analysis.miss_analysis import build_suggestion, count_causes
from report.parse_report import ParsedCandidate, ParsedMiss, ParsedReport, ParsedUnfilled, parse_report

PAGE_TITLE = "日本株デイクローズ・リサーチ"

_STYLE = """
:root {
  --bg: #f4f3ef; --surface: #ffffff; --surface-2: #f2f1ed;
  --text: #1c1d21; --text-muted: #6b6e76; --border: #e3e1da;
  --ink: #23283a; --accent: #3b4a7a;
  --up: #c0392b; --down: #1e8449;
  --buy: #d4483b; --buy-bg: #fdecea; --buy-text: #a93226;
  --sell: #239a5b; --sell-bg: #e6f4ec; --sell-text: #1b6b40;
  --shadow: 0 1px 2px rgba(20,24,40,.06), 0 4px 14px rgba(20,24,40,.05);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0e1013; --surface: #171a1f; --surface-2: #1f2329;
    --text: #e9eaee; --text-muted: #9a9ea8; --border: #2a2e36;
    --ink: #e9eaee; --accent: #8fa2e8;
    --up: #ff7b72; --down: #56d364;
    --buy: #ff6b5e; --buy-bg: #3a1f1c; --buy-text: #ff9e95;
    --sell: #3fcf7f; --sell-bg: #16301f; --sell-text: #7ee2a0;
    --shadow: 0 1px 2px rgba(0,0,0,.4), 0 6px 18px rgba(0,0,0,.3);
  }
}
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Noto Sans JP", "Yu Gothic UI", "Segoe UI", sans-serif;
       max-width: 1040px; margin: 0 auto; padding: 0 16px 48px; line-height: 1.6;
       color: var(--text); background: var(--bg); font-variant-numeric: tabular-nums; }
.hero { padding: 28px 4px 18px; }
.hero .eyebrow { font-size: 0.7rem; letter-spacing: .18em; color: var(--accent); font-weight: bold; margin: 0 0 6px; }
.hero h1 { font-size: 1.4rem; line-height: 1.25; margin: 0; color: var(--ink); letter-spacing: .01em; }
.hero .meta { display: flex; flex-wrap: wrap; gap: 8px; margin: 14px 0 0; }
.pill { font-size: 0.78rem; padding: 4px 11px; border-radius: 999px; background: var(--surface);
        border: 1px solid var(--border); color: var(--text-muted); box-shadow: var(--shadow); }
.pill b { color: var(--text); font-weight: 700; margin-left: 4px; }
.disclaimer { margin: 14px 0 0; padding: 10px 14px; font-size: 0.78rem; line-height: 1.55; color: var(--text-muted);
              background: var(--surface); border: 1px solid var(--border); border-left: 3px solid var(--accent); border-radius: 8px; }
h2.section-title { font-size: 1.05rem; margin: 34px 4px 12px; color: var(--ink); }
h3 { font-size: 0.9rem; margin: 1.2em 0 0.5em; color: var(--text-muted); }
.seg-nav { position: sticky; top: 0; z-index: 5; display: flex; gap: 8px; padding: 10px 0; margin: 4px 0 8px;
           background: linear-gradient(var(--bg) 78%, transparent); }
.seg-nav a { flex: 1; text-align: center; text-decoration: none; font-size: 0.9rem; font-weight: bold; padding: 9px 0;
             border-radius: 999px; border: 1px solid var(--border); background: var(--surface); color: var(--text); box-shadow: var(--shadow); }
.seg-nav a.buy { color: var(--buy-text); } .seg-nav a.sell { color: var(--sell-text); }
.sides { display: grid; gap: 22px; }
.side { scroll-margin-top: 64px; }
.side-head { display: flex; align-items: center; gap: 10px; margin: 6px 2px 12px; }
.side-title { font-size: 1.15rem; font-weight: 800; margin: 0; }
.side.buy .side-title { color: var(--buy-text); } .side.sell .side-title { color: var(--sell-text); }
.side-head::before { content: ""; width: 5px; height: 22px; border-radius: 3px; }
.side.buy .side-head::before { background: var(--buy); } .side.sell .side-head::before { background: var(--sell); }
.side-sub { margin-left: auto; font-size: 0.75rem; color: var(--text-muted); }
.stat-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 12px; }
.stat-tile { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 10px 12px; box-shadow: var(--shadow); }
.stat-tile.feature { grid-column: 1 / -1; }
.stat-tile .cap { font-size: 0.72rem; color: var(--text-muted); display: block; }
.stat-tile .val { font-size: 1.35rem; font-weight: 800; line-height: 1.25; color: var(--ink); }
.stat-tile .sub { display: inline-block; white-space: nowrap; font-size: 0.78rem; font-weight: normal; color: var(--text-muted); margin-left: 4px; }
.stat-tile .bar { height: 6px; border-radius: 3px; background: var(--surface-2); margin-top: 8px; overflow: hidden; }
.stat-tile .bar > i { display: block; height: 100%; border-radius: 3px; }
.side.buy .bar > i { background: var(--buy); } .side.sell .bar > i { background: var(--sell); }
.unfilled { margin: 0 0 14px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface-2); }
.unfilled > summary { display: flex; align-items: center; justify-content: space-between; gap: 8px;
                      cursor: pointer; padding: 10px 12px; font-size: 0.95rem; font-weight: bold; list-style: none; }
.unfilled > summary::-webkit-details-marker { display: none; }
.unfilled > summary::after { content: "▾"; color: var(--text-muted); transition: transform .15s; }
.unfilled[open] > summary::after { transform: rotate(180deg); }
.unfilled .uf-count { margin-left: auto; font-weight: normal; color: var(--text-muted); font-size: 0.85rem; }
.unfilled .uf-help { margin: 0; padding: 0 12px 10px; font-size: 0.8rem; color: var(--text-muted); line-height: 1.5; }
.unfilled .uf-list { max-height: 480px; overflow-y: auto; border-top: 1px solid var(--border); }
.unfilled .uf-group-head { position: sticky; top: 0; z-index: 1; margin: 0; padding: 6px 12px; font-size: 0.78rem;
                           font-weight: bold; color: var(--text-muted); background: var(--surface-2);
                           border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; }
.unfilled .uf-row { padding: 9px 12px; border-bottom: 1px solid var(--border); background: var(--surface); }
.unfilled .uf-row:last-child { border-bottom: 0; }
.unfilled .uf-main { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.unfilled .uf-name { font-weight: bold; font-size: 0.95rem; }
.unfilled .uf-gap { flex: none; font-size: 0.8rem; font-weight: bold; padding: 2px 8px; border-radius: 999px;
                    background: var(--surface-2); border: 1px solid var(--border); white-space: nowrap; }
.unfilled .uf-compare { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 8px; margin-top: 4px; font-size: 0.85rem; }
.unfilled .uf-compare .uf-arrow { color: var(--text-muted); }
.unfilled .uf-compare .uf-lbl { color: var(--text-muted); font-size: 0.75rem; margin-right: 2px; }
.unfilled .uf-note { margin-top: 2px; font-size: 0.8rem; color: var(--text-muted); }
.unfilled .mi-chips { padding: 0 12px 8px; }
.unfilled .mi-summary { margin: 0; padding: 0 12px 8px; display: flex; flex-wrap: wrap; gap: 5px; }
.unfilled .mi-suggest { margin: 0; padding: 8px 12px 12px; font-size: 0.82rem; line-height: 1.55; border-top: 1px solid var(--border); }
.card-grid { display: grid; gap: 10px; margin-bottom: 1em; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; box-shadow: var(--shadow);
        transition: transform .12s ease, box-shadow .12s ease; }
.card:hover { transform: translateY(-1px); }
.card.rank1.buy { border-color: var(--buy); box-shadow: 0 0 0 1px var(--buy), var(--shadow); }
.card.rank1.sell { border-color: var(--sell); box-shadow: 0 0 0 1px var(--sell), var(--shadow); }
.card > summary { list-style: none; cursor: pointer; padding: 12px 14px; font-weight: normal; }
.card > summary::-webkit-details-marker { display: none; }
.card-head { display: flex; align-items: center; gap: 10px; }
.rank-badge { width: 26px; height: 26px; border-radius: 8px; background: var(--surface-2);
              color: var(--text-muted); font-size: 0.82rem; font-weight: 800;
              display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.card.rank1.buy .rank-badge { background: var(--buy); color: #fff; }
.card.rank1.sell .rank-badge { background: var(--sell); color: #fff; }
.card-name { font-weight: 700; font-size: 0.97rem; line-height: 1.35; }
.side-badge { margin-left: auto; font-size: 0.7rem; padding: 3px 9px; border-radius: 999px;
              font-weight: 800; white-space: nowrap; }
.side-badge.buy { background: var(--buy-bg); color: var(--buy-text); }
.side-badge.sell { background: var(--sell-bg); color: var(--sell-text); }
.card-price { margin: 8px 0 6px; font-size: 1.45rem; font-weight: 800; color: var(--ink); line-height: 1.2; }
.card-price::before { content: "参考指値"; display: block; font-size: 0.68rem; font-weight: normal; color: var(--text-muted); letter-spacing: .04em; }
.chips { display: flex; flex-wrap: wrap; gap: 5px; margin: 0; }
.chip { font-size: 0.74rem; line-height: 1.35; padding: 3px 9px; border-radius: 999px; background: var(--surface-2);
        color: var(--text-muted); border: 1px solid var(--border); }
.card-expand-hint { font-size: 0.72rem; color: var(--text-muted); margin: 8px 0 0; display: flex; align-items: center; gap: 4px; }
.card-expand-hint::after { content: "▾"; transition: transform .15s; }
.card[open] .card-expand-hint::after { transform: rotate(180deg); }
.card-detail { border-top: 1px dashed var(--border); padding: 12px 14px 14px; font-size: 0.85rem; }
.card-detail .day-summary { color: var(--text-muted); margin: 0 0 8px; }
.card-detail .one-point { margin: 0; }
.card-detail .one-point-label { font-weight: bold; margin-right: 4px; }
.card-detail .outlook { margin: 10px 0 0; padding: 9px 12px; border-left: 4px solid var(--up); background: var(--surface-2); border-radius: 6px; }
.card-detail .outlook.sell { border-left-color: var(--down); }
.card-detail .outlook-label { display: block; font-weight: bold; font-size: .82em; margin-bottom: 2px; }
.empty-msg { color: var(--text-muted); font-size: 0.9rem; padding: 14px; background: var(--surface); border: 1px dashed var(--border); border-radius: 12px; }
.history-head { display: flex; align-items: baseline; justify-content: space-between; margin: 34px 4px 10px; }
.history-head .section-title { margin: 0; }
.history-head .count { font-size: 0.78rem; color: var(--text-muted); }
.month-tabs { display: flex; gap: 8px; overflow-x: auto; padding: 2px 2px 10px; scrollbar-width: none; }
.month-tabs::-webkit-scrollbar { display: none; }
.month-tabs a { flex: 0 0 auto; font-size: 0.85rem; font-weight: 700; text-decoration: none; padding: 7px 14px; border-radius: 999px;
                border: 1px solid var(--border); background: var(--surface); color: var(--text-muted); }
.month-tabs a.active { background: var(--ink); border-color: var(--ink); color: var(--bg); }
.js .month-panel { display: none; }
.js .month-panel.active { display: block; }
.month-label { font-size: 0.85rem; color: var(--text-muted); margin: 14px 4px 8px; }
.js .month-label { display: none; }
.day-list { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; box-shadow: var(--shadow); overflow: hidden; }
details.day-row { border-bottom: 1px solid var(--border); }
details.day-row:last-child { border-bottom: 0; }
details.day-row > summary { list-style: none; cursor: pointer; display: grid; grid-template-columns: 64px 1fr 16px; align-items: center;
                            gap: 10px; padding: 11px 14px; }
details.day-row > summary::-webkit-details-marker { display: none; }
details.day-row > summary::after { content: "▾"; color: var(--text-muted); font-size: 0.8rem; transition: transform .15s; }
details.day-row[open] > summary::after { transform: rotate(180deg); }
details.day-row[open] > summary { background: var(--surface-2); }
details.day-row > summary:hover { background: var(--surface-2); }
.d-date { font-weight: 800; font-size: 1rem; color: var(--ink); line-height: 1.2; }
.d-date small { display: block; font-size: 0.68rem; font-weight: normal; color: var(--text-muted); }
.d-picks { display: flex; flex-direction: column; gap: 3px; min-width: 0; font-size: 0.82rem; }
.pk { display: flex; align-items: center; gap: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pk i { flex: none; font-style: normal; font-size: 0.68rem; font-weight: 800; padding: 1px 7px; border-radius: 999px; }
.pk.buy i { background: var(--buy-bg); color: var(--buy-text); }
.pk.sell i { background: var(--sell-bg); color: var(--sell-text); }
.pk em { font-style: normal; color: var(--text-muted); font-size: 0.74rem; }
.pk.none { color: var(--text-muted); }
details.day-row > .report { padding: 14px; background: var(--bg); border-top: 1px solid var(--border); }
@media (min-width: 860px) {
  .sides { grid-template-columns: 1fr 1fr; align-items: start; }
  .seg-nav { display: none; }
  .hero h1 { font-size: 2rem; }
}
@media (min-width: 420px) {
  .hero h1 { font-size: 1.65rem; }
}
"""


_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def _stat_row(lines: list[str]) -> str:
    tiles = []
    for line in lines:
        if ":" in line:
            cap, val = line.split(":", 1)
        else:
            cap, val = "", line
        cap, val = cap.strip(), val.strip()
        main, sub = val, ""
        if "（" in val:
            main, rest = val.split("（", 1)
            sub = "（" + rest
        bar = ""
        feature = ""
        pct = _PCT_RE.search(val) if "的中率" in cap else None
        if pct:
            feature = " feature"
            width = max(0.0, min(100.0, float(pct.group(1))))
            bar = f'<div class="bar"><i style="width:{width:.1f}%"></i></div>'
        sub_html = f'<span class="sub">{html.escape(sub)}</span>' if sub else ""
        tile = (
            f'<div class="stat-tile{feature}"><span class="cap">{html.escape(cap)}</span>'
            f'<span class="val">{color_deltas(html.escape(main.strip()))}{sub_html}</span>{bar}</div>'
        )
        tiles.append((0 if feature else 1, tile))
    tiles.sort(key=lambda t: t[0])  # 的中率を先頭の大きなタイルにする
    return f'<div class="stat-row">{"".join(t for _, t in tiles)}</div>'


def _candidate_card(c: ParsedCandidate, side: str) -> str:
    rank1_class = f" rank1 {side}" if c.rank == 1 else ""
    side_label = "買い" if side == "buy" else "売り"
    reasons_html = ""
    if c.reasons:
        chips = "".join(
            f'<span class="chip">{color_deltas(html.escape(r))}</span>' for r in c.reasons
        )
        reasons_html = f'<p class="chips">{chips}</p>'

    detail_html = ""
    expand_hint_html = ""
    if c.day_summary or c.one_point or c.outlook:
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
        outlook_html = (
            f'<p class="outlook {side}"><span class="outlook-label">明日の見通し</span>'
            f"{html.escape(c.outlook)}</p>"
            if c.outlook
            else ""
        )
        detail_html = (
            f'<div class="card-detail">{day_summary_html}{one_point_html}{outlook_html}</div>'
        )
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


_REASON_RE = re.compile(
    r"対象日の(安値|高値)([\d,.]+)円が参考指値([\d,.]+)円まで(?:下がらず|上がらず)"
    r"（差([\d,.]+)円・([\d.]+)%）"
)


def _short_date(iso: str) -> str:
    """2026-11-05 -> 11/05"""
    return iso[5:].replace("-", "/")


def _unfilled_row(u: ParsedUnfilled) -> str:
    m = _REASON_RE.search(u.reason)
    if m:
        kind, extreme, entry, gap_yen, gap_pct = m.groups()
        verb = "下がらず" if kind == "安値" else "上がらず"
        compare = (
            f'<div class="uf-compare"><span><span class="uf-lbl">参考指値</span>{entry}円</span>'
            f'<span class="uf-arrow">⇄</span>'
            f'<span><span class="uf-lbl">当日の{kind}</span>{extreme}円</span></div>'
        )
        gap_badge = f'<span class="uf-gap">あと{gap_pct}%</span>'
        note = f'<div class="uf-note">指値まで{gap_yen}円{verb}（届かず不成立）</div>'
    else:  # 想定外の文面は理由をそのまま表示する
        compare = f'<div class="uf-compare"><span>参考指値 {html.escape(u.entry_price)}</span></div>'
        gap_badge = ""
        note = f'<div class="uf-note">{html.escape(u.reason)}</div>'
    return (
        f'<div class="uf-row" title="{html.escape(u.reason, quote=True)}">'
        f'<div class="uf-main"><span class="uf-name">{html.escape(u.name)}</span>{gap_badge}</div>'
        f"{compare}{note}</div>"
    )


def _unfilled_block(items: list[ParsedUnfilled]) -> str:
    if not items:
        return ""
    groups: dict[tuple[str, str], list[ParsedUnfilled]] = {}
    for u in items:  # 入力は新しい予測日順なので、挿入順がそのまま新しい順になる
        groups.setdefault((u.prediction_date, u.target_date), []).append(u)
    body = "".join(
        f'<section class="uf-group"><h4 class="uf-group-head">'
        f"<span>{html.escape(pd)} 予測 → {html.escape(_short_date(td))} 向け</span>"
        f"<span>{len(rows)}件</span></h4>"
        f'{"".join(_unfilled_row(u) for u in rows)}</section>'
        for (pd, td), rows in groups.items()
    )
    return (
        f'<details class="unfilled"><summary><span>不成立の履歴</span>'
        f'<span class="uf-count">{len(items)}件</span></summary>'
        f'<p class="uf-help">参考指値で約定しなかった予測の一覧です。'
        f"買いは当日の安値が指値まで下がらなかったとき、売りは当日の高値が指値まで上がらなかったときに不成立になります。"
        f"「あと◯%」は、指値に届くまでの差（指値比）です。</p>"
        f'<div class="uf-list">{body}</div></details>'
    )


def _miss_row(m: ParsedMiss) -> str:
    chips = "".join(f'<span class="chip">{html.escape(c)}</span>' for c in m.causes)
    return (
        f'<div class="uf-row">'
        f'<div class="uf-main"><span class="uf-name">{html.escape(m.name)}</span>'
        f'<span class="uf-gap">{html.escape(m.result_return)}</span></div>'
        f'<p class="chips mi-chips">{chips}</p>'
        f'<div class="uf-note">{html.escape(m.detail)}</div></div>'
    )


def _miss_block(items: list[ParsedMiss]) -> str:
    if not items:
        return ""
    groups: dict[tuple[str, str], list[ParsedMiss]] = {}
    for m in items:  # 入力は新しい予測日順
        groups.setdefault((m.prediction_date, m.target_date), []).append(m)
    tag_lists = [m.causes for m in items]
    summary_chips = "".join(
        f'<span class="chip">{html.escape(tag)} {n}件</span>' for tag, n in count_causes(tag_lists)
    )
    body = "".join(
        f'<section class="uf-group"><h4 class="uf-group-head">'
        f"<span>{html.escape(pd)} 予測 → {html.escape(_short_date(td))} 向け</span>"
        f"<span>{len(rows)}件</span></h4>"
        f'{"".join(_miss_row(m) for m in rows)}</section>'
        for (pd, td), rows in groups.items()
    )
    return (
        f'<details class="unfilled misses"><summary><span>不的中の履歴</span>'
        f'<span class="uf-count">{len(items)}件</span></summary>'
        f'<p class="uf-help">約定したものの、的中しなかった予測の一覧です。原因は、翌営業日の地合い・寄り付き・'
        f"予測時の勢いから自動で付けたタグで、複数付くことがあります。"
        f"原因の記録を始めた後の予測だけが対象です。</p>"
        f'<p class="chips mi-summary">{summary_chips}</p>'
        f'<p class="mi-suggest"><b>次回への示唆</b>　{html.escape(build_suggestion(tag_lists))}</p>'
        f'<div class="uf-list">{body}</div></details>'
    )


def _side_section(
    heading: str,
    side: str,
    stats_lines: list[str],
    candidates: list[ParsedCandidate],
    unfilled: list[ParsedUnfilled] | None = None,
    anchor: bool = False,
    missed: list[ParsedMiss] | None = None,
) -> str:
    sub = f"TOP{len(candidates)}" if candidates else ""
    sub_html = f'<span class="side-sub">{sub}</span>' if sub else ""
    parts = [f'<div class="side-head"><h2 class="side-title">{heading}</h2>{sub_html}</div>']
    if stats_lines:
        parts.append(_stat_row(stats_lines))
    parts.append(_unfilled_block(unfilled or []))
    parts.append(_miss_block(missed or []))
    if candidates:
        cards = "".join(_candidate_card(c, side) for c in candidates)
        parts.append(f'<div class="card-grid">{cards}</div>')
    else:
        parts.append('<p class="empty-msg">本日は基準を満たす候補がありませんでした。</p>')
    id_attr = f' id="side-{side}"' if anchor else ""
    return f'<section class="side {side}"{id_attr}>{"".join(parts)}</section>'


def _render_report(parsed: ParsedReport, latest: bool = False) -> str:
    sections = _side_section(
        "買い候補", "buy", parsed.buy_stats_lines, parsed.buy_candidates, parsed.buy_unfilled, latest, parsed.buy_missed
    )
    nav = ""
    if parsed.has_sell_section:
        sections += _side_section(
            "売り候補", "sell", parsed.sell_stats_lines, parsed.sell_candidates, parsed.sell_unfilled, latest, parsed.sell_missed
        )
        if latest:
            nav = (
                '<nav class="seg-nav"><a class="buy" href="#side-buy">買い候補</a>'
                '<a class="sell" href="#side-sell">売り候補</a></nav>'
            )
    return f'{nav}<div class="sides">{sections}</div>'


def _month_label(year_month: str) -> str:
    year, month = year_month.split("-")
    return f"{year}年{int(month)}月"


_WEEKDAYS = "月火水木金土日"


def _day_row(stem: str, parsed: ParsedReport, body: str) -> str:
    from datetime import date

    d = date.fromisoformat(stem)

    def picks(side: str, label: str, cands: list[ParsedCandidate]) -> str:
        if not cands:
            return f'<span class="pk {side} none"><i>{label}</i>候補なし</span>'
        more = f"<em>ほか{len(cands) - 1}</em>" if len(cands) > 1 else ""
        return f'<span class="pk {side}"><i>{label}</i>{html.escape(cands[0].name)}{more}</span>'

    sell = picks("sell", "売", parsed.sell_candidates) if parsed.has_sell_section else ""
    return (
        f'<details class="day-row" name="history"><summary>'
        f'<span class="d-date">{d.month:02d}/{d.day:02d}<small>{d.year} {_WEEKDAYS[d.weekday()]}</small></span>'
        f'<span class="d-picks">{picks("buy", "買", parsed.buy_candidates)}{sell}</span>'
        f'</summary><div class="report">{body}</div></details>'
    )


def build_index(reports_dir: Path, docs_dir: Path, generated_at: str) -> Path:
    docs_dir.mkdir(parents=True, exist_ok=True)

    report_files = sorted(reports_dir.glob("*.md"), reverse=True)

    latest_html = ""
    history_by_month: dict[str, list[str]] = defaultdict(list)

    for i, path in enumerate(report_files):
        parsed = parse_report(path.read_text(encoding="utf-8"))
        body = _render_report(parsed, latest=(i == 0))
        if i == 0:
            latest_html = f'<div class="report latest">{body}</div>'
        else:
            year_month = path.stem[:7]
            history_by_month[year_month].append(_day_row(path.stem, parsed, body))

    if not report_files:
        latest_html = "<p>まだレポートが生成されていません。</p>"

    history_section = "<p>履歴なし</p>"
    history_count = sum(len(v) for v in history_by_month.values())
    if history_by_month:
        months = sorted(history_by_month.keys(), reverse=True)
        tabs = "".join(
            f'<a href="#m-{ym}" data-month="{ym}">{_month_label(ym)}</a>' for ym in months
        )
        panels = "".join(
            f'<section class="month-panel" id="m-{ym}" data-month="{ym}">'
            f'<h3 class="month-label">{_month_label(ym)}</h3>'
            f'<div class="day-list">{"".join(history_by_month[ym])}</div></section>'
            for ym in months
        )
        history_section = f'<nav class="month-tabs">{tabs}</nav>{panels}'

    latest_pill = (
        f'<span class="pill">最新レポート<b>{html.escape(report_files[0].stem)}</b></span>'
        if report_files
        else ""
    )

    page = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{PAGE_TITLE}</title>
<script>document.documentElement.classList.add("js")</script>
<style>{_STYLE}</style>
</head>
<body>
<header class="hero">
<p class="eyebrow">DAY-CLOSE RESEARCH</p>
<h1>{PAGE_TITLE}</h1>
<div class="meta">{latest_pill}<span class="pill">最終更新<b>{html.escape(generated_at)}</b></span></div>
<p class="disclaimer">本ページは根拠付きスコアリングによる分析結果であり、翌日の値動きや勝率を保証するものではありません。実発注は行っていません（デモ検証フェーズ）。</p>
</header>
{latest_html}
<div class="history-head"><h2 class="section-title">過去のレポート</h2><span class="count">{history_count}日分</span></div>
{history_section}
<script>
(function () {{
  var tabs = document.querySelectorAll('.month-tabs a');
  var panels = document.querySelectorAll('.month-panel');
  function show(m) {{
    panels.forEach(function (p) {{ p.classList.toggle('active', p.dataset.month === m); }});
    tabs.forEach(function (t) {{ t.classList.toggle('active', t.dataset.month === m); }});
  }}
  tabs.forEach(function (t) {{
    t.addEventListener('click', function (e) {{ e.preventDefault(); show(t.dataset.month); }});
  }});
  if (tabs.length) show(tabs[0].dataset.month);
}})();
</script>
</body>
</html>
"""

    index_path = docs_dir / "index.html"
    index_path.write_text(page, encoding="utf-8")
    return index_path
