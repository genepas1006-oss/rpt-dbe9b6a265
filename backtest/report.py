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


def build_execution_markdown(
    results: Results, period_labels: dict[str, str], title: str = "約定方法の比較バックテスト", cost_note: str | None = None
) -> str:
    """約定方法×選び方の比較表。results のキーは「選び方 / 約定方法」。"""
    lines = [
        f"# {title}",
        "",
        "選び方: top=スコア上位5件 / reversal=逆張りの上位5件 / all=全候補の平均（スコア不問の比較用基準）。",
        "約定率は、成行の条件では100%。平均リターン・的中率は約定した取引のみ。"
        + (cost_note or "手数料・スリッページは含まない。"),
        "◎ は、前半・後半の両方で平均リターンがプラスの条件（偶然を含み得る。デモ期間での追跡が必要）。",
        "（結果は過去の傾向であり、将来の成績を保証するものではありません。）",
        "",
    ]
    for side, label in (("buy", "買い"), ("sell", "売り")):
        for period in ("train", "valid"):
            lines += [
                f"## {label} / {period_labels[period]}",
                "",
                "| 条件 | 取引数 | 約定率 | 的中率 | 平均リターン | 平均勝ち | 平均負け | 勝ち幅÷負け幅 | |",
                "|---|---|---|---|---|---|---|---|---|",
            ]
            for name, by_period in results.items():
                m = by_period[period][side]
                mark = "◎" if positive_both(results, name, side) else ""
                lines.append(
                    f"| {name} | {m.count} | {_pct(m.fill_rate)} | {_pct(m.win_rate)} | "
                    f"{_pct(m.avg_return, 2)} | {_pct(m.avg_win, 2)} | {_pct(m.avg_loss, 2)} | "
                    f"{_num(m.payoff_ratio)} | {mark} |"
                )
            lines.append("")
    return "\n".join(lines)


def _ci(boot, pct: bool = True) -> str:
    if boot.mean is None or boot.ci_low is None:
        return "-"
    return f"{boot.mean * 100:+.2f}%[{boot.ci_low * 100:+.2f},{boot.ci_high * 100:+.2f}] p={boot.p_not_positive:.4f}"


def build_preopen_markdown(rows, period_labels: dict[str, str], cost: float, resamples: int) -> str:
    """rows: [(StrategyResult(前半), StrategyResult(後半), 採用候補か)]"""
    lines = [
        "# 寄り前に分かる情報でのデイトレ検証（始値で入り、同日の終値で決済）",
        "",
        f"想定始値は実際の始値で代用（寄り前気配とのずれ分、やや楽観的）。費用は往復{cost * 100:g}%を差し引いた値も併記。",
        f"差は『同じ向きの全件』との比較。[ ]は日単位ブートストラップ{resamples:,}回の95%区間、pは差がプラスでない確率。",
        "◎ は事前に決めた採用候補の条件（前半で多重比較補正後p<0.05/48、後半でp<0.05、両期間で費用後プラス）を満たしたもの。",
        "（過去の傾向であり、将来の成績を保証するものではありません。）",
        "",
    ]
    for period, label in (("train", period_labels["train"]), ("valid", period_labels["valid"])):
        lines += [
            f"## {label}",
            "",
            "| 条件 | 件数 | 的中率[95%区間] | 的中率の差 | 平均リターン | 費用後 | 平均リターンの差 | |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for train, valid, ok in rows:
            r = train if period == "train" else valid
            wr = "-" if r.win_rate is None else f"{r.win_rate * 100:.1f}%[{r.wilson[0] * 100:.1f},{r.wilson[1] * 100:.1f}]"
            avg = "-" if r.avg_gross is None else f"{r.avg_gross * 100:+.3f}%"
            net = "-" if r.avg_net is None else f"{r.avg_net * 100:+.3f}%"
            lines.append(
                f"| {r.name} | {r.n} | {wr} | {_ci(r.win_boot)} | {avg} | {net} | {_ci(r.ret_boot)} | {'◎' if ok else ''} |"
            )
        lines.append("")
    return "\n".join(lines)
