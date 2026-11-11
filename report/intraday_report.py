"""寄り枠・昼の予想（日中の試験運用枠）のレポート（Markdown）の生成と読み込み。承認済み設計（2026-11-11）。"""

from dataclasses import dataclass, field
from datetime import date

from analysis.intraday_sets import AM_MOVE_THRESHOLD, OPEN_GAP_THRESHOLD, IntradayPick
from report.forecast_set import ForecastSet, from_md_body, to_md_lines

TITLE = {"open": "寄り枠", "lunch": "昼の予想"}
RULE = {
    "open": f"寄り付きが前日終値比 -{OPEN_GAP_THRESHOLD * 100:g}%以下の銘柄を買い、+{OPEN_GAP_THRESHOLD * 100:g}%以上の銘柄を売り（寄りのギャップの逆張り）",
    "lunch": f"前場が始値比 -{AM_MOVE_THRESHOLD * 100:g}%以下の銘柄を買い、+{AM_MOVE_THRESHOLD * 100:g}%以上の銘柄を売り（前場の動きの逆張り）",
}
BASIS = {"open": "寄り付きの始値", "lunch": "後場の始値（12:30の最初の価格）"}
DETAIL_FROM = {"open": ("前日終値", "始値"), "lunch": ("前場始値", "前場終値")}


@dataclass(frozen=True)
class ParsedPick:
    rank: str
    name: str  # 例: ファナック（6954）
    ref_price: str
    move: str
    detail: str


@dataclass(frozen=True)
class ParsedIntraday:
    slot: str
    day: str
    forecast_set: ForecastSet | None
    buy_stats_lines: list[str] = field(default_factory=list)
    sell_stats_lines: list[str] = field(default_factory=list)
    buy_picks: list[ParsedPick] = field(default_factory=list)
    sell_picks: list[ParsedPick] = field(default_factory=list)
    buy_extra: int = 0
    sell_extra: int = 0


def _stats_lines(stats: tuple[int, int] | None) -> list[str]:
    if not stats or stats[0] == 0:
        return ["- 方向の的中率（基準価格→大引け）: データなし"]
    n, hits = stats
    return [f"- 方向の的中率（基準価格→大引け）: {hits / n * 100:.1f}%（{hits}/{n}件）"]


def _pick_lines(slot: str, picks: list[IntradayPick], extra: int, empty: str) -> list[str]:
    if not picks:
        return [empty]
    a, b = DETAIL_FROM[slot]
    lines = [
        f"- {i}位 | {p.name}（{p.code}） | 基準価格 {p.ref_price:,.1f}円 | {p.move * 100:+.2f}% | "
        f"{a}{p.base_close:,.1f}円 → {b}{p.ref_price:,.1f}円"
        for i, p in enumerate(picks, start=1)
    ]
    if extra:
        lines.append(f"- ほか{extra}件")
    return lines


def generate_intraday_report(
    slot: str,
    day: date,
    fset: ForecastSet,
    buy: list[IntradayPick],
    sell: list[IntradayPick],
    buy_extra: int,
    sell_extra: int,
    buy_stats: tuple[int, int] | None,
    sell_stats: tuple[int, int] | None,
) -> str:
    lines = [
        f"# {TITLE[slot]}レポート {day.isoformat()}",
        "",
        "**注意: 試験運用の枠で、効果は未確認です。本番の成績・仮想資金には含めず、別に記録しています。"
        "実発注は行っていません。値動きや勝率を保証するものではありません。**",
        "",
        f"- 選び方: {RULE[slot]}",
        f"- 的中の基準: {BASIS[slot]}から大引けまでに、予想方向（買い=上昇、売り=下落）へ動いたか（同値は外れ）",
        "",
        *to_md_lines(fset),
        "## 枠の成績（買い）",
        *_stats_lines(buy_stats),
        "",
        "## 枠の成績（売り）",
        *_stats_lines(sell_stats),
        "",
        f"## 買い候補（{day.isoformat()}）",
        "",
        *_pick_lines(slot, buy, buy_extra, "該当する買い候補がありませんでした。"),
        "",
        f"## 売り候補（{day.isoformat()}）",
        "",
        *_pick_lines(slot, sell, sell_extra, "該当する売り候補がありませんでした。"),
        "",
    ]
    return "\n".join(lines)


def _parse_picks(body: str) -> tuple[list[ParsedPick], int]:
    picks, extra = [], 0
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("- ほか") and line.endswith("件"):
            extra = int(line.removeprefix("- ほか").removesuffix("件"))
        elif line.startswith("- ") and " | " in line:
            parts = [p.strip() for p in line.removeprefix("- ").split(" | ", 4)]
            if len(parts) == 5:
                picks.append(ParsedPick(parts[0].removesuffix("位"), parts[1], parts[2].removeprefix("基準価格 "), parts[3], parts[4]))
    return picks, extra


def parse_intraday_report(text: str, slot: str, day: str) -> ParsedIntraday:
    import re

    heads = list(re.finditer(r"^## (.+)$", text, re.MULTILINE))
    sections = [(m.group(1).strip(), text[m.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]) for i, m in enumerate(heads)]
    fset, buy_stats, sell_stats, buy, sell, be, se = None, [], [], [], [], 0, 0
    for heading, body in sections:
        lines = [l.strip().removeprefix("- ") for l in body.splitlines() if l.strip().startswith("- ")]
        if heading.startswith("予想セット"):
            fset = from_md_body(body)
        elif heading.startswith("枠の成績（買い"):
            buy_stats = lines
        elif heading.startswith("枠の成績（売り"):
            sell_stats = lines
        elif heading.startswith("買い候補"):
            buy, be = _parse_picks(body)
        elif heading.startswith("売り候補"):
            sell, se = _parse_picks(body)
    return ParsedIntraday(slot, day, fset, buy_stats, sell_stats, buy, sell, be, se)
