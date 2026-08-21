"""データソースの抽象インターフェース。

分析ロジック（analysis/, tracking/）はこのインターフェースにのみ依存し、
具体的な取得元（yfinance、将来のSBI証券ローカルAPI等）を意識しない設計とする。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DailyBar:
    """1日分の四本値・出来高。"""

    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


class DataSource(ABC):
    @abstractmethod
    def get_daily_bars(self, code: str, start: date, end: date) -> list[DailyBar]:
        """指定銘柄コードの日次四本値・出来高を [start, end] の範囲で取得する。

        取得できない日は結果に含めない（欠損として扱う）。
        銘柄自体が取得不可の場合は空リストを返す（例外を送出しない）。
        """
        raise NotImplementedError

    @abstractmethod
    def get_earnings_dates(self, code: str) -> list[date]:
        """指定銘柄の決算発表日（既知の過去日・予定日）を取得する。

        取得できない場合は空リストを返す（例外を送出しない）。
        """
        raise NotImplementedError
