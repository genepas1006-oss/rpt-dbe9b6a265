"""前営業日の結果（取得 → レポート → パース → サイト表示）のテスト。"""

import sqlite3
from datetime import date

import pytest

from analysis.scoring import RankedCandidate
from report.build_site import build_index
from report.generate_report import generate_report
from report.parse_report import parse_report
from tracking.predictions_db import WinRateStats, init_db, record_evaluation, save_predictions
from tracking.previous import get_previous_results

D_OLD, D_PREV, D_TODAY = date(2026, 11, 4), date(2026, 11, 5), date(2026, 11, 6)
T_PREV = date(2026, 11, 6)


def _cand(code, side="buy", price=995.0, name=None):
    return RankedCandidate(
        code=code, name=name or f"n{code}", total_score=3, technical_score=2, earnings_score=1,
        volume_ratio=1.2, entry_price=price, reasons=[], side=side, day_close=1000.0, daily_return=0.01,
    )


def _pid(db, code, pdate):
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT id FROM predictions WHERE code=? AND prediction_date=?", (code, pdate.isoformat())).fetchone()[0]
    finally:
        conn.close()


def _eval(db, code, pdate, open_, low, high, close):
    record_evaluation(db, _pid(db, code, pdate), target_low=low, target_high=high, target_close=close,
                      actual_date=T_PREV, target_open=open_, market_return=0.0)


def _setup(tmp_path):
    db = str(tmp_path / "p.db")
    init_db(db)
    save_predictions(db, D_OLD, D_PREV, [_cand("OLD")])  # もっと前の予測日（無視される）
    save_predictions(db, D_PREV, T_PREV, [_cand("A", name="三菱商事"), _cand("B"), _cand("C"), _cand("D")])
    save_predictions(db, D_PREV, T_PREV, [_cand("S", side="sell", price=1005.0)])
    _eval(db, "A", D_PREV, 990, 985, 1010, 1005)   # 指値995: 約定（寄り990が有利なので990で約定）、終値1005 → (1005-990)/990 的中。成行も同じ
    _eval(db, "B", D_PREV, 1000, 985, 1000, 990)   # 約定、終値990 → -0.5025% 不的中。成行 -1.0%
    _eval(db, "C", D_PREV, 1000, 996, 1005, 1000)  # 安値996>995 → 不成立
    # D は未評価 → 未確定
    return db


# ---------------- 取得 ----------------
def test_previous_results_statuses_order_and_counts(tmp_path):
    prev = get_previous_results(_setup(tmp_path), "buy", D_TODAY)
    assert prev.prediction_date == D_PREV and prev.target_date == T_PREV
    assert [(i.rank, i.code, i.status) for i in prev.items] == [
        (1, "A", "win"), (2, "B", "loss"), (3, "C", "unfilled"), (4, "D", "pending")]
    assert prev.counts() == {"win": 1, "loss": 1, "unfilled": 1, "pending": 1}


def test_previous_results_values(tmp_path):
    a, b, c, d = get_previous_results(_setup(tmp_path), "buy", D_TODAY).items
    assert a.result_return == pytest.approx(15 / 990) and a.oc_return == pytest.approx(15 / 990)
    assert (a.target_open, a.target_close) == (990, 1005)
    assert b.result_return == pytest.approx(-5 / 995) and b.oc_return == pytest.approx(-0.01)
    assert c.result_return is None and c.oc_return == 0.0  # 指値は不成立でも、成行の結果はある
    assert d.result_return is None and d.target_open is None


def test_previous_results_picks_latest_date_before_today_only(tmp_path):
    db = _setup(tmp_path)
    assert get_previous_results(db, "buy", D_PREV).prediction_date == D_OLD  # 当日(11/5)は含めない
    assert get_previous_results(db, "buy", D_OLD) is None                      # それ以前なし
    save_predictions(db, D_TODAY, date(2026, 11, 9), [_cand("T")])
    assert get_previous_results(db, "buy", D_TODAY).prediction_date == D_PREV  # 今日の予測は「前日」でない


def test_previous_results_sides_are_separate(tmp_path):
    db = _setup(tmp_path)
    sell = get_previous_results(db, "sell", D_TODAY)
    assert [i.code for i in sell.items] == ["S"] and sell.items[0].status == "pending"
    assert get_previous_results(str(_empty(tmp_path)), "buy", D_TODAY) is None


def _empty(tmp_path):
    db = tmp_path / "e.db"
    init_db(str(db))
    return db


def test_all_zero_return_miss_counts_as_loss(tmp_path):
    db = str(tmp_path / "z.db")
    init_db(db)
    save_predictions(db, D_PREV, T_PREV, [_cand("Z")])
    _eval(db, "Z", D_PREV, 1000, 990, 1000, 995)  # 終値=指値 → リターン0 → 的中でない
    assert get_previous_results(db, "buy", D_TODAY).items[0].status == "loss"


# ---------------- レポート → パース ----------------
STATS = WinRateStats(10, 8, 4, 0.5)


def _report(tmp_path, with_sell=True):
    db = _setup(tmp_path)
    cand = _cand("X", name="ファナック", price=100.0)
    return generate_report(
        D_TODAY, date(2026, 11, 9), [cand], [], STATS, STATS,
        buy_previous=get_previous_results(db, "buy", D_TODAY),
        sell_previous=get_previous_results(db, "sell", D_TODAY) if with_sell else None,
    )


def test_report_text_format(tmp_path):
    text = _report(tmp_path)
    assert "## 前営業日の結果（買い）" in text
    assert "- 対象: 2026-11-05予測 → 2026-11-06 | 的中1・不的中1・不成立1・未確定1" in text
    assert "- 1位 | 三菱商事（A） | 的中 | 995.0円（約定990.0円） | +1.52% | 始値990.0円 → 終値1,005.0円 | +1.52%" in text
    assert "- 2位 | nB（B） | 不的中 | 995.0円 | -0.50% | 始値1,000.0円 → 終値990.0円 | -1.00%" in text
    assert "- 3位 | nC（C） | 不成立 | 995.0円 | - | 始値1,000.0円 → 終値1,000.0円 | +0.00%" in text
    assert "- 4位 | nD（D） | 未確定 | 995.0円 | - | - | -" in text
    # 前日の結果は、成績の後・本日の候補の前
    assert text.index("## デモ検証成績（売り") < text.index("## 前営業日の結果（買い）") < text.index("## 本日の買い候補")


def test_report_without_previous_has_no_section():
    text = generate_report(D_TODAY, date(2026, 11, 9), [], [], STATS, STATS)
    assert "前営業日の結果" not in text


def test_parse_roundtrip(tmp_path):
    parsed = parse_report(_report(tmp_path))
    prev = parsed.buy_previous
    assert prev.heading == "2026-11-05予測 → 2026-11-06"
    assert prev.counts == ["的中1", "不的中1", "不成立1", "未確定1"]
    assert [(i.rank, i.status) for i in prev.items] == [("1位", "的中"), ("2位", "不的中"), ("3位", "不成立"), ("4位", "未確定")]
    assert prev.items[0].name == "三菱商事（A）" and prev.items[0].market_return == "+1.52%"
    assert prev.items[3].move == "-" and prev.items[3].result_return == "-"
    assert parsed.sell_previous.items[0].status == "未確定"


def test_parse_old_report_without_section():
    parsed = parse_report(generate_report(D_TODAY, date(2026, 11, 9), [], [], STATS, STATS))
    assert parsed.buy_previous is None and parsed.sell_previous is None


# ---------------- サイト ----------------
def _page(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "2026-11-06.md").write_text(_report(tmp_path), encoding="utf-8")
    return build_index(reports, tmp_path / "docs", "t").read_text(encoding="utf-8")


def test_site_scoreboard_rows_and_order(tmp_path):
    page = _page(tmp_path)
    assert '<span class="prev-title">前営業日の結果</span><span class="prev-sub">2026-11-05予測 → 2026-11-06</span>' in page
    for chip in ('<span class="st win">的中 1</span>', '<span class="st loss">不的中 1</span>',
                 '<span class="st nofill">不成立 1</span>', '<span class="st pending">未確定 1</span>'):
        assert chip in page
    assert '<div class="prev-row win"><span class="rk">1</span><span class="st win">的中</span>' in page
    assert "<b>三菱商事（A）</b><small>指値995.0円（約定990.0円） ／ 始値990.0円 → 終値1,005.0円</small>" in page
    assert '<div class="pr">+1.52%<small>成行 +1.52%</small></div>' in page
    assert '<div class="pr">約定なし<small>成行 +0.00%</small></div>' in page   # 不成立でも成行の結果は見える
    assert '<div class="pr">-<small></small></div>' in page                       # 未確定
    # 各側の先頭（成績タイルより前）にある
    buy_part = page.split('id="side-buy"')[1].split('id="side-sell"')[0]
    assert buy_part.index('class="prev"') < buy_part.index('class="stat-row"') < buy_part.index('class="card-grid"')


def test_site_previous_is_per_side(tmp_path):
    page = _page(tmp_path)
    buy_part = page.split('id="side-buy"')[1].split('id="side-sell"')[0]
    sell_part = page.split('id="side-sell"')[1]
    assert "三菱商事" in buy_part and "三菱商事" not in sell_part
    assert "nS（S）" in sell_part and "nS（S）" not in buy_part


def test_site_escapes_names(tmp_path):
    db = str(tmp_path / "x.db")
    init_db(db)
    save_predictions(db, D_PREV, T_PREV, [_cand("E", name="A&B<社>")])
    # 候補なし・前営業日が全て未確定のレポートは「取引前の空レポート」として載せないため、候補を1件入れる
    text = generate_report(D_TODAY, date(2026, 11, 9), [_cand("Z")], [], STATS, STATS,
                           buy_previous=get_previous_results(db, "buy", D_TODAY))
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "2026-11-06.md").write_text(text, encoding="utf-8")
    page = build_index(reports, tmp_path / "docs", "t").read_text(encoding="utf-8")
    assert "A&amp;B&lt;社&gt;" in page and "A&B<社>" not in page


def test_site_no_previous_block_when_absent(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "2026-11-06.md").write_text(generate_report(D_TODAY, date(2026, 11, 9), [], [], STATS, STATS), encoding="utf-8")
    assert 'class="prev"' not in build_index(reports, tmp_path / "docs", "t").read_text(encoding="utf-8")


def test_target_date_is_the_latest_actual_trading_day(tmp_path):
    """祝日をまたいだ予測は、答え合わせで対象日が実際の営業日に更新される。表示は一番遅い日（実際の結果の日）にする。"""
    db = _setup(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE predictions SET target_date = '2026-11-09' WHERE code = 'B'")
    conn.commit()
    conn.close()
    assert get_previous_results(db, "buy", D_TODAY).target_date == date(2026, 11, 9)


def test_fill_price_gap_and_limit():
    """約定価格: 寄りが有利なら寄り値、そうでなければ指値。売りは高い方、買いは安い方（2026-11-11）。"""
    from tracking.previous import PreviousItem

    def item(side, entry, open_, status="win"):
        return PreviousItem(1, "A", "a", entry, status, 0.01, open_, 0.0, None, side=side)

    assert item("sell", 3878.3, 3999.0).fill_price == 3999.0  # 売り: 寄りが高い→寄り値で約定
    assert item("sell", 1972.8, 1962.0).fill_price == 1972.8  # 売り: 寄りが低い→指値で約定
    assert item("buy", 995.0, 990.0).fill_price == 990.0
    assert item("buy", 995.0, 1000.0).fill_price == 995.0
    assert item("buy", 995.0, None).fill_price == 995.0
    assert item("buy", 995.0, 990.0, status="unfilled").fill_price is None
