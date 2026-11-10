"""テスト枠（値動き重視）のテスト。承認済みの手計算ケース T1〜T4（2026-11-10）。"""

import sqlite3
from datetime import date

import pytest

from analysis.scoring import CandidateInput, rank_candidates
from analysis.technical import TechnicalScore
from analysis.volatile_pool import day_range_ratio, select_volatile_pool
from tracking.predictions_db import MAIN, VOLATILE, get_win_rate_stats, init_db, replace_predictions, save_predictions


def test_t1_day_range_ratio():
    assert day_range_ratio(1030.0, 1000.0, 1020.0) == pytest.approx(30 / 1020)  # 2.94%
    assert day_range_ratio(1000.0, 1000.0, 1000.0) == 0.0
    assert day_range_ratio(1030.0, 1000.0, 0.0) == 0.0


def _cand(code, rng_pct, score=0):
    close = 1000.0
    tech = TechnicalScore(volume_ratio=1.0, daily_return=0.0, close_position=0.5, volume_points=0, return_points=0,
                          close_position_points=0, technical_score=score) if score else None
    return CandidateInput(code=code, name=code, close=close, technical=tech, earnings=None,
                          open=close, high=close + close * rng_pct / 100, low=close, volume=1000)


def test_t2_top_30_percent_count_and_ties():
    ten = [_cand(f"C{i}", float(i)) for i in range(1, 11)]  # 値幅率 1〜10%
    assert [c.code for c in select_volatile_pool(ten)] == ["C8", "C9", "C10"]  # k = 3
    tied = [_cand(f"T{i}", v) for i, v in enumerate([10, 9, 8, 8, 7, 6, 5, 4, 3, 2])]
    assert [c.code for c in select_volatile_pool(tied)] == ["T0", "T1", "T2", "T3"]  # 3番目が8% → 同値も含め4件
    assert len(select_volatile_pool([_cand(f"U{i}", i + 1.0) for i in range(225)])) == 68  # 225×0.3=67.5 の切り上げ
    assert select_volatile_pool([]) == []


def test_t3_ranking_after_filtering():
    pool_input = [_cand("A", 8.0, 2), _cand("B", 9.0, 4), _cand("C", 10.0, 3),
                  _cand("LOWVOL_HIGHSCORE", 1.0, 5), _cand("D", 7.0, 0)]
    pool = select_volatile_pool(pool_input)  # 5件 → k=2 → 上位は 10%・9%
    assert {c.code for c in pool} == {"B", "C"}
    ranked = rank_candidates(pool, top_n=5, side="buy")
    assert [r.code for r in ranked] == ["B", "C"]  # スコア4 → 3。値幅率が低くスコアの高い銘柄は選ばれない
    # 対象が3銘柄（8%・9%・10%）のとき: スコア2・4・3 → 順位は 9% → 10% → 8%
    three = select_volatile_pool([_cand("A", 8.0, 2), _cand("B", 9.0, 4), _cand("C", 10.0, 3), _cand("X", 1.0, 5),
                                  _cand("Y", 2.0, 5), _cand("Z", 3.0, 5), _cand("W", 4.0, 5), _cand("V", 5.0, 5),
                                  _cand("U", 6.0, 5)])  # 9件 → k=3
    assert [r.code for r in rank_candidates(three, top_n=5, side="buy")] == ["B", "C", "A"]


@pytest.fixture
def db(tmp_path):
    p = str(tmp_path / "t.db")
    init_db(p)
    return p


def _ranked(code, side="buy"):
    from analysis.scoring import RankedCandidate

    return RankedCandidate(code=code, name=code, total_score=3, technical_score=2, earnings_score=1, volume_ratio=2.0,
                           entry_price=995.0, side=side, day_close=1000.0)


def test_t4_variants_are_separated(db):
    d, t = date(2026, 11, 9), date(2026, 11, 10)
    save_predictions(db, d, t, [_ranked("MAIN1")])
    save_predictions(db, d, t, [_ranked("EXP1")], variant=VOLATILE)
    conn = sqlite3.connect(db)
    for code, win in (("MAIN1", 1), ("EXP1", 0)):
        conn.execute("UPDATE predictions SET evaluated=1, filled=1, is_win=?, result_return=?, target_close=1010 WHERE code=?",
                     (win, 0.01 if win else -0.01, code))
    conn.commit(); conn.close()
    main, exp = get_win_rate_stats(db, "buy"), get_win_rate_stats(db, "buy", VOLATILE)
    assert (main.total_predictions, main.win_count) == (1, 1)  # テスト枠の分は本番に入らない
    assert (exp.total_predictions, exp.win_count) == (1, 0)
    from tracking.virtual_fund import get_virtual_fund

    fund = get_virtual_fund(db, d, 1_000_000, 10)
    assert fund.days[0].pnl == pytest.approx(100_000 * 0.01)  # 本番の1件だけ（+1,000円）。テスト枠の−1%は入らない


def test_replace_predictions_is_per_variant(db):
    d, t = date(2026, 11, 9), date(2026, 11, 10)
    replace_predictions(db, d, t, "buy", [_ranked("M")])
    replace_predictions(db, d, t, "buy", [_ranked("E1")], variant=VOLATILE)
    replace_predictions(db, d, t, "buy", [_ranked("E2")], variant=VOLATILE)  # テスト枠だけ置き換わる
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT code, variant FROM predictions ORDER BY id").fetchall()
    conn.close()
    assert rows == [("M", MAIN), ("E2", VOLATILE)]


def test_report_and_site_show_collapsed_experiment_block(tmp_path):
    from report.build_site import build_index
    from report.generate_report import generate_report
    from tracking.predictions_db import WinRateStats

    st = WinRateStats(1, 1, 1, 1.0)
    text = generate_report(date(2026, 11, 9), date(2026, 11, 10), [_ranked("1111")], [_ranked("2222", "sell")], st, st,
                           exp_buy_candidates=[_ranked("3333")], exp_sell_candidates=[], exp_buy_stats=st, exp_sell_stats=st)
    assert "## テスト枠の買い候補（2026-11-10向け・値動き重視）" in text and "## テスト枠の成績（買い・値動き重視）" in text
    reports = tmp_path / "reports"; reports.mkdir()
    (reports / "2026-11-09.md").write_text(text, encoding="utf-8")
    page = build_index(reports, tmp_path / "docs", "x").read_text(encoding="utf-8")
    assert '<details class="experiment">' in page and "<details class=\"experiment\" open" not in page  # 初期状態は閉じる
    assert "試験運用・効果は未確認" in page and "3333" in page
    assert page.index('class="sides"') < page.index('class="experiment"')  # 本番の直下
    # 本番の候補数（買い1・売り1）には、テスト枠の候補が混ざらない
    from report.parse_report import parse_report

    parsed = parse_report(text)
    assert [c.code for c in parsed.buy_candidates] == ["1111"] and [c.code for c in parsed.exp_buy_candidates] == ["3333"]
    assert "<dt>テスト枠</dt>" in page and "<dt>当日値幅率</dt>" not in page  # 説明文に出る語だけ


def test_no_experiment_block_when_absent(tmp_path):
    from report.build_site import build_index
    from report.generate_report import generate_report
    from tracking.predictions_db import WinRateStats

    st = WinRateStats(1, 1, 1, 1.0)
    reports = tmp_path / "reports"; reports.mkdir()
    (reports / "2026-11-09.md").write_text(generate_report(date(2026, 11, 9), date(2026, 11, 10), [_ranked("1111")], [], st, st), encoding="utf-8")
    assert '<details class="experiment"' not in build_index(reports, tmp_path / "docs", "x").read_text(encoding="utf-8")
