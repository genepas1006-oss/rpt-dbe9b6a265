"""予想セット（有効期間・状態・バナー）のテスト。承認済みの手計算ケース（2026-11-11）。"""

import json
import re
import sqlite3
from datetime import date, datetime, timedelta

import pytest

from analysis.market_calendar import next_business_day
from report.forecast_set import (
    ACTIVE, EXPIRED, JST, WAITING, ForecastSet, evening_set, from_md_body, pick_banner_set, state_at, to_md_lines,
)


def dt(y, m, d, h=0, mi=0, s=0):
    return datetime(y, m, d, h, mi, s, tzinfo=JST)


def lunch_set(day=date(2026, 11, 11), created=None):
    return ForecastSet("lunch", created or dt(2026, 11, day.day, 11, 50), dt(2026, 11, day.day, 11, 30), "前場終了（約15分遅れのデータ）",
                       day, "pm", dt(2026, 11, day.day, 12, 30), dt(2026, 11, day.day, 15, 30), "後場向け")


def test_lunch_set_states_and_boundaries():
    fs = lunch_set()
    assert state_at(fs, dt(2026, 11, 11, 11, 55)) == (WAITING, timedelta(minutes=35))
    assert state_at(fs, dt(2026, 11, 11, 12, 30, 0))[0] == ACTIVE          # 開始時刻を含む
    assert state_at(fs, dt(2026, 11, 11, 15, 29, 59))[0] == ACTIVE
    assert state_at(fs, dt(2026, 11, 11, 15, 30, 0)) == (EXPIRED, None)    # 終了時刻は含まない


def test_evening_set_is_morning_only():
    fs = evening_set(date(2026, 11, 10), date(2026, 11, 11), dt(2026, 11, 10, 16, 12))
    assert fs.valid_from == dt(2026, 11, 11, 9, 0) and fs.valid_until == dt(2026, 11, 11, 11, 30)
    assert fs.data_as_of == dt(2026, 11, 10, 15, 30) and fs.label == "夜の予想（11/11 前場向け）"
    assert state_at(fs, dt(2026, 11, 10, 20, 0)) == (WAITING, timedelta(hours=13))      # 翌朝9:00から
    assert state_at(fs, dt(2026, 11, 11, 11, 29, 59))[0] == ACTIVE
    assert state_at(fs, dt(2026, 11, 11, 11, 30, 0))[0] == EXPIRED                       # 後場には使えない
    assert state_at(fs, dt(2026, 11, 11, 12, 45))[0] == EXPIRED


def test_friday_evening_targets_next_monday():
    friday, monday = date(2026, 11, 13), date(2026, 11, 16)
    assert next_business_day(friday) == monday
    fs = evening_set(friday, monday, dt(2026, 11, 13, 16, 10))
    assert state_at(fs, dt(2026, 11, 14, 10, 0)) == (WAITING, timedelta(days=1, hours=23))   # 土曜10:00 → 月曜9:00まで47時間


def test_banner_picks_latest_active_else_earliest_waiting():
    ev = evening_set(date(2026, 11, 10), date(2026, 11, 11), dt(2026, 11, 10, 16, 12))
    lu = lunch_set()
    assert pick_banner_set([ev, lu], dt(2026, 11, 11, 10, 0)) is ev                 # 前場: 夜の予想が有効
    assert pick_banner_set([ev, lu], dt(2026, 11, 11, 11, 40)) is lu                # 昼休み: 夜は期限切れ、昼が待機
    assert pick_banner_set([ev, lu], dt(2026, 11, 11, 13, 0)) is lu                 # 後場: 昼の予想が有効
    assert pick_banner_set([ev, lu], dt(2026, 11, 11, 16, 0)) is None               # 終了後: 表示なし
    both_active = ForecastSet("open", dt(2026, 11, 11, 9, 20), dt(2026, 11, 11, 9, 5), "寄り付き", date(2026, 11, 11), "am",
                              dt(2026, 11, 11, 9, 20), dt(2026, 11, 11, 11, 30), "")
    assert pick_banner_set([ev, both_active], dt(2026, 11, 11, 10, 0)) is both_active  # 有効が複数なら作成が新しい方


def test_markdown_roundtrip_and_legacy():
    fs = evening_set(date(2026, 11, 10), date(2026, 11, 11), dt(2026, 11, 10, 16, 12))
    back = from_md_body("\n".join(to_md_lines(fs)[2:]))
    assert back == fs
    unknown = evening_set(date(2026, 11, 10), date(2026, 11, 11), None)
    assert from_md_body("\n".join(to_md_lines(unknown)[2:])).created_at is None
    assert from_md_body("- 種別: 壊れた") is None  # 想定外の形式は、予想セットなしとして扱う


def test_site_renders_banner_header_json_and_fold(tmp_path):
    from analysis.scoring import RankedCandidate
    from report.build_site import build_index
    from report.generate_report import generate_report
    from tracking.predictions_db import WinRateStats

    st = WinRateStats(1, 1, 1, 1.0)
    cand = RankedCandidate(code="6954", name="ファナック", total_score=3, technical_score=2, earnings_score=1,
                           volume_ratio=2.0, entry_price=5608.8, side="buy", day_close=5600.0)
    fs = evening_set(date(2026, 11, 10), date(2026, 11, 11), dt(2026, 11, 10, 16, 12))
    reports = tmp_path / "reports"; reports.mkdir()
    (reports / "2026-11-10.md").write_text(generate_report(date(2026, 11, 10), date(2026, 11, 11), [cand], [], st, st, forecast_set=fs), encoding="utf-8")
    # 予想セットの記載がない古いレポート（履歴）。ファイル名の日付から復元される
    (reports / "2026-11-06.md").write_text(generate_report(date(2026, 11, 6), date(2026, 11, 9), [cand], [], st, st), encoding="utf-8")
    page = build_index(reports, tmp_path / "docs", "x").read_text(encoding="utf-8")
    assert 'id="now-banner"' in page and "JavaScript が必要です" in page
    assert "夜の予想（11/11 前場向け）" in page and "作成 11/10 16:12" in page and "データ基準 11/10 15:30（大引け）" in page
    assert "使える時間 11/11 09:00〜11:30" in page and "後場の売買には使えません" in page
    assert '<details class="fset-body"' in page and "作成 不明（古い形式のため）" in page  # 履歴は作成時刻が不明
    data = json.loads(re.search(r'<script type="application/json" id="fsets">(.*?)</script>', page, re.S).group(1))
    assert [d["id"] for d in data] == ["2026-11-10-evening"]  # バナー判定に使うのは最新のセットだけ
    assert data[0]["valid_from"] == "2026-11-11T09:00:00+09:00" and data[0]["valid_until"] == "2026-11-11T11:30:00+09:00"
    assert "<dt>前場</dt>" in page and "<dt>期限切れ</dt>" in page


def test_save_predictions_records_forecast_set(tmp_path):
    from analysis.scoring import RankedCandidate
    from tracking.predictions_db import init_db, save_predictions

    db = str(tmp_path / "t.db"); init_db(db)
    c = RankedCandidate(code="X", name="X", total_score=3, technical_score=2, earnings_score=1, volume_ratio=2.0,
                        entry_price=995.0, side="buy", day_close=1000.0)
    fs = evening_set(date(2026, 11, 10), date(2026, 11, 11), dt(2026, 11, 10, 16, 12))
    save_predictions(db, date(2026, 11, 10), date(2026, 11, 11), [c], forecast_set=fs)
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT slot, valid_from, valid_until, data_as_of FROM predictions").fetchone()
    conn.close()
    assert row == ("evening", "2026-11-11T09:00:00+09:00", "2026-11-11T11:30:00+09:00", "2026-11-10T15:30:00+09:00")
