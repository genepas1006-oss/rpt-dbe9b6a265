"""本日が市場の営業日か判定する（日経平均に本日の足があるか）。

GitHub Actionsの日次実行で、祝日・休場日に「候補なし」レポートを公開しないために使う。
判定できない場合（取得失敗）は営業日として扱い、実行を止めない。
結果は GITHUB_OUTPUT に open=true/false として書き出す。
"""

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import yfinance as yf


def main() -> int:
    today = datetime.now(ZoneInfo("Asia/Tokyo")).date()
    is_open = True
    try:
        hist = yf.Ticker("^N225").history(period="7d")
        if not hist.empty:
            is_open = hist.index[-1].date() == today
    except Exception as e:  # 取得失敗時は営業日扱いにする
        print(f"[check_market_open] 判定失敗のため営業日として扱います: {e}", file=sys.stderr)

    print(f"{today} market open: {is_open}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"open={'true' if is_open else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
