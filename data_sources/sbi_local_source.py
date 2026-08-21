"""SBI証券 HYPER SBI 2 のローカルAPIを想定したデータソース（未実装）。

HYPER SBI 2に外部から呼び出せるAPIが実在するかどうか、2026-08-21時点では
確認が取れていない。ユーザー側でHYPER SBI 2の設定画面に「APIサーバー機能」
「外部連携」等の項目が実在することを確認できた場合のみ、本実装に着手すること。

確認が取れるまでは、この実装を使用しないこと（run_daily.py等から呼び出さない）。
"""

from datetime import date

from data_sources.base import DailyBar, DataSource


class SBILocalSource(DataSource):
    def get_daily_bars(self, code: str, start: date, end: date) -> list[DailyBar]:
        raise NotImplementedError(
            "HYPER SBI 2のローカルAPIの実在・仕様が未確認のため未実装です。"
            "設定画面でAPI機能を確認できてから実装してください。"
        )

    def get_earnings_dates(self, code: str) -> list[date]:
        raise NotImplementedError(
            "HYPER SBI 2のローカルAPIの実在・仕様が未確認のため未実装です。"
            "設定画面でAPI機能を確認できてから実装してください。"
        )
