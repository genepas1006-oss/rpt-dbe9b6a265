"""前場・後場の時間帯別の的中率（2026-11-20承認）の手計算ケース。"""

import gzip
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

from data_sources.base import IntradayBar
from report.build_site import _session_block, build_index
from tracking.predictions_db import init_db
from tracking.session_stats import (
    compute_session_table,
    ensure_5m_history,
    is_hit,
    load_session_stats,
    save_session_stats,
    session_return,
)

JST = timezone(timedelta(hours=9))
DAY = date(2026, 11, 18)


def _bar(hhmm, o, c):
    return [hhmm, o, max(o, c), min(o, c), c, 100]


# 前場: 9:00始値1,000 → 11:25終値1,012 / 後場: 12:30始値1,010 → 15:25終値1,005
GOOD = [_bar("09:00", 1000, 1003), _bar("10:00", 1005, 1008), _bar("11:25", 1010, 1012),
        _bar("12:30", 1010, 1008), _bar("14:00", 1008, 1006), _bar("15:25", 1006, 1005)]


def test_t1_session_returns_and_hits():
    am, pm = session_return(GOOD, "am"), session_return(GOOD, "pm")
    assert am == pytest.approx(0.012) and pm == pytest.approx(-5 / 1010)  # -0.495%
    assert round(pm * 100, 3) == -0.495
    assert is_hit("buy", am) and not is_hit("buy", pm)
    assert not is_hit("sell", am) and is_hit("sell", pm)


def test_t2_flat_is_a_miss_and_missing_edge_is_excluded():
    flat = [_bar("12:30", 1000, 1000), _bar("15:25", 1000, 1000)]
    r = session_return(flat, "pm")
    assert r == 0 and not is_hit("buy", r) and not is_hit("sell", r)
    late_open = [_bar("09:30", 1000, 1010), _bar("11:25", 1010, 1012)]  # 最初の足が9:30始まり
    assert session_return(late_open, "am") is None
    early_end = [_bar("09:00", 1000, 1010), _bar("11:05", 1010, 1012)]  # 最後の足が11:05〜11:10で終わる（11:20より前）
    assert session_return(early_end, "am") is None
    assert session_return(GOOD[:3], "pm") is None  # 後場の足がない
    assert session_return([_bar("09:00", 0, 5), _bar("11:25", 5, 6)], "am") is None  # 始値0


def _write_day(out_dir, day, data):
    out_dir.mkdir(parents=True, exist_ok=True)
    with gzip.open(out_dir / f"{day.isoformat()}.json.gz", "wt", encoding="utf-8") as f:
        json.dump(data, f)


def _ins(db, variant, side, code, anomaly=0, day=DAY):
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO predictions (prediction_date, code, name, side, total_score, technical_score, earnings_score, "
        "entry_price, reasons, target_date, evaluated, data_anomaly, variant, created_at) "
        "VALUES (?, ?, ?, ?, 0, 0, 0, 100, '[]', ?, 1, ?, ?, 'now')",
        (day.isoformat(), code, code, side, day.isoformat(), anomaly, variant),
    )
    conn.commit()
    conn.close()


def _day_bars(am, pm):
    """前場の値動きam・後場の値動きpm（割合）になる最小限の足。amがNoneなら前場の足なし。"""
    rows = []
    if am is not None:
        rows += [_bar("09:00", 1000, 1000), _bar("11:25", 1000, 1000 * (1 + am))]
    if pm is not None:
        rows += [_bar("12:30", 1000, 1000), _bar("15:25", 1000, 1000 * (1 + pm))]
    return rows


@pytest.fixture
def setup(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    bars = tmp_path / "bars"
    # 夜の予想（買い5件）: 前場 +1.2, -0.5, 0.0, +0.3, 欠損 / 後場 -0.495, +0.2, +0.1, -0.3, +0.6（%）
    am = [0.012, -0.005, 0.0, 0.003, None]
    pm = [-0.00495, 0.002, 0.001, -0.003, 0.006]
    data = {f"B{i}": _day_bars(a, p) for i, (a, p) in enumerate(zip(am, pm))}
    for i in range(5):
        _ins(db, "main", "buy", f"B{i}")
    _ins(db, "main", "buy", "ANOM", anomaly=1)            # データ異常 → 除外
    data["ANOM"] = _day_bars(0.5, 0.5)
    # 昼の予想（売り1件）: 後場 -2.0%（下落）→ 売りは的中。前場は対象外
    _ins(db, "lunch", "sell", "L0")
    data["L0"] = _day_bars(0.01, -0.02)
    # 全銘柄の基準用: 前場 +1%, -1%, 0%
    for code, a in (("U1", 0.01), ("U2", -0.01), ("U3", 0.0)):
        data[code] = _day_bars(a, 0.0)
    _write_day(bars, DAY, data)
    return db, bars


def test_t3_t4_t5_table(setup):
    db, bars = setup
    t = compute_session_table(db, bars)
    rows = {r["variant"]: r for r in t["rows"]}
    main = rows["main"]["buy"]
    assert main["am"] == {"n": 4, "wins": 2}   # T3: 50.0%（2/4件）。欠損1件は除外、データ異常も除外
    assert main["pm"] == {"n": 5, "wins": 3}   # 60.0%（3/5件）
    lunch = rows["lunch"]
    assert lunch["buy"]["am"] is None and lunch["sell"]["am"] is None   # T5: 前場は対象外
    assert lunch["sell"]["pm"] == {"n": 1, "wins": 1}
    base = rows["all"]
    # T4: 前場の基準。U1(+1%), U2(-1%), U3(0%) に、夜の予想の5件・L0・ANOMも含む全銘柄の中から、足がある銘柄で集計される
    assert base["buy"]["am"]["n"] == base["sell"]["am"]["n"]  # 買い・売りで母数は同じ
    # 3銘柄だけの基準を単独で確認（T4: 買い=上がった割合 1/3、売り=下がった割合 1/3、0%はどちらにも数えない）
    from tracking.session_stats import _count, session_return as sr
    items = [("buy", sr(_day_bars(a, 0), "am")) for a in (0.01, -0.01, 0.0)]
    assert _count(items, "buy") == {"n": 3, "wins": 1} and _count([("sell", r) for _, r in items], "sell") == {"n": 3, "wins": 1}


def test_t6_missing_day_file_is_skipped_without_error(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    _ins(db, "main", "buy", "X")
    t = compute_session_table(db, tmp_path / "no_such_dir")
    main = next(r for r in t["rows"] if r["variant"] == "main")
    assert main["buy"]["am"] == {"n": 0, "wins": 0}


class _FakeSource:
    def get_intraday_history(self, code):
        if code == "BAD":
            raise RuntimeError("取得失敗")
        return [IntradayBar(datetime(2026, 11, 18, 9, 0, tzinfo=JST), 1000, 1001, 999, 1000.5, 10),
                IntradayBar(datetime(2026, 11, 18, 11, 25, tzinfo=JST), 1000.5, 1003, 1000, 1002, 10)]


def test_ensure_5m_history_fills_only_missing_days_and_survives_failures(tmp_path):
    out = tmp_path / "bars"
    n = ensure_5m_history(_FakeSource(), ["1111", "BAD"], [DAY, date(2026, 11, 17)], out)
    assert n == 1  # 11/18 の分だけ（11/17 は足がなく保存されない）
    with gzip.open(out / "2026-11-18.json.gz", "rt", encoding="utf-8") as f:
        data = json.load(f)
    assert set(data) == {"1111"} and data["1111"][0][0] == "09:00"
    assert ensure_5m_history(_FakeSource(), ["1111"], [DAY], out) == 0  # すでにあれば取得しない


def test_render_table_cells_and_json_roundtrip(tmp_path, setup):
    db, bars = setup
    path = tmp_path / "reports" / "session_stats.json"
    save_session_stats(path, compute_session_table(db, bars), "t")
    stats = load_session_stats(path)
    html = _session_block(stats)
    assert "<b>50.0%</b><small>2/4件</small>" in html and "<b>60.0%</b><small>3/5件</small>" in html
    assert '<td class="na">対象外</td>' in html  # 昼の予想の前場
    assert "全銘柄（参考）" in html and "試験的" in html
    assert _session_block(None) == "" and load_session_stats(tmp_path / "none.json") is None
    (tmp_path / "reports" / "x.md").write_text("# t\n", encoding="utf-8")
    page = build_index(tmp_path / "reports", tmp_path / "docs", "t").read_text(encoding="utf-8")
    assert "前場・後場の時間帯別の的中率" in page
