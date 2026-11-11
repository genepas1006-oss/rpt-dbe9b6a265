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
import json
import re
from collections import defaultdict
from pathlib import Path

from datetime import date

from html import unescape as html_module_unescape

from analysis.market_calendar import next_business_day
from report.forecast_set import ForecastSet, evening_set, fmt_md_hm, to_json_dict
from report.glossary import terms_in
from report.md_to_html import color_deltas
from report.premarket import Premarket, load_premarket
from tracking.virtual_fund import VirtualFund
from analysis.miss_analysis import build_suggestion, count_causes
from report.parse_report import (
    ParsedCandidate,
    ParsedMiss,
    ParsedPrevious,
    ParsedReport,
    ParsedUnfilled,
    parse_report,
)

PAGE_TITLE = "日本株デイクローズ・リサーチ"

_FSET_SCRIPT = r"""
(function () {
  var el = document.getElementById('fsets');
  if (!el) return;
  var sets = [];
  try { sets = JSON.parse(el.textContent); } catch (e) { return; }
  var byId = {};
  sets.forEach(function (s) { byId[s.id] = s; });
  var tHM = new Intl.DateTimeFormat('ja-JP', {timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit', hour12: false});
  var tD = new Intl.DateTimeFormat('en-CA', {timeZone: 'Asia/Tokyo', year: 'numeric', month: '2-digit', day: '2-digit'});
  var tW = new Intl.DateTimeFormat('en-US', {timeZone: 'Asia/Tokyo', weekday: 'short'});
  var tMD = new Intl.DateTimeFormat('ja-JP', {timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric'});
  function hm(ms) { return tHM.format(new Date(ms)); }
  function md(ms) { return tMD.format(new Date(ms)); }
  function dur(ms) { var m = Math.max(1, Math.ceil(ms / 60000)); if (m < 60) return m + '分'; var h = Math.floor(m / 60); return h + '時間' + (m % 60 ? (m % 60) + '分' : ''); }
  function state(s, now) {
    var f = Date.parse(s.valid_from), u = Date.parse(s.valid_until);
    if (now < f) return {k: 'waiting', ms: f - now, from: f, until: u};
    if (now < u) return {k: 'active', ms: u - now, from: f, until: u};
    return {k: 'expired', ms: 0, from: f, until: u};
  }
  function update() {
    var now = Date.now();
    var last = {};
    document.querySelectorAll('.fset').forEach(function (h) {
      var s = byId[h.getAttribute('data-id')];
      if (!s) return;
      var r = state(s, now);
      var badge = h.querySelector('.fset-state');
      badge.textContent = r.k === 'active' ? '🟢 有効（あと' + dur(r.ms) + '）'
        : r.k === 'waiting' ? '🟡 待機（' + md(r.from) + ' ' + hm(r.from) + 'から・あと' + dur(r.ms) + '）' : '⚪ 期限切れ';
      h.classList.remove('is-active', 'is-waiting', 'is-expired');
      h.classList.add('is-' + r.k);
      last[s.id] = r.k;
    });
    document.querySelectorAll('.fset-body').forEach(function (d) {
      var k = last[d.getAttribute('data-id')];
      if (!k) return;
      d.classList.toggle('is-expired', k === 'expired');
      if (d.getAttribute('data-k') !== k) { d.open = (k !== 'expired'); d.setAttribute('data-k', k); }
    });
    var banner = document.getElementById('now-banner'), text = document.getElementById('nb-text');
    if (!banner || !text) return;
    var active = sets.filter(function (s) { return state(s, now).k === 'active'; })
      .sort(function (a, b) { return (b.created_at || b.valid_from) < (a.created_at || a.valid_from) ? -1 : 1; })[0];
    var waiting = sets.filter(function (s) { return state(s, now).k === 'waiting'; })
      .sort(function (a, b) { return Date.parse(a.valid_from) - Date.parse(b.valid_from); })[0];
    var clock = '<span class="nb-clock">現在 ' + hm(now) + '（日本時間）</span> ／ ';
    var msg, cls;
    if (active) {
      var ra = state(active, now);
      msg = clock + '<b>' + active.label + '</b>が有効です（' + hm(ra.until) + 'まで・あと' + dur(ra.ms) + '）。' + active.note;
      cls = 'is-active';
    } else if (waiting) {
      var rw = state(waiting, now);
      msg = clock + '<b>' + waiting.label + '</b>は ' + md(rw.from) + ' ' + hm(rw.from) + ' から有効です（あと' + dur(rw.ms) + '）。それまでは、この予想で売買しないでください。';
      cls = 'is-waiting';
    } else {
      msg = clock + '<b>現在、有効な予想はありません。</b>下の予想は期限切れです（前日夜の予想は前場向けで、後場の売買には使えません）。'
        + '後場向けの予想は、現時点では出していません。次の更新で新しい予想が出ます（目安: 平日16:10）。';
      cls = 'is-none';
    }
    var today = tD.format(new Date(now)), wd = tW.format(new Date(now));
    var latestTarget = sets.reduce(function (m, s) { return s.target_date > m ? s.target_date : m; }, '');
    var minutes = parseInt(hm(now).slice(0, 2), 10) * 60 + parseInt(hm(now).slice(3, 5), 10);
    if (wd !== 'Sat' && wd !== 'Sun' && minutes >= 540 && minutes < 930 && latestTarget && latestTarget < today) {
      msg += '<span class="nb-alert">本日（' + today + '）向けの予想がまだ反映されていません。表示中の予想は古い情報です（休場日の場合は、この表示は無視してください）。</span>';
    }
    banner.className = 'now-banner ' + cls;
    text.innerHTML = msg;
  }
  update();
  setInterval(update, 30000);
})();
"""

_STYLE = """
:root {
  --bg: #f4f3ef; --surface: #ffffff; --surface-2: #f2f1ed;
  --text: #1c1d21; --text-muted: #6b6e76; --border: #e3e1da;
  --ink: #23283a; --accent: #3b4a7a;
  --win: #2563c9; --win-bg: #e6eefc; --loss: #b45f06; --loss-bg: #fdf0dd; --idle: #6b6e76; --idle-bg: #ecebe6;
  --up: #c0392b; --down: #1e8449;
  --buy: #d4483b; --buy-bg: #fdecea; --buy-text: #a93226;
  --sell: #239a5b; --sell-bg: #e6f4ec; --sell-text: #1b6b40;
  --ok: #1b7a46; --ok-bg: #e3f3ea; --wait: #8a5a00; --wait-bg: #fff2d6; --stale: #6b6e76; --stale-bg: #ecebe6; --alert: #a4262c; --alert-bg: #fde8e8;
  --shadow: 0 1px 2px rgba(20,24,40,.06), 0 4px 14px rgba(20,24,40,.05);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0e1013; --surface: #171a1f; --surface-2: #1f2329;
    --text: #e9eaee; --text-muted: #9a9ea8; --border: #2a2e36;
    --ink: #e9eaee; --accent: #8fa2e8;
    --win: #7aa7ff; --win-bg: #17284a; --loss: #f2b35e; --loss-bg: #3a2a10; --idle: #9a9ea8; --idle-bg: #262a31;
    --up: #ff7b72; --down: #56d364;
    --buy: #ff6b5e; --buy-bg: #3a1f1c; --buy-text: #ff9e95;
    --sell: #3fcf7f; --sell-bg: #16301f; --sell-text: #7ee2a0;
    --ok: #6fd69a; --ok-bg: #12301f; --wait: #f2c26b; --wait-bg: #3a2c0e; --stale: #9a9ea8; --stale-bg: #262a31; --alert: #ff9b9b; --alert-bg: #3b1a1c;
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
.prev { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; box-shadow: var(--shadow); padding: 12px 14px; margin: 0 0 12px; }
.prev-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
.prev-title { font-weight: 800; font-size: 0.95rem; color: var(--ink); }
.prev-sub { font-size: 0.75rem; color: var(--text-muted); }
.prev-score { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.st { font-size: 0.72rem; font-weight: 800; padding: 2px 9px; border-radius: 999px; white-space: nowrap; }
.st.win { background: var(--win-bg); color: var(--win); }
.st.loss { background: var(--loss-bg); color: var(--loss); }
.st.nofill, .st.pending { background: var(--idle-bg); color: var(--idle); }
.prev-row { display: grid; grid-template-columns: 18px auto 1fr auto; align-items: center; gap: 8px; padding: 8px 0; border-top: 1px solid var(--border); }
.prev-row .rk { font-size: 0.75rem; color: var(--text-muted); font-weight: 800; text-align: center; }
.prev-row .pn { min-width: 0; }
.prev-row .pn b { display: block; font-size: 0.9rem; }
.prev-row small { display: block; font-size: 0.72rem; color: var(--text-muted); line-height: 1.4; }
.prev-row .pr { text-align: right; font-weight: 800; font-size: 0.95rem; white-space: nowrap; }
.prev-row.win .pr { color: var(--win); } .prev-row.loss .pr { color: var(--loss); }
.prev-row.nofill .pr, .prev-row.pending .pr { color: var(--idle); font-weight: 600; font-size: 0.8rem; }
.env { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; box-shadow: var(--shadow); padding: 12px 14px; margin: 0 0 14px; }
.env-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; flex-wrap: wrap; margin-bottom: 6px; }
.env-title { font-weight: 800; font-size: 0.95rem; color: var(--ink); }
.env-sub { font-size: 0.74rem; color: var(--text-muted); }
.env-row { display: grid; grid-template-columns: 1fr auto; gap: 2px 10px; align-items: center; padding: 8px 0; border-top: 1px solid var(--border); }
.env-k { font-size: 0.8rem; color: var(--text-muted); grid-column: 1; }
.env-v { font-size: 1.05rem; font-weight: 800; grid-column: 1; line-height: 1.35; }
.env-row .tag { grid-column: 2; grid-row: 1 / span 2; justify-self: end; }
.env-v.small { font-size: 0.85rem; font-weight: 600; }
.env-src { font-size: 0.72rem; color: var(--text-muted); grid-column: 1 / -1; }
.env-note { margin: 6px 0 0; font-size: 0.72rem; color: var(--text-muted); }
.tag { font-size: 0.7rem; font-weight: 800; padding: 2px 9px; border-radius: 999px; white-space: nowrap; }
.tag.fact { background: var(--win-bg); color: var(--win); }
.tag.guess { background: var(--loss-bg); color: var(--loss); }
.tag.unknown { background: var(--idle-bg); color: var(--idle); }
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
.stock-link { color: inherit; text-decoration: underline dotted; text-underline-offset: 3px; }
.stock-link:hover { color: var(--accent); }
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
.fund { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; box-shadow: var(--shadow); padding: 14px 16px; margin: 0 0 18px; }
.fund-head { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
.fund-title { font-size: 0.95rem; font-weight: 800; color: var(--ink); }
.fund-sub { font-size: 0.72rem; color: var(--text-muted); }
.fund-balance { font-size: 1.9rem; font-weight: 800; color: var(--ink); line-height: 1.3; margin: 4px 0 8px; }
.fund-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px; margin-bottom: 10px; }
.fund-stat { background: var(--surface-2); border-radius: 10px; padding: 8px 10px; }
.fund-stat .cap { display: block; font-size: 0.7rem; color: var(--text-muted); }
.fund-stat .val { font-size: 1.05rem; font-weight: 800; color: var(--ink); }
.fund-stat .val small { font-size: 0.74rem; font-weight: normal; color: var(--text-muted); margin-left: 4px; }
.fund-chart { width: 100%; height: 64px; display: block; margin: 4px 0 8px; }
.fund-chart polyline { fill: none; stroke: var(--accent); stroke-width: 2; vector-effect: non-scaling-stroke; }
.fund-chart line { stroke: var(--border); stroke-width: 1; stroke-dasharray: 3 3; vector-effect: non-scaling-stroke; }
.fund-days { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
.fund-days th { text-align: right; font-weight: normal; color: var(--text-muted); padding: 4px 6px; border-bottom: 1px solid var(--border); }
.fund-days td { text-align: right; padding: 5px 6px; border-bottom: 1px solid var(--border); font-variant-numeric: tabular-nums; }
.fund-days th:first-child, .fund-days td:first-child { text-align: left; }
.prev-row .pn small.pn-note { display: block; margin-top: 2px; color: var(--text-muted); font-style: italic; }
.now-banner { margin: 0 0 14px; padding: 10px 14px; border-radius: 12px; border: 1px solid var(--border); background: var(--surface); box-shadow: var(--shadow); font-size: 0.88rem; line-height: 1.6; }
.now-banner .nb-clock { font-weight: 800; color: var(--ink); }
.now-banner.is-active { border-left: 5px solid var(--ok); background: var(--ok-bg); }
.now-banner.is-waiting { border-left: 5px solid var(--wait); background: var(--wait-bg); }
.now-banner.is-none { border-left: 5px solid var(--stale); background: var(--stale-bg); }
.now-banner .nb-alert { display: block; margin-top: 6px; padding: 6px 10px; border-radius: 8px; background: var(--alert-bg); color: var(--alert); font-weight: 700; }
.fset { margin: 0 0 12px; padding: 10px 14px; border-radius: 12px; border: 1px solid var(--border); border-left: 5px solid var(--stale); background: var(--surface); }
.fset.is-active { border-left-color: var(--ok); } .fset.is-waiting { border-left-color: var(--wait); } .fset.is-expired { border-left-color: var(--stale); background: var(--stale-bg); }
.fset-top { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.fset-label { font-size: 1rem; color: var(--ink); }
.fset-state { font-size: 0.78rem; font-weight: 800; padding: 2px 9px; border-radius: 999px; background: var(--stale-bg); color: var(--stale); }
.fset.is-active .fset-state { background: var(--ok-bg); color: var(--ok); } .fset.is-waiting .fset-state { background: var(--wait-bg); color: var(--wait); }
.fset.is-expired .fset-state { background: var(--stale); color: var(--surface); }
.fset-meta { display: flex; flex-wrap: wrap; gap: 4px 14px; margin-top: 4px; font-size: 0.74rem; color: var(--text-muted); }
.fset-note { margin: 6px 0 0; font-size: 0.8rem; color: var(--text); font-weight: 700; }
.fset.is-expired .fset-note { color: var(--alert); }
.fset-body > summary { cursor: pointer; font-size: 0.78rem; color: var(--text-muted); padding: 4px 2px 8px; }
.fset-body.is-expired .sides, .fset-body.is-expired .experiment { opacity: 0.55; }
.fset-body.is-expired .card-price, .fset-body.is-expired .stock-link { text-decoration: line-through; }
.experiment { background: var(--surface-2); border: 1px dashed var(--border); border-radius: 14px; margin: 14px 0; padding: 0 14px; }
.experiment > summary { cursor: pointer; list-style: none; display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 12px 0; font-weight: 800; font-size: 0.95rem; color: var(--ink); }
.experiment > summary::-webkit-details-marker { display: none; }
.experiment > summary::after { content: "▼"; font-size: 0.7rem; color: var(--text-muted); }
.experiment[open] > summary::after { content: "▲"; }
.exp-badge { margin-left: auto; font-size: 0.68rem; font-weight: normal; color: var(--text-muted); border: 1px solid var(--border); border-radius: 999px; padding: 2px 8px; white-space: nowrap; }
.experiment > .uf-help { margin: 0 0 10px; font-size: 0.8rem; line-height: 1.6; color: var(--text-muted); }
.exp-sides { display: grid; gap: 16px; padding-bottom: 14px; }
.exp-col-title { margin: 6px 2px 8px; font-size: 0.95rem; color: var(--text-muted); }
.exp-col.buy .exp-col-title { color: var(--buy-text); } .exp-col.sell .exp-col-title { color: var(--sell-text); }
.mi-review { margin: 6px 0 0; font-size: 0.8rem; line-height: 1.65; color: var(--text); }
.glossary { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; box-shadow: var(--shadow); padding: 4px 16px 14px; margin: 18px 0; }
.glossary dl { margin: 8px 0 0; }
.glossary dt { font-weight: 800; font-size: 0.85rem; color: var(--ink); margin-top: 10px; }
.glossary dd { margin: 2px 0 0; font-size: 0.8rem; line-height: 1.6; color: var(--text-muted); }
.fund-note { margin: 8px 0 0; font-size: 0.72rem; color: var(--text-muted); line-height: 1.5; }
@media (min-width: 860px) {
  .exp-sides { grid-template-columns: 1fr 1fr; align-items: start; }
  /* 買い/売りの各ブロック（見出し・前営業日・成績・履歴・候補）を同じ行に揃える */
  .sides { grid-template-columns: 1fr 1fr; gap: 0 22px; }
  /* 上5ブロック＋候補カード5行 = 10行。カードも順位ごとに左右で同じ高さにする */
  .sides > .side.paired { display: grid; grid-row: span 10; grid-template-rows: subgrid; row-gap: 0; }
  .side.paired > .slot.cards { grid-row: span 5; display: grid; grid-template-rows: subgrid; row-gap: 10px; }
  .side.paired > .slot.cards > .card-grid { display: contents; }
  .side.paired > .slot.cards > .empty-msg { grid-row: 1; }
  .stat-tile .cap { min-height: 2.8em; line-height: 1.4; }
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
        pct = _PCT_RE.search(val) if cap.startswith("的中率") else None
        if pct:
            feature = " feature"
            width = max(0.0, min(100.0, float(pct.group(1))))
            bar = f'<div class="bar"><i style="width:{width:.1f}%"></i></div>'
        sub_html = f'<span class="sub">{html.escape(sub)}</span>' if sub else ""
        # リターン（損益）の符号は、値上がり=赤・値下がり=緑の配色と紛らわしいので色を付けない
        escaped = html.escape(main.strip())
        value_html = escaped if ("リターン" in cap or "全銘柄平均" in cap) else color_deltas(escaped)
        tile = (
            f'<div class="stat-tile{feature}"><span class="cap">{html.escape(cap)}</span>'
            f'<span class="val">{value_html}{sub_html}</span>{bar}</div>'
        )
        tiles.append((0 if feature else 1, tile))
    tiles.sort(key=lambda t: t[0])  # 的中率を先頭の大きなタイルにする
    return f'<div class="stat-row">{"".join(t for _, t in tiles)}</div>'


_CODE_IN_LABEL_RE = re.compile(r"（([0-9A-Z]{4})）\s*$")
YAHOO_CHART_URL = "https://finance.yahoo.co.jp/quote/{code}.T/chart"


def _stock_link(label: str, code: str | None = None) -> str:
    """銘柄名をYahoo!ファイナンスのチャートへのリンクにする。コード（4桁の英数字）が分からなければリンクにしない。"""
    if code is None:
        m = _CODE_IN_LABEL_RE.search(label)
        code = m.group(1) if m else None
    text = html.escape(label)
    if not code or not re.fullmatch(r"[0-9A-Z]{4}", code):
        return text
    url = YAHOO_CHART_URL.format(code=code)
    return f'<a class="stock-link" href="{url}" target="_blank" rel="noopener noreferrer">{text}</a>'


def _yen(v: float, signed: bool = False) -> str:
    return f"{round(v):+,}円" if signed else f"{round(v):,}円"


def _fund_block(fund: VirtualFund | None) -> str:
    """トップページの仮想資金（デモ）。勝敗の色分けはせず、符号付きの数値で示す。"""
    if fund is None:
        return ""
    last = fund.last_day
    if last is None:
        day_stat = '<div class="fund-stat"><span class="cap">前日比</span><span class="val">—</span></div>'
    else:
        day_stat = (
            f'<div class="fund-stat"><span class="cap">前日比（{last.target_date.month}/{last.target_date.day}）</span>'
            f'<span class="val">{_yen(last.pnl, True)}<small>{last.pnl_pct * 100:+.2f}%</small></span></div>'
        )
    buy_total = sum(d.buy_pnl for d in fund.days)
    sell_total = sum(d.sell_pnl for d in fund.days)
    stats = (
        day_stat
        + f'<div class="fund-stat"><span class="cap">開始からの損益</span>'
        f'<span class="val">{_yen(fund.total_pnl, True)}<small>{fund.total_pct * 100:+.2f}%</small></span></div>'
        + f'<div class="fund-stat"><span class="cap">買い・売り別の累計</span>'
        f'<span class="val"><small style="margin:0">買い</small> {_yen(buy_total, True)}'
        f'<br><small style="margin:0">売り</small> {_yen(sell_total, True)}</span></div>'
    )
    chart = ""
    if fund.days:
        values = [fund.initial] + [d.end_balance for d in fund.days]
        lo, hi = min(values), max(values)
        span = (hi - lo) or 1.0
        n = len(values) - 1 or 1
        pts = " ".join(
            f"{i / n * 100:.2f},{(1 - (v - lo) / span) * 56 + 4:.2f}" for i, v in enumerate(values)
        )
        base_y = (1 - (fund.initial - lo) / span) * 56 + 4
        chart = (
            f'<svg class="fund-chart" viewBox="0 0 100 64" preserveAspectRatio="none" role="img" '
            f'aria-label="残高の推移"><line x1="0" y1="{base_y:.2f}" x2="100" y2="{base_y:.2f}"/>'
            f'<polyline points="{pts}"/></svg>'
        )
    rows = "".join(
        f"<tr><td>{d.target_date.month:02d}/{d.target_date.day:02d}</td>"
        f"<td>{_yen(d.pnl, True)}</td><td>{d.pnl_pct * 100:+.2f}%</td><td>{_yen(d.end_balance)}</td></tr>"
        for d in reversed(fund.days[-10:])
    )
    table = (
        '<table class="fund-days"><thead><tr><th>結果日</th><th>損益</th><th>前日比</th><th>残高</th></tr></thead>'
        f"<tbody>{rows}</tbody></table>"
        if rows
        else '<p class="fund-note">最初の答え合わせが済むと、日別の損益と残高をここに表示します。</p>'
    )
    return (
        '<section class="fund"><div class="fund-head"><span class="fund-title">仮想資金（デモ）</span>'
        f'<span class="fund-sub">開始 {_yen(fund.initial)}</span></div>'
        f'<div class="fund-balance">{_yen(fund.balance)}</div>'
        f'<div class="fund-stats">{stats}</div>{chart}{table}'
        '<p class="fund-note">買い・売りの全候補に、毎日「残高÷10」ずつ指値で投入し、約定した分を終値で決済した場合の'
        '参考値です（不成立は現金のまま・複利）。手数料・単元株・信用取引の費用は考慮していません。'
        '実際の損益や将来の成績を保証するものではありません。</p></section>'
    )


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
<span class="card-name">{_stock_link(f"{c.name}（{c.code}）", c.code)}</span>
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
        f'<div class="uf-main"><span class="uf-name">{_stock_link(u.name)}</span>{gap_badge}</div>'
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


def _review_html(review: str) -> str:
    """検証メモを、項目（約定価格・副次要因・次回への検討）ごとに改行して読みやすくする。"""
    return re.sub(r" (約定価格|副次要因:|次回への検討:|日経平均のデータが欠けている)", r"<br>\1", html.escape(review))


def _miss_row(m: ParsedMiss) -> str:
    chips = "".join(f'<span class="chip">{html.escape(c)}</span>' for c in m.causes)
    return (
        f'<div class="uf-row">'
        f'<div class="uf-main"><span class="uf-name">{_stock_link(m.name)}</span>'
        f'<span class="uf-gap">{html.escape(m.result_return)}</span></div>'
        f'<p class="chips mi-chips">{chips}</p>'
        f'<div class="uf-note">{html.escape(m.detail)}</div>'
        + (f'<p class="mi-review">{_review_html(m.review)}</p>' if m.review else "")
        + "</div>"
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
        f"原因の記録を始めた後の予測だけが対象です。"
        f"各予測の「主因」「副次要因」は、値動きの経過とあわせた検証メモです。分からない用語は、ページ内の「用語の説明」をご覧ください。</p>"
        f'<p class="chips mi-summary">{summary_chips}</p>'
        f'<p class="mi-suggest"><b>次回への示唆</b>　{html.escape(build_suggestion(tag_lists))}</p>'
        f'<div class="uf-list">{body}</div></details>'
    )


_STATUS_CLASS = {"的中": "win", "不的中": "loss", "不成立": "nofill", "未確定": "pending"}


def _status_class(label: str) -> str:
    return _STATUS_CLASS.get(label, "pending")


def _env_row(key: str, value: str, tag: str, tag_label: str, source: str, small: bool = False) -> str:
    return (
        f'<div class="env-row"><div class="env-k">{html.escape(key)}</div>'
        f'<div class="env-v{" small" if small else ""}">{value}</div><span class="tag {tag}">{tag_label}</span>'
        f'<div class="env-src">{html.escape(source)}</div></div>'
    )


def _actual_gap_row(pm: Premarket, market_gaps: dict[date, float] | None) -> str:
    """想定ギャップの答え合わせ。実際の値（前日終値→当日始値の225銘柄平均）があれば、想定との差と方向の一致を併記する。"""
    key = "実際のギャップ（日本株全体の平均）"
    actual = (market_gaps or {}).get(pm.for_date)
    if actual is None:
        return _env_row(key, "不明", "unknown", "不明", "寄り付き後（15:35の更新）に反映されます")
    diff = (actual - pm.expected_gap) * 100
    if actual == 0 or pm.expected_gap == 0:
        direction = "判定なし"
    else:
        direction = "一致" if (actual > 0) == (pm.expected_gap > 0) else "不一致"
    return _env_row(
        key,
        color_deltas(html.escape(f"{actual * 100:+.2f}%")),
        "fact",
        "事実",
        f"{pm.for_date.isoformat()}・前日終値→当日始値の225銘柄平均（Yahoo Finance）｜想定との差 {diff:+.1f}ポイント・方向 {direction}",
    )


_NEXT_DAY_UNKNOWN = "翌営業日向けの米国市場の結果は、朝の更新（米国市場の確定後）で反映されます"


def _environment_block(
    pm: Premarket | None, latest_prediction_date: date | None, market_gaps: dict[date, float] | None = None
) -> str:
    """寄り前の環境認識（目安）。事実・推測・不明を区別し、出所と基準日を付ける。

    最新レポートの予測日以前が対象日の値（対象日が過ぎた値）も隠さず、「参考」と明記して残す。
    その場合は、翌営業日向けの欄を「不明（理由）」として別に出す。
    """
    rows = []
    if pm is not None:
        is_current = latest_prediction_date is None or pm.for_date > latest_prediction_date
        sub_title = (
            f"{pm.for_date.isoformat()} 寄り付き前 ／ 売買の助言ではありません"
            if is_current
            else f"{pm.for_date.isoformat()} 寄り付き前の値（対象日は過ぎています・参考） ／ 売買の助言ではありません"
        )
        rows += [
            _env_row(
                "米国（S&P500）前日比",
                color_deltas(html.escape(f"{pm.us_return * 100:+.2f}%")),
                "fact", "事実", f"Yahoo Finance ^GSPC・{pm.us_date.isoformat()} 終値",
            ),
            _env_row(
                "想定ギャップの目安（日本株全体の平均）",
                color_deltas(html.escape(f"約{pm.expected_gap * 100:+.1f}%")),
                "guess", "推測", f"傾き{pm.slope:.2f}×米国前日比・直近{pm.n_fit}営業日の回帰",
            ),
        ]
        if pm.direction_acc is not None and pm.corr is not None and pm.mae is not None and pm.mae_zero is not None:
            accuracy = (
                f"方向一致 {pm.direction_acc * 100:.0f}%・相関 {pm.corr:.2f}・平均誤差 {pm.mae * 100:.2f}%"
                f"（常に0と予測した場合 {pm.mae_zero * 100:.2f}%）"
            )
            src = f"{pm.eval_start}〜{pm.eval_end}（{pm.eval_n}日、各日をその日より前のデータだけで予測）"
            rows.append(_env_row("過去の精度", html.escape(accuracy), "fact", "事実（過去の検証）", src, small=True))
        else:
            rows.append(_env_row("過去の精度", "不明", "unknown", "不明", "検証に必要なデータが足りません"))
        rows.append(_actual_gap_row(pm, market_gaps))
        if not is_current:
            rows.append(_env_row("翌営業日向けの想定ギャップ", "不明", "unknown", "不明", _NEXT_DAY_UNKNOWN))
    else:
        sub_title = "売買の助言ではありません"
        rows.append(
            _env_row("想定ギャップの目安（日本株全体の平均）", "不明", "unknown", "不明", _NEXT_DAY_UNKNOWN)
        )
    rows.append(
        _env_row(
            "PTS・ADR・寄り前気配・適時開示・SNS", "不明", "unknown", "不明", "無料データでは取得できないため"
        )
    )
    return (
        f'<section class="env"><div class="env-head"><span class="env-title">環境認識（目安）</span>'
        f'<span class="env-sub">{html.escape(sub_title)}</span></div>'
        f'<div class="env-rows">{"".join(rows)}</div>'
        f'<p class="env-note">日本株全体の平均の目安であり、個別銘柄の値動きや成績を保証するものではありません。</p>'
        f"</section>"
    )


def _count_chip(text: str) -> str:
    """「的中2」→「的中 2」のチップ。"""
    m = re.match(r"(\D+)(\d+)$", text)
    label, n = (m.group(1), m.group(2)) if m else (text, "")
    return f'<span class="st {_status_class(label)}">{html.escape((label + " " + n).strip())}</span>'


def _previous_block(prev: ParsedPrevious | None) -> str:
    """前営業日の予想と結果。各側の先頭に置き、今日の予想を見る前に前日の勝敗を確認できるようにする。"""
    if prev is None or not prev.items:
        return ""
    chips = "".join(_count_chip(c) for c in prev.counts)
    rows = []
    for i in prev.items:
        cls = _status_class(i.status)
        has_return = i.result_return != "-"
        ret = html.escape(i.result_return) if has_return else "約定なし" if i.status == "不成立" else "-"
        sub_ret = f"成行 {html.escape(i.market_return)}" if i.market_return != "-" else ""
        move = f" ／ {html.escape(i.move)}" if i.move != "-" else ""
        rows.append(
            f'<div class="prev-row {cls}"><span class="rk">{html.escape(i.rank.removesuffix("位"))}</span>'
            f'<span class="st {cls}">{html.escape(i.status)}</span>'
            f'<div class="pn"><b>{_stock_link(i.name)}</b>'
            f"<small>指値{html.escape(i.entry_price)}{move}</small>"
            + (f'<small class="pn-note">{html.escape(i.note)}</small>' if i.note else "")
            + "</div>"
            f'<div class="pr">{ret}<small>{sub_ret}</small></div></div>'
        )
    return (
        f'<div class="prev"><div class="prev-head"><span class="prev-title">前営業日の結果</span>'
        f'<span class="prev-sub">{html.escape(prev.heading)}</span></div>'
        f'<div class="prev-score">{chips}</div><div class="prev-list">{"".join(rows)}</div></div>'
    )


def _side_section(
    heading: str,
    side: str,
    stats_lines: list[str],
    candidates: list[ParsedCandidate],
    unfilled: list[ParsedUnfilled] | None = None,
    anchor: bool = False,
    missed: list[ParsedMiss] | None = None,
    previous: ParsedPrevious | None = None,
) -> str:
    sub = f"TOP{len(candidates)}" if candidates else ""
    sub_html = f'<span class="side-sub">{sub}</span>' if sub else ""
    # 各ブロックを固定スロットに入れ、買い/売りで行位置を揃える（空でもスロットは常に6個）
    parts = [f'<div class="side-head"><h2 class="side-title">{heading}</h2>{sub_html}</div>']
    parts.append(_previous_block(previous))
    parts.append(_stat_row(stats_lines) if stats_lines else "")
    parts.append(_unfilled_block(unfilled or []))
    parts.append(_miss_block(missed or []))
    if candidates:
        cards = "".join(_candidate_card(c, side) for c in candidates)
        parts.append(f'<div class="card-grid">{cards}</div>')
    else:
        parts.append('<p class="empty-msg">本日は基準を満たす候補がありませんでした。</p>')
    slots = "".join(
        f'<div class="slot{" cards" if i == len(parts) - 1 else ""}">{p}</div>' for i, p in enumerate(parts)
    )
    id_attr = f' id="side-{side}"' if anchor else ""
    return f'<section class="side paired {side}"{id_attr}>{slots}</section>'


def _experiment_block(parsed: ParsedReport) -> str:
    """テスト枠（値動き重視・試験運用）。本番の直下に、折りたたみ（初期状態は閉じる）で置く。"""
    if not (parsed.exp_buy_candidates or parsed.exp_sell_candidates):
        return ""
    cols = []
    for label, side, stats, cands in (
        ("買い", "buy", parsed.exp_buy_stats_lines, parsed.exp_buy_candidates),
        ("売り", "sell", parsed.exp_sell_stats_lines, parsed.exp_sell_candidates),
    ):
        body = _stat_row(stats) if stats else ""
        if cands:
            body += f'<div class="card-grid">{"".join(_candidate_card(c, side) for c in cands)}</div>'
        else:
            body += '<p class="empty-msg">該当する候補がありませんでした。</p>'
        cols.append(f'<section class="exp-col {side}"><h3 class="exp-col-title">{label}候補</h3>{body}</section>')
    return (
        '<details class="experiment"><summary><span>テスト枠（値動き重視）</span>'
        '<span class="exp-badge">試験運用・効果は未確認</span></summary>'
        '<p class="uf-help">当日の値動き（値幅）が大きい上位30%の銘柄の中から、本番と同じスコアで選んだ候補です。'
        "本番の成績・仮想資金には含めず、別に記録しています。本番の候補とは別に、数週間追跡して効果を確かめる試験です。</p>"
        f'<div class="exp-sides">{"".join(cols)}</div></details>'
    )


def _render_report(parsed: ParsedReport, latest: bool = False, fset: ForecastSet | None = None, set_id: str = "") -> str:
    sections = _side_section(
        "買い候補", "buy", parsed.buy_stats_lines, parsed.buy_candidates, parsed.buy_unfilled, latest, parsed.buy_missed,
        parsed.buy_previous,
    )
    nav = ""
    if parsed.has_sell_section:
        sections += _side_section(
            "売り候補", "sell", parsed.sell_stats_lines, parsed.sell_candidates, parsed.sell_unfilled, latest, parsed.sell_missed,
            parsed.sell_previous,
        )
        if latest:
            nav = (
                '<nav class="seg-nav"><a class="buy" href="#side-buy">買い候補</a>'
                '<a class="sell" href="#side-sell">売り候補</a></nav>'
            )
    inner = f'<div class="sides">{sections}</div>{_experiment_block(parsed)}'
    if fset is None:
        return f"{nav}{inner}"
    header = _fset_header(fset, set_id)
    if latest:  # 最新の予想セットは、期限切れになったら自動で折りたたむ（画面側のスクリプトで開閉）
        return (
            f'{nav}{header}<details class="fset-body" data-id="{html.escape(set_id)}" open>'
            f'<summary>候補一覧（期限切れのときは折りたたまれます。タップで開閉）</summary>{inner}</details>'
        )
    return f"{header}{inner}"


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


def _glossary_block(*html_parts: str) -> str:
    """ページ本文に出てくる専門用語の意味を、本文の下に注意書きとして載せる。"""
    text = html_module_unescape(re.sub(r"<[^>]+>", " ", " ".join(html_parts)))
    entries = terms_in(text)
    if not entries:
        return ""
    items = "".join(f"<dt>{html.escape(t)}</dt><dd>{html.escape(d)}</dd>" for t, d in entries)
    return (
        '<section class="glossary"><h2 class="section-title">用語の説明</h2>'
        '<p class="fund-note">このページに出てくる専門用語の、一般的な意味です。</p>'
        f"<dl>{items}</dl></section>"
    )


def _fset_header(fs: ForecastSet, set_id: str) -> str:
    created = fmt_md_hm(fs.created_at) if fs.created_at else "不明（古い形式のため）"
    window = f"{fs.valid_from.month}/{fs.valid_from.day} {fs.valid_from:%H:%M}〜{fs.valid_until:%H:%M}"
    return (
        f'<div class="fset" data-id="{html.escape(set_id)}">'
        f'<div class="fset-top"><span class="fset-state">判定中…</span><b class="fset-label">{html.escape(fs.label)}</b></div>'
        f'<div class="fset-meta"><span>作成 {html.escape(created)}</span>'
        f"<span>データ基準 {html.escape(fmt_md_hm(fs.data_as_of))}（{html.escape(fs.data_note)}）</span>"
        f"<span>使える時間 {html.escape(window)}</span></div>"
        f'<p class="fset-note">{html.escape(fs.note)}</p></div>'
    )


def _banner_html() -> str:
    return (
        '<div id="now-banner" class="now-banner is-none" role="status" aria-live="polite">'
        '<span id="nb-text">予想の有効時間を判定中…</span>'
        "<noscript>時刻による「有効・期限切れ」の判定には JavaScript が必要です。"
        "各予想の「作成」「データ基準」「使える時間」を必ずご確認ください。</noscript></div>"
    )


def _fsets_json(sets: list[tuple[str, ForecastSet]]) -> str:
    data = json.dumps([to_json_dict(fs, sid) for sid, fs in sets], ensure_ascii=False)
    return f'<script type="application/json" id="fsets">{data.replace("</", "<\\/")}</script>'


def _derive_set(stem: str) -> ForecastSet | None:
    """予想セットの記載がない古いレポートは、ファイル名の日付から夜の予想として復元する（作成時刻は不明）。"""
    try:
        d = date.fromisoformat(stem)
    except ValueError:
        return None
    return evening_set(d, next_business_day(d), None)


def _is_premarket_empty(parsed: ParsedReport) -> bool:
    if parsed.buy_candidates or parsed.sell_candidates:
        return False
    items = [i for prev in (parsed.buy_previous, parsed.sell_previous) if prev for i in prev.items]
    return bool(items) and all(i.status == "未確定" for i in items)


def build_index(
    reports_dir: Path,
    docs_dir: Path,
    generated_at: str,
    market_gaps: dict[date, float] | None = None,
    fund: VirtualFund | None = None,
) -> Path:
    docs_dir.mkdir(parents=True, exist_ok=True)

    # 市場の取引前に作られた空のレポート（買い・売りとも候補なし、かつ前営業日の結果が全て未確定）は載せない
    parsed_by_path = {}
    for path in sorted(reports_dir.glob("*.md"), reverse=True):
        parsed = parse_report(path.read_text(encoding="utf-8"))
        if not _is_premarket_empty(parsed):
            parsed_by_path[path] = parsed
    report_files = list(parsed_by_path)

    latest_html = ""
    premarket = load_premarket(reports_dir / "premarket.json")
    latest_date = None
    if report_files:
        try:
            latest_date = date.fromisoformat(report_files[0].stem)
        except ValueError:
            latest_date = None
    env_html = _environment_block(premarket, latest_date, market_gaps)
    history_by_month: dict[str, list[str]] = defaultdict(list)
    page_sets: list[tuple[str, ForecastSet]] = []

    for i, path in enumerate(report_files):
        parsed = parsed_by_path[path]
        fset = parsed.forecast_set or _derive_set(path.stem)
        set_id = f"{path.stem}-{fset.slot}" if fset else ""
        body = _render_report(parsed, latest=(i == 0), fset=fset, set_id=set_id)
        if i == 0 and fset:
            page_sets.append((set_id, fset))
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
{_banner_html()}
{_fund_block(fund)}
{env_html}
{latest_html}
{_glossary_block(_fund_block(fund), env_html, latest_html)}
<div class="history-head"><h2 class="section-title">過去のレポート</h2><span class="count">{history_count}日分</span></div>
{history_section}
{_fsets_json(page_sets)}
<script>
{_FSET_SCRIPT}
</script>
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
