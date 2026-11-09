"""バックテスト結果の表示用整形（Markdown）。"""

from backtest.engine import Metrics

Results = dict[str, dict[str, dict[str, Metrics]]]  # variant -> {"train"/"valid"} -> {"buy"/"sell"} -> Metrics


def _pct(x: float | None, digits: int = 1) -> str:
    return "-" if x is None else f"{x * 100:.{digits}f}%"


def _num(x: float | None) -> str:
    return "-" if x is None else f"{x:.2f}"


def improved(results: Results, name: str, side: str) -> bool:
    """前半・後半の両方で、baselineより平均リターンが良ければ True。"""
    for period in ("train", "valid"):
        base = results["baseline"][period][side].avg_return
        cur = results[name][period][side].avg_return
        if base is None or cur is None or cur <= base:
            return False
    return True


def positive_both(results: Results, name: str, side: str) -> bool:
    """前半・後半の両方で、平均リターンがプラスなら True。"""
    for period in ("train", "valid"):
        cur = results[name][period][side].avg_return
        if cur is None or cur <= 0:
            return False
    return True


def build_markdown(results: Results, period_labels: dict[str, str]) -> str:
    lines = [
        "# バックテスト結果",
        "",
        "平均リターン・的中率は約定した取引のみで集計。手数料・スリッページは含まない。",
        "✓ は、前半・後半の両方で baseline より平均リターンが高い条件（偶然でも付き得る目安。",
        "候補数・勝ち幅÷負け幅・条件間の一貫性もあわせて見ること）。",
        "◎ は、前半・後半の両方で平均リターンがプラスの条件（これも偶然を含み得る。デモ期間での追跡が必要）。",
        "（結果は過去の傾向であり、将来の成績を保証するものではありません。）",
        "",
    ]
    for side, label in (("buy", "買い"), ("sell", "売り")):
        for period in ("train", "valid"):
            lines += [
                f"## {label} / {period_labels[period]}",
                "",
                "| 条件 | 候補数 | 約定率 | 的中率 | 平均リターン | 平均勝ち | 平均負け | 勝ち幅÷負け幅 | |",
                "|---|---|---|---|---|---|---|---|---|",
            ]
            for name, by_period in results.items():
                m = by_period[period][side]
                mark = ""
                if name != "baseline" and improved(results, name, side):
                    mark += "✓"
                if positive_both(results, name, side):
                    mark += "◎"
                lines.append(
                    f"| {name} | {m.count} | {_pct(m.fill_rate)} | {_pct(m.win_rate)} | "
                    f"{_pct(m.avg_return, 2)} | {_pct(m.avg_win, 2)} | {_pct(m.avg_loss, 2)} | "
                    f"{_num(m.payoff_ratio)} | {mark} |"
                )
            lines.append("")
    return "\n".join(lines)
