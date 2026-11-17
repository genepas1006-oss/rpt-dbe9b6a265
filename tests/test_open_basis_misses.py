"""不的中の履歴・検証メモを始値→終値の基準にそろえる（2026-11-17承認・段階C2）の手計算ケース。"""

import json
import sqlite3

import pytest

from tracking.miss_reviews import update_miss_reviews
from tracking.missed import get_missed_predictions
from tracking.predictions_db import init_db
from tracking.refill import backfill_open_misses


def _ins(db, code, *, filled, result, oc, open_, close, anomaly=0, pred_close=2000.0, market=0.0):
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO predictions (prediction_date, code, name, side, total_score, technical_score, earnings_score, "
        "entry_price, reasons, target_date, evaluated, filled, target_low, target_high, target_close, target_open, "
        "result_return, is_win, created_at, pred_close, pred_daily_return, pred_volume_ratio, market_return, "
        "oc_return, data_anomaly) VALUES ('2026-11-09', ?, ?, 'buy', 1, 1, 0, 2000, '[]', '2026-11-10', 1, ?, "
        "1990, 2020, ?, ?, ?, ?, 'now', ?, 0.0, 1.0, ?, ?, ?)",
        (code, code, filled, close, open_, result, None if result is None else int(result > 0), pred_close, market, oc, anomaly),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def db(tmp_path):
    p = str(tmp_path / "t.db")
    init_db(p)
    _ins(p, "R1", filled=1, result=0.0025, oc=-5 / 2010, open_=2010.0, close=2005.0)      # 指値では利益、始値基準は不的中
    _ins(p, "R2", filled=0, result=None, oc=-0.01, open_=2020.0, close=1999.8, market=-0.012)  # 不成立、始値基準で不的中
    _ins(p, "R3", filled=1, result=-0.005, oc=0.01, open_=1990.0, close=2009.9)            # 指値では損失、始値基準は的中
    _ins(p, "R4", filled=1, result=-0.001, oc=0.0, open_=2000.0, close=2000.0)             # 同値は不的中
    _ins(p, "R5", filled=1, result=0.01, oc=0.005, open_=2000.0, close=2010.0)             # 的中
    _ins(p, "R6", filled=1, result=-0.02, oc=-0.02, open_=2000.0, close=1960.0, anomaly=1)  # データ異常
    _ins(p, "R7", filled=1, result=-0.02, oc=-0.02, open_=2000.0, close=1960.0, pred_close=None)  # 予測時の値が未記録
    return p


def test_c2_missed_list_membership(db):
    n = backfill_open_misses(db)
    assert n == 3  # R1, R2, R4 に原因タグを付ける（R7は予測時の値がなく付けられない）
    assert backfill_open_misses(db) == 0  # 何度実行しても同じ
    codes = sorted(m.code for m in get_missed_predictions(db, "buy"))
    assert codes == ["R1", "R2", "R4"]


def test_c2_unfilled_row_gets_market_cause_and_detail(db):
    backfill_open_misses(db)
    r2 = next(m for m in get_missed_predictions(db, "buy") if m.code == "R2")
    assert "地合い悪化" in r2.causes  # 日経平均 -1.2% は -1% 以下
    assert r2.result_return == pytest.approx(-0.01)
    assert "指値: 不成立" in r2.detail and r2.detail.startswith("始値2,020.0円 → 終値1,999.8円")
    r1 = next(m for m in get_missed_predictions(db, "buy") if m.code == "R1")
    assert "指値: 約定 +0.25%" in r1.detail  # 指値では利益だが、始値基準では不的中


def test_c2_review_uses_open_price(db):
    backfill_open_misses(db)
    assert update_miss_reviews(db) == 3
    r1 = next(m for m in get_missed_predictions(db, "buy") if m.code == "R1")
    assert "始値2,010.0円" in r1.review and "終値で-0.25%" in r1.review  # (2,005-2,010)÷2,010 = -0.249%
    assert "約定価格" not in r1.review
    conn = sqlite3.connect(db)
    metrics = json.loads(conn.execute("SELECT metrics FROM miss_reviews WHERE prediction_id = (SELECT id FROM predictions WHERE code='R1')").fetchone()[0])
    conn.close()
    assert metrics["basis"] == "open"


def test_c2_old_style_reviews_are_rebuilt(db):
    backfill_open_misses(db)
    update_miss_reviews(db)
    conn = sqlite3.connect(db)
    # 始値基準の印（basis）が無い古いメモは削除して作り直す
    conn.execute("UPDATE miss_reviews SET metrics = '{\"fill_price\": 1}' WHERE prediction_id = (SELECT id FROM predictions WHERE code='R1')")
    conn.commit()
    conn.close()
    assert update_miss_reviews(db) == 1
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM miss_reviews WHERE metrics LIKE '%basis%'").fetchone()[0] == 3
    conn.close()


def test_c2_record_evaluation_tags_unfilled_open_misses(tmp_path):
    """答え合わせ時にも、指値が不成立で始値基準の不的中なら原因タグが付く。"""
    from datetime import date

    from analysis.scoring import RankedCandidate
    from tracking.predictions_db import record_evaluation, save_predictions

    db = str(tmp_path / "e.db")
    init_db(db)
    c = RankedCandidate(code="U", name="U", total_score=3, technical_score=2, earnings_score=1, volume_ratio=1.2,
                        entry_price=995.0, side="buy", day_close=1000.0, daily_return=0.01)
    save_predictions(db, date(2026, 11, 5), date(2026, 11, 6), [c])
    conn = sqlite3.connect(db)
    pid = conn.execute("SELECT id FROM predictions").fetchone()[0]
    conn.close()
    # 安値996 > 指値995 → 不成立。始値1,000→終値990 → 始値基準で不的中
    record_evaluation(db, pid, target_low=996, target_high=1002, target_close=990,
                      actual_date=date(2026, 11, 6), target_open=1000, market_return=-0.015)
    [m] = get_missed_predictions(db, "buy")
    assert m.limit_filled == 0 and "地合い悪化" in m.causes
