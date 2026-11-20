"""SBI証券の取引結果CSV → 日ごとの損益 → 損益カレンダー（2026-11-20）のテスト。CSVは架空のデータ。"""

import json
from datetime import date

import pytest

from report.build_site import build_index
from report.pnl_calendar import fmt_signed, month_summary, render_calendar
from tracking.trade_import import load_daily_pnl, merge_daily_pnl, parse_daily_pnl, save_daily_pnl

HEADER = "銘柄,銘柄,銘柄,取引区分,期限,預り区分,約定日,受渡日,株数,平均約定単価,手数料・諸経費等,課税額・譲渡益税,受渡金額・決済損益,受渡金額(日計り分)\n"


def _row(code, typ, day, qty, price, fee="--", pnl="--"):
    return f'{code},テスト銘柄,東証,{typ},６ヵ月,特定,{day},{day},{qty},"{price}",{fee},--,"{pnl}",--\n'


CSV = HEADER + "".join([
    # 11/05: +190（(102-100)×100 - 10）と -1,290（(100-113)×100 + 10 手数料... 架空）
    _row("1111", "信用新規買", "2026/11/05", 100, "100"),
    _row("1111", "信用返済売", "2026/11/05", 100, "102", fee=10, pnl="190"),
    _row("2222", "信用新規売", "2026/11/05", 100, "1,000"),
    _row("2222", "信用返済買", "2026/11/05", 100, "1,013", fee=12, pnl="-1,312"),   # (1,000-1,013)×100 - 12
    # 11/06: 新規のみ（損益なし）→ 日に出ない
    _row("3333", "信用新規買", "2026/11/06", 200, "50"),
    # 11/09: 返済1件（持ち越し分）
    _row("3333", "信用返済売", "2026/11/09", 200, "52.5", fee=8, pnl="492"),         # (52.5-50)×200 - 8
    # 損益が「--」の返済行は無視
    _row("4444", "信用返済売", "2026/11/09", 100, "10", pnl="--"),
])


def test_daily_pnl_hand_calc():
    d = parse_daily_pnl(CSV)
    assert d == {
        "2026-11-05": {"pnl": 190 - 1312, "trades": 2},   # -1,122
        "2026-11-09": {"pnl": 492, "trades": 1},
    }
    assert (102 - 100) * 100 - 10 == 190 and (1000 - 1013) * 100 - 12 == -1312 and round((52.5 - 50) * 200 - 8) == 492


def test_encoding_shift_jis_and_bom():
    assert parse_daily_pnl(CSV.encode("cp932")) == parse_daily_pnl(CSV)
    assert parse_daily_pnl(("﻿" + CSV).encode("utf-8")) == parse_daily_pnl(CSV)


def test_merge_replaces_overlapping_days_and_keeps_others():
    old = {"2026-11-05": {"pnl": 1, "trades": 1}, "2026-11-04": {"pnl": 5, "trades": 1}}
    new = parse_daily_pnl(CSV)
    m = merge_daily_pnl(old, new)
    assert m["2026-11-05"]["pnl"] == -1122 and m["2026-11-04"]["pnl"] == 5 and m["2026-11-09"]["pnl"] == 492
    assert merge_daily_pnl(m, new) == m  # 何度取り込んでも同じ


def test_json_roundtrip_contains_only_date_pnl_and_count(tmp_path):
    p = tmp_path / "trades" / "daily_pnl.json"
    save_daily_pnl(p, parse_daily_pnl(CSV))
    text = p.read_text(encoding="utf-8")
    assert "テスト銘柄" not in text and "1111" not in text and "52.5" not in text  # 銘柄名・コード・単価は保存しない
    assert load_daily_pnl(p) == parse_daily_pnl(CSV)
    assert load_daily_pnl(tmp_path / "none.json") == {}
    p.write_text("{broken", encoding="utf-8")
    assert load_daily_pnl(p) == {}


def test_signed_format():
    assert fmt_signed(11085) == "+11,085" and fmt_signed(-1693) == "−1,693" and fmt_signed(0) == "0"


# ---- 架空の9日分での、カレンダーの集計（手計算: 合計 +2,150 / 勝ち4日・負け5日 / 週計 -1,000・-4,750・+7,900） ----
SAMPLE = {
    "2026-11-06": -1000, "2026-11-10": -2000, "2026-11-11": -3000, "2026-11-12": 500, "2026-11-13": -250,
    "2026-11-16": 4000, "2026-11-17": 1500, "2026-11-18": 2500, "2026-11-19": -100,
}


def _days():
    return {k: {"pnl": v, "trades": 1} for k, v in SAMPLE.items()}


def test_month_summary_hand_calc():
    s = month_summary(_days(), 2026, 11)
    assert s == {"total": 2150, "win_days": 4, "loss_days": 5, "days": 9}


def test_calendar_html_signs_colors_and_week_totals():
    h = render_calendar(_days())
    assert "合計 +2,150円" in h and "勝ち4日・負け5日" in h
    assert '<td class="minus"><span class="d">6<i class="mk">▼</i></span><span class="v">−1,000</span></td>' in h
    assert '<td class="plus"><span class="d">18<i class="mk">▲</i></span><span class="v">+2,500</span></td>' in h
    assert '<td class="wk minus">−1,000</td>' in h and '<td class="wk minus">−4,750</td>' in h and '<td class="wk plus">+7,900</td>' in h
    assert h.count('class="cal-month active"') == 1  # 最新の月が初期表示


def test_calendar_weekend_pnl_goes_to_week_total_and_multiple_months():
    d = {"2026-10-30": {"pnl": 100, "trades": 1}, "2026-11-07": {"pnl": 50, "trades": 1}, "2026-11-06": {"pnl": 10, "trades": 1}}
    h = render_calendar(d)
    assert 'data-month="2026-10"' in h and 'data-month="2026-11"' in h
    assert '<td class="wk plus">+60</td>' in h  # 土曜(11/7)の+50は、その週の週計に含む（金曜の+10と合わせて+60）
    assert render_calendar({}) == ""


def test_site_shows_calendar_only_when_data_exists(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "2026-11-06.md").write_text("# 日本株デイクローズ・リサーチレポート\n", encoding="utf-8")
    page = build_index(reports, tmp_path / "docs", "t").read_text(encoding="utf-8")
    assert 'id="pnl-cal"' not in page  # データが無ければ出さない
    save_daily_pnl(tmp_path / "trades" / "daily_pnl.json", _days())
    page = build_index(reports, tmp_path / "docs", "t").read_text(encoding="utf-8")
    assert 'id="pnl-cal"' in page and "損益カレンダー" in page
    assert page.index('id="now-banner"') < page.index('id="pnl-cal"') < page.index('class="fund"') if 'class="fund"' in page else True
