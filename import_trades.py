"""SBI証券の取引結果CSVを取り込み、損益カレンダー用の trades/daily_pnl.json を更新する。

使い方:
    python import_trades.py 取引結果.csv

保存するのは日付・損益・返済の件数だけ。銘柄名・株数・単価は保存しない。CSV自体もリポジトリに置かない。
"""

import sys
from pathlib import Path

from tracking.trade_import import load_daily_pnl, merge_daily_pnl, parse_daily_pnl, save_daily_pnl

OUT = Path("trades/daily_pnl.json")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("使い方: python import_trades.py 取引結果.csv")
        return 2
    new = parse_daily_pnl(Path(argv[1]).read_bytes())
    if not new:
        print("信用返済の損益が見つかりませんでした。CSVの形式を確認してください。")
        return 1
    save_daily_pnl(OUT, merge_daily_pnl(load_daily_pnl(OUT), new))
    for d, v in sorted(new.items()):
        print(f"{d}  {v['pnl']:+,}円（返済{v['trades']}件）")
    print(f"合計 {sum(v['pnl'] for v in new.values()):+,}円 → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
