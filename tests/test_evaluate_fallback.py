"""祝日フォールバック・二重登録防止・重複掃除のテスト（2026-11-06承認ケース）。"""

import sqlite3
import sys
from datetime import date
from pathlib import Path

from analysis.scoring import RankedCandidate
from data_sources.base import DailyBar, DataSource
from tracking.evaluate import evaluate_pending_predictions
from tracking.predictions_db import init_db, replace_predictions, save_predictions

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from dedupe_predictions import find_duplicate_ids  # noqa: E402


class _Src(DataSource):
    def __init__(self, bars):
        self.bars = bars

    def get_daily_bars(self, code, start, end):
        return [b for b in self.bars if start <= b.trade_date <= end]

    def get_earnings_dates(self, code):
        return []


def _bar(d, low, high, close):
    return DailyBar(trade_date=d, open=low, high=high, low=low, close=close, volume=1)


def _cand(code, price, side="buy"):
    return RankedCandidate(
        code=code, name=f"n{code}", total_score=3, technical_score=2, earnings_score=1,
        volume_ratio=2.0, entry_price=price, reasons=[], side=side,
    )


def _db(tmp_path):
    db = str(tmp_path / "p.db")
    init_db(db)
    return db


def _row(db, code):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT evaluated, filled, target_date, result_return, is_win FROM predictions WHERE code=?",
            (code,),
        ).fetchone()
    finally:
        conn.close()


H, NEXT = date(2026, 11, 3), date(2026, 11, 4)


def test_A_holiday_target_uses_next_trading_day_buy(tmp_path):
    db = _db(tmp_path)
    save_predictions(db, date(2026, 11, 2), H, [_cand("A", 1000.0)])
    assert evaluate_pending_predictions(db, _Src([_bar(NEXT, 990, 1010, 1005)]), as_of=NEXT) == 1
    evaluated, filled, target, ret, win = _row(db, "A")
    assert (evaluated, filled, target, win) == (1, 1, "2026-11-04", 1)
    assert abs(ret - 0.005) < 1e-12  # (1005-1000)/1000


def test_B_holiday_target_sell_unfilled(tmp_path):
    db = _db(tmp_path)
    save_predictions(db, date(2026, 11, 2), H, [_cand("B", 1000.0, "sell")])
    evaluate_pending_predictions(db, _Src([_bar(NEXT, 950, 995, 960)]), as_of=NEXT)
    assert _row(db, "B") == (1, 0, "2026-11-04", None, None)  # 995 < 1000


def test_C_normal_day_unchanged_target_date(tmp_path):
    db = _db(tmp_path)
    d = date(2026, 11, 6)
    save_predictions(db, date(2026, 11, 5), d, [_cand("C", 1000.0)])
    evaluate_pending_predictions(db, _Src([_bar(d, 990, 1010, 1005)]), as_of=d)
    assert _row(db, "C")[2] == "2026-11-06"


def test_D_does_not_use_future_bar(tmp_path):
    db = _db(tmp_path)
    save_predictions(db, date(2026, 11, 2), H, [_cand("D", 1000.0)])
    assert evaluate_pending_predictions(db, _Src([_bar(NEXT, 990, 1010, 1005)]), as_of=H) == 0
    assert _row(db, "D")[0] == 0


def test_E_no_bars_stays_pending(tmp_path):
    db = _db(tmp_path)
    save_predictions(db, date(2026, 11, 2), H, [_cand("E", 1000.0)])
    assert evaluate_pending_predictions(db, _Src([]), as_of=NEXT) == 0
    assert _row(db, "E")[0] == 0


def _count(db, where="1=1"):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM predictions WHERE {where}").fetchone()[0]
    finally:
        conn.close()


D0, T0 = date(2026, 11, 2), date(2026, 11, 3)


def test_1_rerun_keeps_only_latest_set(tmp_path):
    db = _db(tmp_path)
    replace_predictions(db, D0, T0, "buy", [_cand(str(i), 1000.0) for i in range(5)])
    replace_predictions(db, D0, T0, "buy", [_cand(f"n{i}", 1000.0) for i in range(5)])
    assert _count(db) == 5
    assert _count(db, "code LIKE 'n%'") == 5


def test_2_rerun_with_no_candidates_clears_unevaluated(tmp_path):
    db = _db(tmp_path)
    replace_predictions(db, D0, T0, "sell", [_cand(str(i), 1000.0, "sell") for i in range(5)])
    replace_predictions(db, D0, T0, "sell", [])
    assert _count(db) == 0


def test_3_evaluated_rows_are_left_alone(tmp_path):
    db = _db(tmp_path)
    replace_predictions(db, D0, T0, "buy", [_cand("X", 1000.0)])
    evaluate_pending_predictions(db, _Src([_bar(T0, 990, 1010, 1005)]), as_of=T0)
    replace_predictions(db, D0, T0, "buy", [_cand("Y", 1000.0), _cand("Z", 1000.0)])
    assert _count(db) == 1
    assert _count(db, "code='X' AND evaluated=1") == 1


def test_4_sides_are_independent(tmp_path):
    db = _db(tmp_path)
    replace_predictions(db, D0, T0, "sell", [_cand("S", 1000.0, "sell")])
    replace_predictions(db, D0, T0, "buy", [_cand("B1", 1000.0)])
    replace_predictions(db, D0, T0, "buy", [_cand("B2", 1000.0)])
    assert _count(db, "side='sell'") == 1
    assert _count(db, "side='buy'") == 1


def test_5_other_dates_untouched(tmp_path):
    db = _db(tmp_path)
    replace_predictions(db, date(2026, 10, 30), date(2026, 11, 2), "buy", [_cand("O", 1000.0)])
    replace_predictions(db, D0, T0, "buy", [_cand("N", 1000.0)])
    replace_predictions(db, D0, T0, "buy", [_cand("N2", 1000.0)])
    assert _count(db, "code='O'") == 1


def test_dedupe_script_keeps_only_latest_batch(tmp_path):
    db = _db(tmp_path)
    save_predictions(db, D0, T0, [_cand(str(i), 1000.0) for i in range(5)])  # 10:07の実行
    conn = sqlite3.connect(db)
    conn.execute("UPDATE predictions SET created_at='2026-11-02T10:07:00'")
    conn.commit()
    conn.close()
    save_predictions(db, D0, T0, [_cand(f"n{i}", 1000.0) for i in range(5)])  # 15:37の実行
    conn = sqlite3.connect(db)
    conn.execute("UPDATE predictions SET created_at='2026-11-02T15:37:00' WHERE code LIKE 'n%'")
    conn.commit()
    dups = find_duplicate_ids(conn)
    conn.close()
    assert len(dups) == 1
    assert dups[0][:2] == ("2026-11-02", "buy")
    assert len(dups[0][2]) == 5
