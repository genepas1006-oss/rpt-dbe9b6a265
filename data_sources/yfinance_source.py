"""yfinanceを用いたデフォルトデータソース実装。"""

import logging
from datetime import date, timedelta

import yfinance as yf

from config import yfinance_symbol
from data_sources.base import DailyBar, DataSource, Fundamentals

logger = logging.getLogger(__name__)


class YFinanceSource(DataSource):
    def get_daily_bars(self, code: str, start: date, end: date) -> list[DailyBar]:
        return self.get_symbol_bars(yfinance_symbol(code), start, end)

    def get_symbol_bars(self, symbol: str, start: date, end: date) -> list[DailyBar]:
        """yfinanceシンボル（例: "7203.T", 指数なら "^N225"）で日次バーを取得する。"""
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

    def get_fundamentals(self, code: str) -> Fundamentals | None:
        symbol = yfinance_symbol(code)
        try:
            info = yf.Ticker(symbol).info
        except Exception:
            logger.warning("ファンダメンタル取得に失敗: %s", symbol, exc_info=True)
            return None
        if not info:
            return None

        def num(key: str) -> float | None:
            v = info.get(key)
            return float(v) if isinstance(v, (int, float)) and v == v else None

        per = num("trailingPE")
        dy = num("dividendYield")  # yfinanceは%表記（4.33 = 4.33%）
        count = num("numberOfAnalystOpinions")
        return Fundamentals(
            per=per if per is not None and per > 0 else None,
            pbr=num("priceToBook"),
            dividend_yield=dy / 100 if dy is not None else None,
            roe=num("returnOnEquity"),
            revenue_growth=num("revenueGrowth"),
            earnings_growth=num("earningsGrowth"),
            target_price=num("targetMeanPrice"),
            analyst_count=int(count) if count is not None else None,
            week52_high=num("fiftyTwoWeekHigh"),
            week52_low=num("fiftyTwoWeekLow"),
        )

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
