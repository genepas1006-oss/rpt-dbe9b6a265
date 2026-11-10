"""仮想資金（デモ）の残高推移。予測を毎日 残高/枠数 ずつ投入した場合の損益を積み上げる。

承認済み設計（2026-11-09）:
    - 開始残金から、予測日ごとに「その日の開始残高 / 枠数」を1銘柄あたりの投入額とする（複利）。
    - 損益 = 投入額 × result_return（約定した予測のみ。不成立は現金のまま）。
    - 買い・売りは合算した1つの口座として扱う。
    - その予測日の全予測が答え合わせ済みになった日だけ残高に反映する（未確定の日は含めない）。
    - 手数料・単元株・信用取引の費用は考慮しない参考値。
"""

import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class FundDay:
    prediction_date: date
    target_date: date
    start_balance: float
    pnl: float
    buy_pnl: float
    sell_pnl: float
    filled_count: int
    end_balance: float

    @property
    def pnl_pct(self) -> float:
        """その日の損益を、その日の開始残高に対する割合で表す。"""
        return self.pnl / self.start_balance


@dataclass(frozen=True)
class VirtualFund:
    initial: float
    days: list[FundDay] = field(default_factory=list)

    @property
    def balance(self) -> float:
        return self.days[-1].end_balance if self.days else self.initial

    @property
    def last_day(self) -> FundDay | None:
        return self.days[-1] if self.days else None

    @property
    def total_pnl(self) -> float:
        return self.balance - self.initial

    @property
    def total_pct(self) -> float:
        return self.total_pnl / self.initial


def get_virtual_fund(db_path: str, start_date: date, initial: float, slots: int) -> VirtualFund:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT prediction_date, target_date, side, evaluated, filled, result_return, data_anomaly "
            "FROM predictions WHERE variant = 'main' AND prediction_date >= ? ORDER BY prediction_date, id",
            (start_date.isoformat(),),
        ).fetchall()
    finally:
        conn.close()

    by_day: dict[str, list[tuple]] = {}
    for r in rows:
        by_day.setdefault(r[0], []).append(r)

    balance = float(initial)
    days: list[FundDay] = []
    for pred_date in sorted(by_day):
        day_rows = by_day[pred_date]
        if any(not r[3] for r in day_rows):  # 未確定の予測が残る日は反映しない
            continue
        allocation = balance / slots
        buy_pnl = sell_pnl = 0.0
        filled_count = 0
        for _, _, side, _, filled, result_return, anomaly in day_rows:
            if anomaly or not filled or result_return is None:  # データ異常（株式分割の疑い）の行は損益に含めない
                continue
            filled_count += 1
            pnl = allocation * result_return
            if side == "sell":
                sell_pnl += pnl
            else:
                buy_pnl += pnl
        pnl_total = buy_pnl + sell_pnl
        days.append(
            FundDay(
                prediction_date=date.fromisoformat(pred_date),
                target_date=date.fromisoformat(max(r[1] for r in day_rows)),
                start_balance=balance,
                pnl=pnl_total,
                buy_pnl=buy_pnl,
                sell_pnl=sell_pnl,
                filled_count=filled_count,
                end_balance=balance + pnl_total,
            )
        )
        balance += pnl_total
    return VirtualFund(initial=float(initial), days=days)


def get_default_virtual_fund(db_path: str) -> VirtualFund | None:
    """config.py の設定で仮想資金を計算する。DBが無い等で計算できなければNone（表示を省略する）。"""
    import config

    if not Path(db_path).exists():  # connect() が空のDBを作ってしまうのを避ける
        return None
    try:
        return get_virtual_fund(
            db_path,
            date.fromisoformat(config.VIRTUAL_FUND_START_DATE),
            config.VIRTUAL_FUND_INITIAL,
            config.VIRTUAL_FUND_SLOTS,
        )
    except sqlite3.Error:
        return None
