"""損益カレンダー（ページ上部）。SBI証券の取引結果CSVから集計した、日ごとの実現損益を月間カレンダーで表示する。

承認済み設計（2026-11-20）:
    月曜〜金曜の5列＋週計の列。日ごとの損益を、符号付きの数字（+/−）と色（プラス=青、マイナス=橙）、▲▼で示す。
    月の合計・勝ち日（損益>0）・負け日（損益<0）の数・週計を出す。土日に損益がある場合は、その週の週計に含める。
    色だけに頼らず、必ず符号と▲▼も付ける。
"""

import calendar
import html
from datetime import date, timedelta


def fmt_signed(v: int) -> str:
    """+12,345 / −1,693（マイナスはU+2212）。0は「0」。"""
    if v > 0:
        return f"+{v:,}"
    if v < 0:
        return f"−{-v:,}"
    return "0"


def _cls(v: int) -> str:
    return "plus" if v > 0 else "minus" if v < 0 else "zero"


def _mark(v: int) -> str:
    return "▲" if v > 0 else "▼" if v < 0 else "－"


def month_summary(days: dict[str, dict[str, int]], year: int, month: int) -> dict:
    items = {date.fromisoformat(k): v["pnl"] for k, v in days.items() if date.fromisoformat(k).year == year and date.fromisoformat(k).month == month}
    return {
        "total": sum(items.values()),
        "win_days": sum(1 for v in items.values() if v > 0),
        "loss_days": sum(1 for v in items.values() if v < 0),
        "days": len(items),
    }


def _month_html(days: dict[str, dict[str, int]], year: int, month: int, active: bool) -> str:
    pnl = {date.fromisoformat(k): v["pnl"] for k, v in days.items()}
    sm = month_summary(days, year, month)
    head = "".join(f"<th>{w}</th>" for w in "月火水木金") + "<th>週計</th>"
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
    body = ""
    for week in weeks:
        cells, week_total, has = "", 0, False
        for i, d in enumerate(week):
            v = pnl.get(d)
            if v is not None:
                week_total += v
                has = True
            if i >= 5:  # 土日は列を出さない（損益があれば週計に含める）
                continue
            if d.month != month:
                cells += '<td class="out"></td>'
            elif v is None:
                cells += f'<td class="none"><span class="d">{d.day}</span></td>'
            else:
                cells += (
                    f'<td class="{_cls(v)}"><span class="d">{d.day}<i class="mk">{_mark(v)}</i></span>'
                    f'<span class="v">{html.escape(fmt_signed(v))}</span></td>'
                )
        if all(d.month != month for d in week[:5]) and not any(pnl.get(d) is not None and d.month == month for d in week):
            continue
        wk = f'<td class="wk {_cls(week_total)}">{html.escape(fmt_signed(week_total))}</td>' if has else '<td class="wk none"></td>'
        body += f"<tr>{cells}{wk}</tr>"
    summary = (
        f'<p class="cal-sum"><b class="{_cls(sm["total"])}">合計 {html.escape(fmt_signed(sm["total"]))}円</b>'
        f'<span>勝ち{sm["win_days"]}日・負け{sm["loss_days"]}日</span></p>'
    )
    return (
        f'<div class="cal-month{" active" if active else ""}" data-month="{year}-{month:02d}">'
        f'<h3 class="cal-title">{year}年{month}月</h3>{summary}'
        f'<table class="cal-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
    )


def render_calendar(days: dict[str, dict[str, int]]) -> str:
    """損益のデータが無ければ空文字（ページに出さない）。最新の月を初期表示にする。"""
    if not days:
        return ""
    months = sorted({(date.fromisoformat(k).year, date.fromisoformat(k).month) for k in days})
    last = months[-1]
    body = "".join(_month_html(days, y, m, (y, m) == last) for y, m in months)
    total = sum(v["pnl"] for v in days.values())
    return (
        '<section class="pnl-cal" id="pnl-cal"><div class="cal-head"><span class="cal-h-title">損益カレンダー</span>'
        '<span class="cal-nav"><button type="button" class="cal-prev" aria-label="前の月">◀</button>'
        '<button type="button" class="cal-next" aria-label="次の月">▶</button></span></div>'
        f"{body}"
        '<p class="cal-note">SBI証券の取引結果から集計した、実際の売買の実現損益です（信用返済・手数料込み）。'
        "返済した日に計上します。このツールの予想の成績ではありません。"
        f'全期間の合計: <b>{html.escape(fmt_signed(total))}円</b></p></section>'
    )


CAL_STYLE = """
.pnl-cal { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; box-shadow: var(--shadow); padding: 12px 12px 10px; margin: 0 0 14px; }
.pnl-cal .cal-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }
.pnl-cal .cal-h-title { font-weight: 800; font-size: 0.95rem; color: var(--ink); }
.pnl-cal .cal-nav button { border: 1px solid var(--border); background: var(--surface-2); color: var(--ink); border-radius: 8px; width: 36px; height: 30px; margin-left: 6px; font-size: 0.8rem; cursor: pointer; }
.pnl-cal .cal-month { display: none; } .pnl-cal .cal-month.active { display: block; }
.pnl-cal .cal-title { margin: 4px 0 2px; font-size: 1rem; color: var(--ink); }
.pnl-cal .cal-sum { display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: baseline; margin: 0 0 8px; font-size: 0.82rem; color: var(--text-muted); }
.pnl-cal .cal-sum b { font-size: 1.15rem; }
.pnl-cal .plus { color: var(--win); } .pnl-cal .minus { color: var(--loss); } .pnl-cal .zero { color: var(--idle); }
.pnl-cal .cal-table { width: 100%; border-collapse: separate; border-spacing: 2px; table-layout: fixed; }
.pnl-cal .cal-table th:last-child, .pnl-cal .cal-table td.wk { width: 17%; }
.pnl-cal .cal-table th { font-size: 0.68rem; font-weight: 700; color: var(--text-muted); padding: 2px 0; }
.pnl-cal .cal-table td { height: 54px; vertical-align: top; border-radius: 8px; padding: 3px 2px 3px 4px; overflow: hidden; background: var(--surface-2); position: relative; }
.pnl-cal .cal-table td.out { background: transparent; }
.pnl-cal .cal-table td.plus { background: var(--win-bg); } .pnl-cal .cal-table td.minus { background: var(--loss-bg); }
.pnl-cal .cal-table .d { display: flex; justify-content: space-between; font-size: 0.66rem; color: var(--text-muted); }
.pnl-cal .cal-table .mk { font-style: normal; font-size: 0.7rem; font-weight: 800; }
.pnl-cal .cal-table td.plus .mk { color: var(--win); } .pnl-cal .cal-table td.minus .mk { color: var(--loss); }
.pnl-cal .cal-table .v { display: block; font-size: 0.66rem; font-weight: 800; line-height: 1.25; margin-top: 6px; letter-spacing: -0.02em; white-space: nowrap; }
.pnl-cal .cal-table td.wk { background: transparent; vertical-align: middle; text-align: center; font-size: 0.72rem; font-weight: 800; border-left: 2px solid var(--border); border-radius: 0; }
.pnl-cal .cal-note { margin: 8px 0 0; font-size: 0.7rem; color: var(--text-muted); line-height: 1.5; }
@media (min-width: 700px) { .pnl-cal .cal-table td { height: 64px; } .pnl-cal .cal-table .v { font-size: 0.9rem; } }
"""

CAL_SCRIPT = """
(function () {
  var root = document.getElementById('pnl-cal');
  if (!root) return;
  var months = Array.prototype.slice.call(root.querySelectorAll('.cal-month'));
  var now = new Date(Date.now() + 9 * 3600 * 1000);
  var cur = now.getUTCFullYear() + '-' + ('0' + (now.getUTCMonth() + 1)).slice(-2);
  var idx = months.findIndex(function (m) { return m.dataset.month === cur; });
  if (idx < 0) idx = months.length - 1;
  function show() { months.forEach(function (m, i) { m.classList.toggle('active', i === idx); }); }
  root.querySelector('.cal-prev').addEventListener('click', function () { if (idx > 0) { idx--; show(); } });
  root.querySelector('.cal-next').addEventListener('click', function () { if (idx < months.length - 1) { idx++; show(); } });
  show();
})();
"""
