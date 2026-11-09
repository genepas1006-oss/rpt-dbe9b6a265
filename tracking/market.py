"""指数（日経平均）の日次騰落率。不的中の原因分析で「地合い」の判定に使う。"""

from datetime import date

from data_sources.base import DailyBar


def index_daily_returns(bars: list[DailyBar]) -> dict[date, float]:
    """日付昇順の指数バーから、日付→前日比の辞書を作る（先頭日は前日がないので含まない）。"""
    returns: dict[date, float] = {}
    for prev, cur in zip(bars, bars[1:]):
        if prev.close > 0:
            returns[cur.trade_date] = (cur.close - prev.close) / prev.close
    return returns
