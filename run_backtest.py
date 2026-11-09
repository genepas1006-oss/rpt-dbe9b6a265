"""日経225の過去データで、地合い・過熱度フィルターの効果を検証する（デモ検証用）。

使い方:
    python run_backtest.py               # 取得（初回のみ数分）→ 検証 → data/backtest_result.md に保存
    python run_backtest.py --refresh     # キャッシュを捨てて取得し直す
    python run_backtest.py --no-earnings # 決算日の取得を省略（速いが本番と条件が少し異なる）

結果は過去の傾向であり、将来の成績を保証するものではない。
"""

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from backtest.engine import (
    Variant,
    apply_variant,
    baseline,
    build_trading_days,
    combine,
    market_filter,
    overheat_filter,
    reversal,
    split_days,
    summarize,
)
from backtest.execution import apply_rule, default_rules
from backtest.report import build_execution_markdown, build_markdown
from config import NIKKEI225
from data_sources.base import DailyBar
from data_sources.yfinance_source import YFinanceSource

HISTORY_DAYS = 900
INDEX_SYMBOL = "^N225"
CACHE_PATH = Path("data/backtest_cache.json")
RESULT_PATH = Path("data/backtest_result.md")
EXECUTION_RESULT_PATH = Path("data/backtest_execution.md")

DEV_THRESHOLDS = (0.05, 0.08, 0.10, 0.15)
RSI_THRESHOLDS = (60, 70, 80)


def _bars_to_json(bars: list[DailyBar]) -> list[list]:
    return [[b.trade_date.isoformat(), b.open, b.high, b.low, b.close, b.volume] for b in bars]


def _bars_from_json(rows: list[list]) -> list[DailyBar]:
    return [DailyBar(date.fromisoformat(r[0]), r[1], r[2], r[3], r[4], int(r[5])) for r in rows]


def fetch_all(use_earnings: bool, today: date) -> dict:
    source = YFinanceSource()
    start = today - timedelta(days=HISTORY_DAYS)
    print(f"日経平均を取得中（{start} 〜 {today}）...")
    index_bars = source.get_symbol_bars(INDEX_SYMBOL, start, today)
    if len(index_bars) < 60:
        raise SystemExit("日経平均のデータを取得できませんでした。ネットワークを確認してください。")

    bars_by_code, earnings_by_code = {}, {}
    for n, (code, _name) in enumerate(NIKKEI225, start=1):
        bars = source.get_daily_bars(code, start, today)
        if bars:
            bars_by_code[code] = bars
        if use_earnings:
            earnings_by_code[code] = [d.isoformat() for d in source.get_earnings_dates(code)]
        if n % 25 == 0:
            print(f"  {n}/{len(NIKKEI225)} 銘柄")
    return {
        "fetched_on": today.isoformat(),
        "use_earnings": use_earnings,
        "index": _bars_to_json(index_bars),
        "bars": {c: _bars_to_json(b) for c, b in bars_by_code.items()},
        "earnings": earnings_by_code,
    }


def load_or_fetch(refresh: bool, use_earnings: bool, today: date) -> dict:
    if CACHE_PATH.exists() and not refresh:
        cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        if cached.get("use_earnings") == use_earnings:
            print(f"キャッシュを使用: {CACHE_PATH}（{cached['fetched_on']} 取得）")
            return cached
    data = fetch_all(use_earnings, today)
    CACHE_PATH.parent.mkdir(exist_ok=True)
    CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def build_variants() -> list[Variant]:
    singles = [market_filter()]
    singles += [overheat_filter(dev_threshold=d) for d in DEV_THRESHOLDS]
    singles += [overheat_filter(rsi_threshold=r) for r in RSI_THRESHOLDS]
    combos = [combine(market_filter(), v) for v in singles[1:]]
    reverse = [reversal(), combine(reversal(), market_filter())]
    return [baseline(), *singles, *combos, *reverse]


def run_execution(train_days, valid_days, labels) -> None:
    selections = [("top", baseline(), "top"), ("reversal", reversal(), "top"), ("all", baseline(), "all")]
    results = {}
    for rule in default_rules():
        for label, variant, select in selections:
            name = f"{label} / {rule.name}"
            print(f"  検証: {name}")
            results[name] = {}
            for period, period_days in (("train", train_days), ("valid", valid_days)):
                trades = apply_rule(period_days, variant, rule, select)
                results[name][period] = {"buy": summarize(trades, "buy"), "sell": summarize(trades, "sell")}
    markdown = build_execution_markdown(results, labels)
    EXECUTION_RESULT_PATH.write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"\n結果を保存しました: {EXECUTION_RESULT_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser(description="地合い・過熱度フィルターのバックテスト")
    parser.add_argument("--refresh", action="store_true", help="キャッシュを捨てて取得し直す")
    parser.add_argument("--execution", action="store_true", help="約定方法（指値/成行/持ち越し/利確損切り）を比較する")
    parser.add_argument("--no-earnings", action="store_true", help="決算日の取得を省略する")
    args = parser.parse_args()

    data = load_or_fetch(args.refresh, not args.no_earnings, date.today())
    index_bars = _bars_from_json(data["index"])
    bars_by_code = {c: _bars_from_json(rows) for c, rows in data["bars"].items()}
    earnings = {c: [date.fromisoformat(d) for d in ds] for c, ds in data["earnings"].items()}
    names = dict(NIKKEI225)

    print("各営業日の候補を組み立て中...")
    days = build_trading_days(bars_by_code, names, index_bars, earnings)
    train_days, valid_days = split_days(days)
    labels = {
        "train": f"前半（{train_days[0].day}〜{train_days[-1].day}）",
        "valid": f"後半（{valid_days[0].day}〜{valid_days[-1].day}）",
    }

    if args.execution:
        run_execution(train_days, valid_days, labels)
        return 0

    results = {}
    for variant in build_variants():
        print(f"  検証: {variant.name}")
        results[variant.name] = {}
        for period, period_days in (("train", train_days), ("valid", valid_days)):
            trades = apply_variant(period_days, variant)
            results[variant.name][period] = {
                "buy": summarize(trades, "buy"),
                "sell": summarize(trades, "sell"),
            }

    markdown = build_markdown(results, labels)
    RESULT_PATH.write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"\n結果を保存しました: {RESULT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
