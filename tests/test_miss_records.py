"""不的中の原因記録（DB移行・保存・評価・履歴取得）のテスト。"""

import json
import sqlite3
from datetime import date

from analysis.scoring import RankedCandidate
from data_sources.base import DailyBar, DataSource
from tracking.evaluate import evaluate_pending_predictions
from tracking.market import index_daily_returns
from tracking.missed import get_missed_predictions
from tracking.predictions_db import init_db, record_evaluation, save_predictions

D0, T0 = date(2026, 11, 5), date(2026, 11, 6)


def _cand(code, side="buy", close=1000.0, daily=0.01, vol=1.2, price=None):
    price = price if price is not None else (995.0 if side == "buy" else 1005.0)
    return RankedCandidate(
        code=code, name=f"n{code}", total_score=3, technical_score=2, earnings_score=1,
        volume_ratio=vol, entry_price=price, reasons=[], side=side,
        day_close=close, daily_return=daily,
    )


def _row(db, code):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT pred_close, pred_daily_return, pred_volume_ratio, target_open, market_return, miss_causes "
            "FROM predictions WHERE code=?", (code,)
        ).fetchone()
    finally:
        conn.close()


def _pid(db, code):
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT id FROM predictions WHERE code=?", (code,)).fetchone()[0]
    finally:
        conn.close()


# ---------------- DB移行 ----------------
def test_init_db_adds_new_columns_to_old_schema(tmp_path):
    db = str(tmp_path / "old.db")
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, prediction_date TEXT NOT NULL, code TEXT NOT NULL,
            name TEXT NOT NULL, side TEXT NOT NULL DEFAULT 'buy', total_score INTEGER NOT NULL,
            technical_score INTEGER NOT NULL, earnings_score INTEGER NOT NULL, entry_price REAL NOT NULL,
            reasons TEXT NOT NULL, target_date TEXT NOT NULL, evaluated INTEGER NOT NULL DEFAULT 0,
            filled INTEGER, target_low REAL, target_high REAL, target_close REAL, result_return REAL,
            is_win INTEGER, created_at TEXT NOT NULL)"""
    )
    conn.execute(
        "INSERT INTO predictions (prediction_date, code, name, total_score, technical_score, earnings_score, "
        "entry_price, reasons, target_date, created_at) VALUES ('2026-10-01','X','x',1,1,0,100,'[]','2026-10-02','t')"
    )
    conn.commit()
    conn.close()

    init_db(db)
    init_db(db)  # 2回呼んでも壊れない

    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(predictions)")}
    old = conn.execute("SELECT code, miss_causes FROM predictions").fetchone()
    conn.close()
    assert {"pred_close", "pred_daily_return", "pred_volume_ratio", "target_open", "market_return", "miss_causes"} <= cols
    assert old == ("X", None)  # 既存の行は残る


# ---------------- 保存 ----------------
def test_save_predictions_stores_prediction_time_values(tmp_path):
    db = str(tmp_path / "p.db")
    init_db(db)
    save_predictions(db, D0, T0, [_cand("A", close=1000.0, daily=0.04, vol=3.5)])
    assert _row(db, "A") == (1000.0, 0.04, 3.5, None, None, None)


# ---------------- 評価での原因記録（承認済みの手計算ケース） ----------------
def _eval(db, code, low, high, close, open_, market):
    record_evaluation(db, _pid(db, code), target_low=low, target_high=high, target_close=close,
                      actual_date=T0, target_open=open_, market_return=market)


def test_miss_records_causes_case1_market_and_gap(tmp_path):
    db = str(tmp_path / "p.db")
    init_db(db)
    save_predictions(db, D0, T0, [_cand("A", close=1000.0, daily=0.01, vol=1.2)])
    _eval(db, "A", low=975, high=992, close=980, open_=990, market=-0.015)  # 約定(975<=995), 終値980 → 負け
    _, _, _, t_open, mkt, causes = _row(db, "A")
    assert (t_open, mkt) == (990, -0.015)
    assert json.loads(causes) == ["地合い悪化", "寄りで下落"]


def test_miss_case2_surge_and_case3_other(tmp_path):
    db = str(tmp_path / "p.db")
    init_db(db)
    save_predictions(db, D0, T0, [_cand("B", daily=0.04, vol=1.1), _cand("C", daily=0.01, vol=1.0)])
    _eval(db, "B", low=985, high=1000, close=990, open_=999, market=0.002)
    _eval(db, "C", low=985, high=1005, close=990, open_=1001, market=0.0)
    assert json.loads(_row(db, "B")[5]) == ["急騰後の反動"]
    assert json.loads(_row(db, "C")[5]) == ["その他"]


def test_win_and_unfilled_have_no_causes(tmp_path):
    db = str(tmp_path / "p.db")
    init_db(db)
    save_predictions(db, D0, T0, [_cand("W", daily=0.04, vol=3.5), _cand("U")])
    _eval(db, "W", low=990, high=1010, close=1005, open_=1001, market=0.0)  # 約定して勝ち
    _eval(db, "U", low=996, high=1010, close=1005, open_=1001, market=0.0)  # 安値996 > 指値995 → 不成立
    assert _row(db, "W")[5] is None
    assert _row(db, "U")[5] is None


def test_row_without_prediction_time_values_gets_no_causes(tmp_path):
    db = str(tmp_path / "p.db")
    init_db(db)
    save_predictions(db, D0, T0, [_cand("O", close=0.0)])  # day_close=0 → pred_close未記録（旧データ相当）
    _eval(db, "O", low=975, high=992, close=980, open_=990, market=-0.02)
    assert _row(db, "O")[5] is None


def test_zero_return_miss_is_tagged(tmp_path):
    db = str(tmp_path / "p.db")
    init_db(db)
    save_predictions(db, D0, T0, [_cand("Z")])
    _eval(db, "Z", low=990, high=1000, close=995, open_=1000, market=0.0)  # 終値=指値 → リターン0 → 的中でない
    assert json.loads(_row(db, "Z")[5]) == ["その他"]


def test_missing_market_data_tags_no_data(tmp_path):
    db = str(tmp_path / "p.db")
    init_db(db)
    save_predictions(db, D0, T0, [_cand("M")])
    _eval(db, "M", low=975, high=992, close=980, open_=1001, market=None)
    assert json.loads(_row(db, "M")[5]) == ["データ不足"]


def test_sell_miss_uses_mirrored_tags(tmp_path):
    db = str(tmp_path / "p.db")
    init_db(db)
    save_predictions(db, D0, T0, [_cand("S", side="sell", close=1000.0, daily=-0.04, vol=1.2)])
    _eval(db, "S", low=1000, high=1030, close=1020, open_=1010, market=0.015)  # 売り指値1005, 高値1030で約定, 終値1020 → 負け
    assert json.loads(_row(db, "S")[5]) == ["地合い上昇", "寄りで上昇", "急落後の反発"]


# ---------------- evaluate_pending_predictions ----------------
class _Src(DataSource):
    def __init__(self, bars):
        self.bars = bars

    def get_daily_bars(self, code, start, end):
        return [b for b in self.bars if start <= b.trade_date <= end]

    def get_earnings_dates(self, code):
        return []


def test_evaluate_passes_open_and_market_return_of_actual_date(tmp_path):
    db = str(tmp_path / "p.db")
    init_db(db)
    holiday, nxt = date(2026, 11, 3), date(2026, 11, 4)
    save_predictions(db, date(2026, 11, 2), holiday, [_cand("H")])
    bars = [DailyBar(nxt, 990, 1000, 975, 980, 1)]  # 始値990, 安値975 → 約定 → 終値980で負け
    evaluate_pending_predictions(db, _Src(bars), as_of=nxt, market_returns={holiday: 0.05, nxt: -0.015})
    _, _, _, t_open, mkt, causes = _row(db, "H")
    assert (t_open, mkt) == (990, -0.015)  # 実際に使った営業日(11/4)の値を使う
    assert json.loads(causes) == ["地合い悪化", "寄りで下落"]


def test_evaluate_without_market_returns_still_works(tmp_path):
    db = str(tmp_path / "p.db")
    init_db(db)
    save_predictions(db, D0, T0, [_cand("N")])
    evaluate_pending_predictions(db, _Src([DailyBar(T0, 1001, 1002, 975, 980, 1)]), as_of=T0)
    assert json.loads(_row(db, "N")[5]) == ["データ不足"]


# ---------------- 指数の前日比 ----------------
def test_index_daily_returns_hand_calc():
    ds = [date(2026, 11, 2), date(2026, 11, 4), date(2026, 11, 5)]
    bars = [DailyBar(d, c, c, c, c, 1) for d, c in zip(ds, [100.0, 101.0, 99.0])]
    r = index_daily_returns(bars)
    assert ds[0] not in r
    assert r[ds[1]] == 0.01  # (101-100)/100
    assert abs(r[ds[2]] - (-2 / 101)) < 1e-12  # ≒ -1.98%


def test_index_daily_returns_edge_cases():
    assert index_daily_returns([]) == {}
    assert index_daily_returns([DailyBar(date(2026, 1, 1), 1, 1, 1, 1, 1)]) == {}
    bars = [DailyBar(date(2026, 1, 1), 0, 0, 0, 0.0, 1), DailyBar(date(2026, 1, 2), 1, 1, 1, 1.0, 1)]
    assert index_daily_returns(bars) == {}  # 前日終値0は計算しない


# ---------------- 履歴の取得 ----------------
def test_get_missed_predictions_filters_orders_and_formats_detail(tmp_path):
    db = str(tmp_path / "p.db")
    init_db(db)
    save_predictions(db, date(2026, 11, 4), D0, [_cand("OLD", close=1000.0)])
    save_predictions(db, D0, T0, [_cand("NEW1", close=1000.0), _cand("WIN", close=1000.0),
                                  _cand("SELL", side="sell", close=1000.0, daily=-0.04)])
    _eval(db, "OLD", low=975, high=992, close=980, open_=990, market=-0.015)
    _eval(db, "NEW1", low=975, high=992, close=980, open_=999, market=0.0)
    _eval(db, "WIN", low=990, high=1010, close=1005, open_=1001, market=0.0)
    _eval(db, "SELL", low=1000, high=1030, close=1020, open_=1010, market=0.015)

    buys = get_missed_predictions(db, "buy")
    assert [m.code for m in buys] == ["NEW1", "OLD"]  # 新しい予測日が先、勝ちは含まない
    assert [m.code for m in get_missed_predictions(db, "sell")] == ["SELL"]
    old = buys[1]
    assert old.causes == ["地合い悪化", "寄りで下落"]
    assert old.detail == "指値995.0円 → 終値980.0円／日経平均-1.50%／寄り付きは予測日終値比-1.00%"
    assert old.result_return == (980 - 995.0) / 995.0


def test_get_missed_predictions_ignores_wins_even_if_causes_were_written(tmp_path):
    """防御的な条件: 的中・不成立の行に何らかの理由で原因が入っていても、履歴には出さない。"""
    db = str(tmp_path / "p.db")
    init_db(db)
    save_predictions(db, D0, T0, [_cand("W"), _cand("U")])
    _eval(db, "W", low=990, high=1010, close=1005, open_=1001, market=0.0)  # 勝ち
    _eval(db, "U", low=996, high=1010, close=1005, open_=1001, market=0.0)  # 不成立
    conn = sqlite3.connect(db)
    conn.execute("UPDATE predictions SET miss_causes = '[\"その他\"]'")
    conn.commit()
    conn.close()
    assert get_missed_predictions(db, "buy") == []
