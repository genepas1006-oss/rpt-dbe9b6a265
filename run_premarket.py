"""寄り前（朝、米国市場の確定後）に、環境認識（米国市場→日本株全体の想定ギャップの目安）を更新する。

使い方（平日 8:00〜8:55 頃に実行。先に run_daily.py を一度実行して data/market_gaps.json を作っておく）:
    python run_premarket.py             # 本日（日本時間）向け
    python run_premarket.py --date 2026-11-10

結果は reports/premarket.json に保存し、サイトを作り直して公開する。売買の助言ではなく、環境認識の目安。
"""

import argparse
import sys
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from analysis.futures_gap import compute_futures_gap
from analysis.market_gaps import load_market_gaps
from data_sources.yfinance_source import YFinanceSource
from report.build_site import build_index
from tracking.virtual_fund import get_default_virtual_fund
from report.premarket import compute_premarket, save_premarket
from report.publish import publish_docs

DB_PATH = "data/predictions.db"
MARKET_GAPS_PATH = Path("data/market_gaps.json")
REPORTS_DIR = Path("reports")
DOCS_DIR = Path("docs")
US_SYMBOL = "^GSPC"
FUTURES_SYMBOLS = ("NIY=F", "NKD=F")  # 日経225先物（CME・円建て→ドル建ての順に試す）


def main() -> int:
    parser = argparse.ArgumentParser(description="寄り前の環境認識を更新する")
    parser.add_argument("--date", type=str, default=None, help="対象日（YYYY-MM-DD）。省略時は本日（日本時間）")
    parser.add_argument("--no-publish", action="store_true", help="サイトの作り直しと公開をしない")
    args = parser.parse_args()

    now = datetime.now(ZoneInfo("Asia/Tokyo"))
    for_date = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else now.date()
    if for_date.weekday() >= 5:
        print(f"{for_date} は土日のため、更新しません。")
        return 0

    gaps = load_market_gaps(MARKET_GAPS_PATH)
    if not gaps:
        print(f"{MARKET_GAPS_PATH} がありません。先に run_daily.py を実行してください。")
        return 1

    source = YFinanceSource()
    us_bars = source.get_symbol_bars(US_SYMBOL, min(gaps) - timedelta(days=10), for_date)
    pm, reason = compute_premarket(gaps, us_bars, for_date, now.strftime("%Y-%m-%d %H:%M"))
    if pm is None:
        print(f"環境認識を更新できませんでした: {reason}")
        return 1

    # 日経225先物（夜間）ベースの想定。取れなくても、米国市場ベースの結果だけで続ける
    fut, fut_reason = None, "先物の取得に失敗しました（取得制限・休場など）"
    for symbol in FUTURES_SYMBOLS:
        try:
            fut, fut_reason = compute_futures_gap(source.get_symbol_hourly_bars(symbol), gaps, for_date, symbol)
        except Exception as e:  # noqa: BLE001
            fut, fut_reason = None, f"先物の計算に失敗しました: {e}"
        if fut is not None:
            break
    pm = replace(pm, futures=fut, futures_note=None if fut else fut_reason)
    if fut:
        print(f"先物 {fut.symbol} {fut.move * 100:+.2f}% → 想定ギャップ 約{fut.expected_gap * 100:+.1f}%（推測）")
    else:
        print(f"先物ベースの想定は出せませんでした: {fut_reason}")

    save_premarket(REPORTS_DIR / "premarket.json", pm)
    print(
        f"{for_date} 向け: 米国 {pm.us_return * 100:+.2f}%（{pm.us_date}）→ 想定ギャップ 約{pm.expected_gap * 100:+.1f}%（推測）"
    )
    if args.no_publish:
        return 0

    build_index(
        REPORTS_DIR, DOCS_DIR, now.strftime("%Y-%m-%d %H:%M"), gaps, get_default_virtual_fund(DB_PATH)
    )
    result = publish_docs(Path(__file__).parent, f"docs: {for_date.isoformat()} 環境認識の更新")
    print(f"[publish] {result.status}: {result.detail}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
