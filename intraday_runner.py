"""寄り枠（9:25）・昼の予想（11:50）の作成。承認済み設計（2026-11-11）。試験運用で、効果は未確認。

使い方（平日）:
    python run_open.py     # 9:25ごろ。寄り付きのギャップが大きい銘柄（逆張り）
    python run_lunch.py    # 11:50ごろ。前場の動きが大きい銘柄（逆張り）
データ元は約15分遅れのため、9:20より前・11:45より前に実行すると、足が揃わない銘柄が増える。
対象日の足を取れた銘柄が半数未満なら、レポートの作成と公開を中止する（休場日・取得失敗）。
"""

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from pathlib import Path

from analysis.intraday_sets import IntradayInput, select_lunch, select_open_gap
from analysis.market_gaps import load_market_gaps
from config import NIKKEI225
from data_sources.base import DataSource
from data_sources.yfinance_source import YFinanceSource
from report.build_site import build_index
from report.forecast_set import JST, lunch_set, open_set
from report.intraday_report import generate_intraday_report
from report.publish import publish_docs
from tracking.intraday_db import LUNCH, OPEN_GAP, get_intraday_stats, save_intraday_picks
from tracking.predictions_db import init_db
from tracking.virtual_fund import get_default_virtual_fund

DB_PATH = "data/predictions.db"
REPORTS_DIR = Path("reports")
DOCS_DIR = Path("docs")
MARKET_GAPS_PATH = Path("data/market_gaps.json")
MIN_DATA_RATIO = 0.5
OPEN_WINDOW_END = time(9, 10)  # 寄り付きの足は、9:00〜9:10の間に始まる最初の足
LUNCH_LAST_BAR_FROM = time(11, 20)  # 前場の最後の足は、11:20以降に始まるものが揃っていること
AM_CLOSE = time(11, 30)


class NoIntradayData(RuntimeError):
    """対象日の日中の足がほとんど取得できない（取引前・休場日・取得失敗）。"""


def open_input(code: str, name: str, prev_close: float | None, bars) -> IntradayInput | None:
    """寄り枠の入力: 前日終値と、寄り付き（9:00〜9:10に始まる最初の足）の始値。"""
    if not prev_close or not bars:
        return None
    first = min(bars, key=lambda b: b.start)
    if first.start.astimezone(JST).time() >= OPEN_WINDOW_END:
        return None
    return IntradayInput(code, name, prev_close, first.open)


def lunch_input(code: str, name: str, bars) -> IntradayInput | None:
    """昼の予想の入力: 前場の始値と、11:30までの最後の足の終値（前場の足が揃っているものだけ）。"""
    am = [b for b in bars if b.start.astimezone(JST).time() < AM_CLOSE]
    if not am:
        return None
    first, last = min(am, key=lambda b: b.start), max(am, key=lambda b: b.start)
    if first.start.astimezone(JST).time() >= OPEN_WINDOW_END or last.start.astimezone(JST).time() < LUNCH_LAST_BAR_FROM:
        return None
    return IntradayInput(code, name, first.open, last.close)


def collect_inputs(slot: str, day: date, source: DataSource, universe: list[tuple[str, str]]) -> tuple[list[IntradayInput], int]:
    def job(item):
        code, name = item
        try:
            bars = source.get_intraday_bars(code, day)
            if slot == "open":
                prev = [b for b in source.get_daily_bars(code, day - timedelta(days=10), day - timedelta(days=1))]
                return open_input(code, name, prev[-1].close if prev else None, bars)
            return lunch_input(code, name, bars)
        except Exception:  # noqa: BLE001  1銘柄の失敗で全体を止めない
            return None

    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(job, universe))
    inputs = [r for r in results if r is not None]
    return inputs, len(inputs)


def run_intraday(slot: str, day: date, source: DataSource | None = None, now: datetime | None = None,
                 universe: list[tuple[str, str]] | None = None, publish: bool = True) -> Path:
    source = source or YFinanceSource()
    now = (now or datetime.now(JST)).astimezone(JST)
    universe = universe or list(NIKKEI225)
    Path("data").mkdir(exist_ok=True)
    REPORTS_DIR.mkdir(exist_ok=True)
    init_db(DB_PATH)

    inputs, loaded = collect_inputs(slot, day, source, universe)
    if len(universe) == 0 or loaded / len(universe) < MIN_DATA_RATIO:
        raise NoIntradayData(
            f"{day.isoformat()}の日中の足を取得できた銘柄が{loaded}/{len(universe)}件のため、"
            f"{'寄り枠' if slot == 'open' else '昼の予想'}の作成と公開を中止しました（取引前・休場日・取得失敗の可能性）。"
        )
    select = select_open_gap if slot == "open" else select_lunch
    buy, sell, buy_extra, sell_extra = select(inputs)
    fset = (open_set if slot == "open" else lunch_set)(day, now)
    variant = OPEN_GAP if slot == "open" else LUNCH
    save_intraday_picks(DB_PATH, day, variant, [*buy, *sell], fset)
    text = generate_intraday_report(
        slot, day, fset, buy, sell, buy_extra, sell_extra,
        get_intraday_stats(DB_PATH, variant, "buy"), get_intraday_stats(DB_PATH, variant, "sell"),
    )
    path = REPORTS_DIR / f"{day.isoformat()}-{slot}.md"
    path.write_text(text, encoding="utf-8")
    if publish:
        gaps = load_market_gaps(MARKET_GAPS_PATH)
        build_index(REPORTS_DIR, DOCS_DIR, now.strftime("%Y-%m-%d %H:%M"), gaps, get_default_virtual_fund(DB_PATH))
        label = "寄り枠" if slot == "open" else "昼の予想"
        result = publish_docs(Path(__file__).parent, f"docs: {day.isoformat()} {label}の更新")
        print(f"[publish] {result.status}: {result.detail}")
        if not result.ok:
            raise RuntimeError(result.detail)
    return path


def main(slot: str) -> int:
    parser = argparse.ArgumentParser(description="寄り枠・昼の予想を作成する（試験運用）")
    parser.add_argument("--date", type=str, default=None, help="対象日（YYYY-MM-DD）。省略時は本日（日本時間）")
    parser.add_argument("--no-publish", action="store_true", help="サイトの作り直しと公開をしない")
    args = parser.parse_args()
    now = datetime.now(JST)
    day = date.fromisoformat(args.date) if args.date else now.date()
    if day.weekday() >= 5:
        print(f"{day} は土日のため、作成しません。")
        return 0
    try:
        path = run_intraday(slot, day, now=now, publish=not args.no_publish)
    except NoIntradayData as e:
        print(e)
        return 1
    print(f"作成しました: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "open"))
