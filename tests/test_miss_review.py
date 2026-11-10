"""外れた予想の検証メモのテスト。承認済みの手計算ケース M1〜M4 ほか（2026-11-10）。"""

import json
import sqlite3
from datetime import date

import pytest

from analysis.miss_review import compute_metrics, review_miss
from report.glossary import GLOSSARY, terms_in
from tracking.miss_reviews import update_miss_reviews
from tracking.predictions_db import init_db


def _review(side, entry, pc, o, h, l, c, m, dr=0.0, vr=1.0, snap=None, days=None):
    return review_miss(side, entry, pc, dr, vr, o, h, l, c, m, snap, days)


def test_m1_sell_gap_is_primary():
    r = _review("sell", 1005, 1000, 1020, 1030, 1010, 1025, 0.012)
    mt = r.metrics
    assert mt.fill_price == 1020 and mt.trade_return == pytest.approx(-5 / 1020)  # -0.49%
    assert mt.stock_move == pytest.approx(0.025) and mt.market_share == pytest.approx(0.48)
    assert mt.excess == pytest.approx(0.013)
    assert mt.gap == pytest.approx(0.02) and mt.open_to_close == pytest.approx(5 / 1020)
    assert mt.favorable == pytest.approx(10 / 1020) and mt.adverse == pytest.approx(10 / 1020)
    assert r.primary == "寄りで上昇" and r.secondary == ["地合い上昇"]
    assert "寄り付きで予測日の終値比+2.00%" in r.text and "約定価格1,020.0円" in r.text and "終値で-0.49%" in r.text


def test_m2_buy_market_is_primary_with_gap_secondary():
    r = _review("buy", 995, 1000, 990, 995, 980, 985, -0.02)
    mt = r.metrics
    assert mt.fill_price == 990 and mt.trade_return == pytest.approx(-5 / 990)  # -0.51%
    assert mt.market_share == pytest.approx(1.0) and mt.excess == pytest.approx(0.005)
    assert mt.favorable == pytest.approx(5 / 990) and mt.adverse == pytest.approx(10 / 990)
    assert r.primary == "地合い悪化" and r.secondary == ["寄りで下落"]
    assert "約100%を市場全体の動きで説明できます" in r.text and "超過）は+0.50%" in r.text


def test_m3_buy_individual_factor():
    r = _review("buy", 995, 1000, 1000, 1005, 985, 990, 0.002)
    mt = r.metrics
    assert mt.fill_price == 995 and mt.trade_return == pytest.approx(-5 / 995)  # -0.50%
    assert mt.market_share == 0.0 and mt.excess == pytest.approx(-0.012)
    assert mt.gap == 0.0 and mt.open_to_close == pytest.approx(-0.01)
    assert mt.favorable == pytest.approx(10 / 995) and mt.adverse == pytest.approx(10 / 995)
    assert r.primary == "個別要因" and r.secondary == []


def test_m4_market_missing_is_noted():
    r = _review("buy", 995, 1000, 1000, 1005, 985, 990, None)
    assert r.metrics.market_share is None and r.metrics.excess is None
    assert r.primary == "データ不足" and "日経平均のデータが欠けているため" in r.text
    r2 = _review("buy", 995, 1000, 985, 995, 975, 980, None)  # 寄りのギャップだけで主因が決まる場合は判定できる
    assert r2.primary == "寄りで下落"


def test_market_share_boundary_and_direction():
    # r = -2.0%, m = -1.0% → 寄与率0.5ちょうどで地合い主因。m=-0.99%なら主因にならない
    assert _review("buy", 995, 1000, 995, 996, 975, 980, -0.01).primary == "地合い悪化"
    assert _review("buy", 995, 1000, 995, 996, 975, 980, -0.0099).primary != "地合い悪化"
    # 逆向き（銘柄は下落、日経は上昇）は寄与率0
    assert compute_metrics("buy", 995, 1000, 995, 996, 975, 980, 0.01).market_share == 0.0


def test_priority_and_secondary_order():
    snap = [{"stance": "bear", "reason": "割高"}, {"stance": "bear", "reason": "減益基調"}]
    r = _review("buy", 995, 1000, 990, 995, 975, 980, -0.02, dr=0.04, vr=3.0, snap=snap, days=1)
    assert r.primary == "地合い悪化"
    assert r.secondary == ["急騰後の反動", "ファンダメンタル逆行", "決算イベント", "寄りで下落"]


@pytest.mark.parametrize("dr,vr,expected", [(0.03, 1.0, True), (0.0299, 1.0, False), (0.0, 3.0, True), (0.0, 2.99, False)])
def test_surge_boundary(dr, vr, expected):
    r = _review("buy", 995, 1000, 1000, 1005, 985, 990, 0.002, dr=dr, vr=vr)
    assert (r.primary == "急騰後の反動") is expected


def test_sell_side_surge_is_downside():
    assert _review("sell", 1005, 1000, 1000, 1010, 990, 1006, 0.002, dr=-0.03).primary == "急落後の反発"
    assert _review("sell", 1005, 1000, 1000, 1010, 990, 1006, 0.002, dr=0.03).primary != "急落後の反発"


def test_fundamental_contrary_and_earnings_boundaries():
    contrary = [{"stance": "bull", "reason": "割安"}, {"stance": "bull", "reason": "増益基調"}, {"stance": "bear", "reason": "52週高値圏"}]
    r = _review("sell", 1005, 1000, 1000, 1010, 990, 1006, 0.002, snap=contrary)
    assert r.primary == "ファンダメンタル逆行" and "割安・増益基調・52週高値圏" in r.text
    even = [{"stance": "bull", "reason": "割安"}, {"stance": "bear", "reason": "割高"}]
    assert _review("sell", 1005, 1000, 1000, 1010, 990, 1006, 0.002, snap=even).primary == "個別要因"
    assert _review("buy", 995, 1000, 1000, 1005, 985, 990, 0.002, days=2).primary == "決算イベント"
    assert _review("buy", 995, 1000, 1000, 1005, 985, 990, 0.002, days=3).primary == "個別要因"


def test_no_assertive_wording():
    r = _review("sell", 1005, 1000, 1020, 1030, 1010, 1025, 0.012)
    for bad in ("必ず", "確実", "保証", "間違いなく"):
        assert bad not in r.text


# ---- 用語の説明 ----
def test_glossary_filters_terms_in_order_and_explains_review_terms():
    text = "寄り付きのギャップ。PBR 0.66倍で割安。日経平均が動いた。"
    assert [t for t, _ in terms_in(text)] == ["日経平均", "寄り付き", "ギャップ", "PBR", "割安"]
    assert terms_in("専門用語なし") == []
    used = {t for t, _ in terms_in(_review("sell", 1005, 1000, 1020, 1030, 1010, 1025, 0.012).text)}
    assert {"ギャップ", "寄り付き", "終値", "約定"} <= used
    used2 = {t for t, _ in terms_in(_review("buy", 995, 1000, 990, 995, 980, 985, -0.02).text)}
    assert {"日経平均", "超過", "終値"} <= used2
    assert len({t for t, _ in GLOSSARY}) == len(GLOSSARY)  # 重複なし


# ---- DB・レポート・サイト ----
@pytest.fixture
def db(tmp_path):
    p = str(tmp_path / "t.db")
    init_db(p)
    return p


def _insert(db, code, side="sell", is_win=0, filled=1, anomaly=0, fjson=None, edays=None, pdate="2026-11-09"):
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO predictions (prediction_date, code, name, side, total_score, technical_score, earnings_score, "
        "entry_price, reasons, target_date, evaluated, filled, target_low, target_high, target_close, target_open, "
        "result_return, is_win, created_at, pred_close, pred_daily_return, pred_volume_ratio, market_return, "
        "miss_causes, data_anomaly, fundamental_json, earnings_days) VALUES (?, ?, ?, ?, 1, 1, 0, 1005, '[]', '2026-11-10', "
        "1, ?, 1010, 1030, 1025, 1020, -0.0049, ?, 'now', 1000, 0.0, 1.0, 0.012, '[\"寄りで上昇\"]', ?, ?, ?)",
        (pdate, code, code, side, filled, is_win, anomaly, fjson, edays),
    )
    conn.commit(); conn.close()


def test_update_miss_reviews_creates_updates_and_deletes(db):
    _insert(db, "A")
    _insert(db, "WIN", is_win=1)
    _insert(db, "UNF", filled=0, is_win=None)
    _insert(db, "ANOM", anomaly=1)
    assert update_miss_reviews(db) == 1
    assert update_miss_reviews(db) == 0  # 何度実行しても同じ
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT primary_cause, secondary_causes, review_text FROM miss_reviews").fetchall()
    assert len(row) == 1 and row[0][0] == "寄りで上昇" and json.loads(row[0][1]) == ["地合い上昇"]
    # 再計算で的中に変わった行のメモは消える
    conn.execute("UPDATE predictions SET is_win = 1 WHERE code = 'A'"); conn.commit(); conn.close()
    update_miss_reviews(db)
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM miss_reviews").fetchone()[0] == 0
    conn.close()


def test_save_predictions_records_prediction_time_materials(db):
    from analysis.scoring import RankedCandidate
    from tracking.predictions_db import save_predictions

    c = RankedCandidate(code="X", name="X", total_score=3, technical_score=2, earnings_score=1, volume_ratio=2.0,
                        entry_price=995.0, side="buy", day_close=1000.0)
    save_predictions(db, date(2026, 11, 9), date(2026, 11, 10), [c], {"X": ('[{"stance":"bull"}]', 5)})
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT fundamental_json, earnings_days FROM predictions").fetchone() == ('[{"stance":"bull"}]', 5)
    conn.close()


def test_missed_report_site_flow_shows_review_and_glossary(db, tmp_path):
    from report.build_site import build_index
    from report.generate_report import generate_report
    from tracking.missed import get_missed_predictions
    from tracking.predictions_db import WinRateStats
    from analysis.scoring import RankedCandidate

    _insert(db, "A")
    update_miss_reviews(db)
    missed = get_missed_predictions(db, "sell")
    assert len(missed) == 1 and missed[0].review.startswith("主因: 寄りで上昇")
    st = WinRateStats(1, 1, 0, 0.0)
    cand = RankedCandidate(code="6954", name="ファナック", total_score=3, technical_score=2, earnings_score=1,
                           volume_ratio=2.0, entry_price=5608.8, side="sell", day_close=5600.0)
    text = generate_report(date(2026, 11, 9), date(2026, 11, 10), [], [cand], st, st, sell_missed=missed)
    assert " | 主因: 寄りで上昇" in text
    reports = tmp_path / "reports"; reports.mkdir()
    (reports / "2026-11-09.md").write_text(text, encoding="utf-8")
    page = build_index(reports, tmp_path / "docs", "x").read_text(encoding="utf-8")
    assert '<p class="mi-review">主因: 寄りで上昇' in page and '<br>次回への検討:' in page
    assert '<section class="glossary">' in page and "<dt>ギャップ</dt>" in page and "<dt>日経平均</dt>" in page


def test_report_without_reviews_still_parses(tmp_path):
    from report.parse_report import parse_report

    md = ("# 日本株デイクローズ・リサーチレポート 2026-11-06\n\n## 不的中の履歴（買い）\n\n"
          "- 2026-11-04 | 2026-11-05 | A（1111） | 995.0円 | -1.00% | 地合い悪化 | 指値995.0円 → 終値980.0円\n")
    parsed = parse_report(md)
    assert len(parsed.buy_missed) == 1 and parsed.buy_missed[0].review == ""
