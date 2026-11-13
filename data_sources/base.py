"""データソースの抽象インターフェース。

分析ロジック（analysis/, tracking/）はこのインターフェースにのみ依存し、
具体的な取得元（yfinance、将来のSBI証券ローカルAPI等）を意識しない設計とする。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class DailyBar:
    """1日分の四本値・出来高。"""

    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True)
class IntradayBar:
    """日中の足（始まりの時刻、日本時間）。"""

    start: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True)
class HourBar:
    """1時間足（始まりの時刻は日本時間。足は start から1時間）。先物の夜間の動きなどに使う。"""

    start: datetime
    close: float


@dataclass(frozen=True)
class Fundamentals:
    """ファンダメンタル指標（取得できた項目のみ。取得できないものはNone）。比率は小数（0.1 = 10%）。"""

    per: float | None = None  # 実績PER（倍）。赤字などで算出できない場合はNone
    pbr: float | None = None
    dividend_yield: float | None = None
    roe: float | None = None
    revenue_growth: float | None = None
    earnings_growth: float | None = None
    target_price: float | None = None  # アナリスト平均目標株価（円）
    analyst_count: int | None = None
    week52_high: float | None = None
    week52_low: float | None = None


class DataSource(ABC):
    @abstractmethod
    def get_daily_bars(self, code: str, start: date, end: date) -> list[DailyBar]:
        """指定銘柄コードの日次四本値・出来高を [start, end] の範囲で取得する。

        取得できない日は結果に含めない（欠損として扱う）。
        銘柄自体が取得不可の場合は空リストを返す（例外を送出しない）。
        """
        raise NotImplementedError

    def get_intraday_bars(self, code: str, day: date) -> list[IntradayBar]:
        """指定日の日中の足（5分足）。取得できない場合は空リスト（例外を送出しない）。"""
        return []

    def get_fundamentals(self, code: str) -> Fundamentals | None:
        """指定銘柄のファンダメンタル指標を取得する。未対応のデータ元・取得失敗はNone（例外を送出しない）。"""
        return None

    @abstractmethod
    def get_earnings_dates(self, code: str) -> list[date]:
        """指定銘柄の決算発表日（既知の過去日・予定日）を取得する。

        取得できない場合は空リストを返す（例外を送出しない）。
        """
        raise NotImplementedError
