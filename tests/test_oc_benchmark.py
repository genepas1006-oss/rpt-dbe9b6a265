"""全銘柄平均との比較を始値→終値の基準にそろえる（2026-11-17承認・段階C1）の手計算ケース。"""

import sqlite3
from datetime import date

import pytest

from data_sources.base import DailyBar
from report.generate_report import OC_EFFECT_LABEL, _score_effect_lines
from tracking.benchmark import (
    compute_missing_oc_benchmarks,
    compute_universe_oc_return,
    get_score_effect_oc,
)
from tracking.predictions_db import init_db

D1, D2, D3 = date(2026, 11, 9), date(2026, 11, 10), date(2026, 11, 11)


def _bar(d, o, c):
    return DailyBar(d, o, max(o, c), min(o, c), c, 1)


def _universe(day, nxt):
    return {
        "A": [_bar(day, 100, 100), _bar(nxt, 100, 102)],  # +2%
        "B": [_bar(day, 200, 200), _bar(nxt, 200, 198)],  # -1%
        "C": [_bar(day, 50, 50), _bar(nxt, 50, 50)],      # 0%
        "D": [_bar(day, 10, 10)],                          # 次の足なし → 除外
        "E": [_bar(day, 10, 10), _bar(nxt, 0, 5)],         # 始値0 → 除外
    }


def test_universe_oc_return_hand_calc():
    u = _universe(D1, D2)
    buy = compute_universe_oc_return("buy", u, D1)
    sell = compute_universe_oc_return("sell", u, D1)
    assert buy[0] == pytest.approx((0.02 - 0.01 + 0.0) / 3) and buy[1] == 3  # +0.333%
    assert sell[0] == pytest.approx(-(0.02 - 0.01) / 3) and sell[1] == 3      # -0.333%
    assert compute_universe_oc_return("buy", u, date(2026, 1, 1)) is None


def _pred(db, d, oc, side="buy", evaluated=1, anomaly=0, variant="main"):
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO predictions (prediction_date, code, name, side, total_score, technical_score, earnings_score, "
        "entry_price, reasons, target_date, evaluated, oc_return, data_anomaly, variant, created_at) "
        "VALUES (?, 'X', 'X', ?, 1, 1, 0, 100, '[]', '2026-11-12', ?, ?, ?, ?, 'now')",
        (d.isoformat(), side, evaluated, oc, anomaly, variant),
    )
    conn.commit()
    conn.close()


def test_score_effect_oc_two_days(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    for oc in (0.010, -0.005, 0.020, 0.0, -0.015):  # 1日目のTOP5: 平均 +0.20%
        _pred(db, D1, oc)
    _pred(db, D2, 0.005)                               # 2日目: +0.5%
    _pred(db, D3, 0.03)                                # 3日目は全銘柄平均なし → 除外
    _pred(db, D1, 0.5, anomaly=1)                      # データ異常は除外
    _pred(db, D1, None)                                # 始値なしは除外
    bars = {k: v for k, v in _universe(D1, D2).items()}
    # 2日目の全銘柄は +0.1%（1銘柄: 始値1000→終値1001）
    bars2 = {"Z": [_bar(D2, 1000, 1000), _bar(D3, 1000, 1001)]}
    for k, v in bars2.items():
        bars[k] = v
    assert compute_missing_oc_benchmarks(db, bars) == 2  # D1 と D2（D3 は次の足がなく計算できない）
    eff = get_score_effect_oc(db, "buy")
    assert eff.days == 2
    assert eff.top_avg == pytest.approx((0.0020 + 0.005) / 2)
    bench_d1 = (0.02 - 0.01 + 0.0) / 3
    assert eff.bench_avg == pytest.approx((bench_d1 + 0.001) / 2)
    assert eff.excess == pytest.approx(((0.002 - bench_d1) + (0.005 - 0.001)) / 2)
    assert compute_missing_oc_benchmarks(db, bars) == 0  # 何度実行しても同じ


def test_report_line_labels():
    from tracking.benchmark import ScoreEffect

    eff = ScoreEffect(days=2, top_avg=0.0035, bench_avg=0.00217, excess=0.00133)
    [line] = _score_effect_lines(eff, OC_EFFECT_LABEL)
    assert line == "- 全銘柄平均との差（スコアの効果の目安・始値→終値）: +0.13%（TOP5 +0.35% / 全銘柄 +0.22%・2日）"
    [ref] = _score_effect_lines(eff)
    assert ref.startswith("- 全銘柄平均との差（参考・指値で約定した場合）: +0.13%")
