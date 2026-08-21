"""yfinanceを用いたデフォルトデータソース実装。"""

import logging
from datetime import date, timedelta

import yfinance as yf

from config import yfinance_symbol
from data_sources.base import DailyBar, DataSource

logger = logging.getLogger(__name__)


class YFinanceSource(DataSource):
    def get_daily_bars(self, code: str, start: date, end: date) -> list[DailyBar]:
        symbol = yfinance_symbol(code)
        try:
            # yfinanceのhistory()はend未満を返すため、end当日を含めるには+1日する。
            hist = yf.Ticker(symbol).history(
                start=start, end=end + timedelta(days=1), interval="1d"
            )
        except Exception:
            logger.warning("株価取得に失敗: %s", symbol, exc_info=True)
            return []

        if hist.empty:
            return []

        bars = []
        for idx, row in hist.iterrows():
            try:
                bars.append(
                    DailyBar(
                        trade_date=idx.date(),
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        volume=int(row["Volume"]),
                    )
                )
            except (KeyError, ValueError, TypeError):
                logger.warning("株価データの行変換に失敗: %s %s", symbol, idx, exc_info=True)
                continue

        return bars

    def get_earnings_dates(self, code: str) -> list[date]:
        symbol = yfinance_symbol(code)
        try:
            df = yf.Ticker(symbol).get_earnings_dates(limit=20)
        except Exception:
            logger.warning("決算日取得に失敗: %s", symbol, exc_info=True)
            return []

        if df is None or df.empty:
            return []

        return [idx.date() for idx in df.index]
