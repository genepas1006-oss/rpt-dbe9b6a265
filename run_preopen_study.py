"""寄り前に分かる情報（ギャップ/ATR・想定値幅・前日出来高・地合い・日足位置）での検証を実行する。

使い方（run_backtest.py で作ったキャッシュを使う。無ければ先に run_backtest.py を実行）:
    python run_preopen_study.py                 # 前半70%・後半30%、ブートストラップ20,000回
    python run_preopen_study.py --resamples 50000

結果は data/preopen_study.md に保存する。過去の傾向であり、将来の成績を保証するものではない。
"""

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from backtest.preopen import (
    BONFERRONI_TESTS,
    build_samples,
    build_strategies,
    evaluate_strategy,
    is_candidate,
    split_samples,
)
from backtest.report import build_preopen_markdown
from data_sources.base import DailyBar
from data_sources.yfinance_source import YFinanceSource
from run_backtest import CACHE_PATH, _bars_from_json, _bars_to_json

PREOPEN_CACHE = Path("data/preopen_cache.json")
RESULT_PATH = Path("data/preopen_study.md")
US_SYMBOL = "^GSPC"
FX_SYMBOL = "USDJPY=X"
COST = 0.001


def load_market_bars(start: date, end: date) -> tuple[list[DailyBar], list[DailyBar]]:
    if PREOPEN_CACHE.exists():
        cached = json.loads(PREOPEN_CACHE.read_text(encoding="utf-8"))
        return _bars_from_json(cached["us"]), _bars_from_json(cached["fx"])
    source = YFinanceSource()
    print(f"米国(S&P500)とドル円を取得中（{start} 〜 {end}）...")
    us = source.get_symbol_bars(US_SYMBOL, start - timedelta(days=10), end)
    fx = source.get_symbol_bars(FX_SYMBOL, start - timedelta(days=10), end)
    PREOPEN_CACHE.write_text(
        json.dumps({"us": _bars_to_json(us), "fx": _bars_to_json(fx)}, ensure_ascii=False), encoding="utf-8"
    )
    return us, fx


def main() -> int:
    parser = argparse.ArgumentParser(description="寄り前情報でのデイトレ検証")
    parser.add_argument("--resamples", type=int, default=20_000)
    args = parser.parse_args()

    if not CACHE_PATH.exists():
        raise SystemExit(f"{CACHE_PATH} がありません。先に python run_backtest.py を実行してください。")
    data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    index_bars = _bars_from_json(data["index"])
    bars_by_code = {c: _bars_from_json(rows) for c, rows in data["bars"].items()}
    us, fx = load_market_bars(index_bars[0].trade_date, index_bars[-1].trade_date)
    print(f"米国 {len(us)}本 / ドル円 {len(fx)}本 / 日経平均 {len(index_bars)}本")

    samples = build_samples(bars_by_code, index_bars, us, fx)
    train, valid = split_samples(samples)
    print(f"サンプル {len(samples):,}件（前半 {len(train):,} / 後半 {len(valid):,}）")
    labels = {
        "train": f"前半（{min(s.day for s in train)}〜{max(s.day for s in train)}）",
        "valid": f"後半（{min(s.day for s in valid)}〜{max(s.day for s in valid)}）",
    }

    rows = []
    for n, strategy in enumerate(build_strategies(), start=1):
        tr = evaluate_strategy(train, strategy, COST, args.resamples)
        va = evaluate_strategy(valid, strategy, COST, args.resamples)
        is_baseline = strategy.name.startswith("ALL_")
        ok = (not is_baseline) and is_candidate(tr, va, BONFERRONI_TESTS)
        rows.append((tr, va, ok))
        print(f"  {n:2d}/50 {strategy.name:28s} 前半n={tr.n:>7,} 後半n={va.n:>7,} {'◎' if ok else ''}")

    markdown = build_preopen_markdown(rows, labels, COST, args.resamples)
    RESULT_PATH.write_text(markdown, encoding="utf-8")
    cands = [tr.name for tr, _, ok in rows if ok]
    print("\n採用候補:", ", ".join(cands) if cands else "なし")
    print(f"結果を保存しました: {RESULT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
