"""営業日の計算（土日のみ。日本の祝日は考慮していない既知の簡略化）。"""

from datetime import date, timedelta


def next_business_day(d: date) -> date:
    """土日をスキップした翌営業日を返す（日本の祝日は考慮していない・既知の簡略化）。"""
    next_day = d + timedelta(days=1)
    while next_day.weekday() >= 5:  # 5=土, 6=日
        next_day += timedelta(days=1)
    return next_day
