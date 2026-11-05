import sqlite3
from datetime import date

from analysis.scoring import RankedCandidate
from tracking.predictions_db import init_db, record_evaluation, save_predictions
from tracking.unfilled import build_unfilled_reason, get_unfilled_predictions


def test_buy_reason_1():
    # 差 = 1012.0-1000.0 = 12.0 / 12.0÷1000.0 = 1.20%
    assert build_unfilled_reason("buy", 1000.0, 1012.0, 1030.0) == (
        "対象日の安値1,012.0円が参考指値1,000.0円まで下がらず（差12.0円・1.20%）"
    )


def test_buy_reason_2():
    # 差 = 5620.0-5608.8 = 11.2 / 11.2÷5608.8 ≈ 0.1997 -> 0.20%
    assert "差11.2円・0.20%" in build_unfilled_reason("buy", 5608.8, 5620.0, 5700.0)


def test_sell_reason_1():
    # 差 = 4051.2-4040.0 = 11.2 / 11.2÷4051.2 ≈ 0.2765 -> 0.28%
    assert build_unfilled_reason("sell", 4051.2, 3900.0, 4040.0) == (
        "対象日の高値4,040.0円が参考指値4,051.2円まで上がらず（差11.2円・0.28%）"
    )


def test_sell_reason_2():
    # 差 = 1000.0-999.5 = 0.5 / 0.5÷1000.0 = 0.05%
    assert "差0.5円・0.05%" in build_unfilled_reason("sell", 1000.0, 950.0, 999.5)


def test_reason_has_no_assertive_wording():
    for side in ("buy", "sell"):
        text = build_unfilled_reason(side, 1000.0, 1012.0, 990.0)
        assert not any(w in text for w in ("必ず", "保証", "確実"))


def _cand(code, name, price, side):
    return RankedCandidate(
        code=code, name=name, total_score=3, technical_score=2, earnings_score=1,
        volume_ratio=2.0, entry_price=price, reasons=[], side=side,
    )


def test_get_unfilled_filters_orders_and_splits_by_side(tmp_path):
    db = str(tmp_path / "p.db")
    init_db(db)
    save_predictions(db, date(2026, 10, 26), date(2026, 10, 27), [_cand("1", "A", 1000.0, "buy"), _cand("2", "B", 1000.0, "buy")])
    save_predictions(db, date(2026, 10, 27), date(2026, 10, 28), [_cand("3", "C", 1000.0, "buy"), _cand("4", "D", 1000.0, "sell")])
    conn = sqlite3.connect(db)
    ids = {r[1]: r[0] for r in conn.execute("SELECT id, code FROM predictions")}
    conn.close()

    record_evaluation(db, ids["1"], target_low=1012.0, target_high=1030.0, target_close=1020.0)  # 不成立
    record_evaluation(db, ids["2"], target_low=1000.0, target_high=1030.0, target_close=1020.0)  # 安値==指値 -> 約定
    record_evaluation(db, ids["3"], target_low=1005.0, target_high=1010.0, target_close=1008.0)  # 不成立
    record_evaluation(db, ids["4"], target_low=950.0, target_high=999.0, target_close=960.0)      # 売り不成立

    buys = get_unfilled_predictions(db, "buy")
    assert [u.code for u in buys] == ["3", "1"]  # 新しい予測日が先
    assert [u.code for u in get_unfilled_predictions(db, "sell")] == ["4"]
    assert buys[1].reason.startswith("対象日の安値1,012.0円")


def test_unevaluated_is_not_listed(tmp_path):
    db = str(tmp_path / "p.db")
    init_db(db)
    save_predictions(db, date(2026, 10, 26), date(2026, 10, 27), [_cand("1", "A", 1000.0, "buy")])
    assert get_unfilled_predictions(db, "buy") == []
