"""generate_report.py が出力する固定フォーマットのMarkdownを構造化データに戻す。

docs/のHTML生成（report/build_site.py）専用のパーサー。generate_report.pyの
出力フォーマットが変わる場合はこちらも合わせて見直すこと。
2026-10-26以前の旧フォーマット（買い候補のみ、見出しが「本日のTOP候補」）も
買い候補として読み込めるようにしている。
"""

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ParsedCandidate:
    rank: int
    name: str
    code: str
    score: int
    breakdown: str
    entry_price: str
    reasons: list[str] = field(default_factory=list)
    day_summary: str = ""
    one_point: str = ""
    outlook: str = ""


@dataclass(frozen=True)
class ParsedUnfilled:
    prediction_date: str
    target_date: str
    name: str
    entry_price: str
    reason: str


@dataclass(frozen=True)
class ParsedMiss:
    prediction_date: str
    target_date: str
    name: str
    entry_price: str
    result_return: str
    causes: list[str]
    detail: str
    review: str = ""  # 検証メモ（なければ空）


@dataclass(frozen=True)
class ParsedPreviousItem:
    rank: str
    name: str
    status: str
    entry_price: str
    result_return: str
    move: str
    market_return: str
    note: str = ""  # 例: ギャップで有利に約定（なければ空）


@dataclass(frozen=True)
class ParsedPrevious:
    heading: str  # 例: 2026-11-05予測 → 2026-11-06
    counts: list[str]  # 例: ["的中2", "不的中1", "不成立1", "未確定0"]
    items: list[ParsedPreviousItem]


@dataclass(frozen=True)
class ParsedReport:
    buy_stats_lines: list[str]
    sell_stats_lines: list[str]
    buy_candidates: list[ParsedCandidate]
    sell_candidates: list[ParsedCandidate]
    buy_unfilled: list[ParsedUnfilled] = field(default_factory=list)
    sell_unfilled: list[ParsedUnfilled] = field(default_factory=list)
    buy_missed: list[ParsedMiss] = field(default_factory=list)
    sell_missed: list[ParsedMiss] = field(default_factory=list)
    buy_previous: ParsedPrevious | None = None
    sell_previous: ParsedPrevious | None = None

    @property
    def has_sell_section(self) -> bool:
        return bool(self.sell_stats_lines) or bool(self.sell_candidates)


_SECTION_RE = re.compile(r"^## (.+)$", re.MULTILINE)
_CANDIDATE_HEADING_RE = re.compile(
    r"^### (\d+)位 (.+?)（(.+?)） - スコア(\d+)点$", re.MULTILINE
)


def _split_sections(text: str) -> list[tuple[str, str]]:
    headings = list(_SECTION_RE.finditer(text))
    sections = []
    for i, m in enumerate(headings):
        start = m.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        sections.append((m.group(1).strip(), text[start:end]))
    return sections


def _parse_stats_lines(body: str) -> list[str]:
    return [line.strip("- ").strip() for line in body.splitlines() if line.strip().startswith("-")]


def _parse_unfilled(body: str) -> list[ParsedUnfilled]:
    items = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        parts = line.removeprefix("- ").split(" | ", 4)
        if len(parts) == 5:
            items.append(ParsedUnfilled(*(p.strip() for p in parts)))
    return items


def _parse_missed(body: str) -> list[ParsedMiss]:
    items = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        parts = [p.strip() for p in line.removeprefix("- ").split(" | ", 7)]
        if len(parts) in (7, 8):
            items.append(ParsedMiss(*parts[:5], parts[5].split("・"), parts[6], parts[7] if len(parts) == 8 else ""))
    return items


def _parse_previous(body: str) -> ParsedPrevious | None:
    heading, counts, items = "", [], []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("- 対象:"):
            parts = [p.strip() for p in line.removeprefix("- 対象:").split(" | ", 1)]
            heading = parts[0]
            counts = parts[1].split("・") if len(parts) > 1 else []
        elif line.startswith("- "):
            parts = [p.strip() for p in line.removeprefix("- ").split(" | ", 7)]
            if len(parts) in (7, 8):
                items.append(ParsedPreviousItem(*parts))
    return ParsedPrevious(heading, counts, items) if items else None


def _parse_candidates(body: str) -> list[ParsedCandidate]:
    headings = list(_CANDIDATE_HEADING_RE.finditer(body))
    candidates = []
    for i, m in enumerate(headings):
        start = m.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(body)
        block = body[start:end]

        breakdown = ""
        entry_price = ""
        reasons: list[str] = []
        day_summary = ""
        one_point = ""
        outlook = ""
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("- 内訳:"):
                breakdown = line.removeprefix("- 内訳:").strip()
            elif line.startswith("- 参考指値:"):
                entry_price = line.removeprefix("- 参考指値:").strip()
            elif line.startswith("- 根拠:"):
                reasons = [r.strip() for r in line.removeprefix("- 根拠:").split("/")]
            elif line.startswith("- 当日の値動き:"):
                day_summary = line.removeprefix("- 当日の値動き:").strip()
            elif line.startswith("- ワンポイント:"):
                one_point = line.removeprefix("- ワンポイント:").strip()
            elif line.startswith("- 明日の見通し:"):
                outlook = line.removeprefix("- 明日の見通し:").strip()

        candidates.append(
            ParsedCandidate(
                rank=int(m.group(1)),
                name=m.group(2),
                code=m.group(3),
                score=int(m.group(4)),
                breakdown=breakdown,
                entry_price=entry_price,
                reasons=reasons,
                day_summary=day_summary,
                one_point=one_point,
                outlook=outlook,
            )
        )
    return candidates


def parse_report(text: str) -> ParsedReport:
    sections = _split_sections(text)

    buy_stats: list[str] = []
    sell_stats: list[str] = []
    buy_candidates: list[ParsedCandidate] = []
    sell_candidates: list[ParsedCandidate] = []
    buy_unfilled: list[ParsedUnfilled] = []
    sell_unfilled: list[ParsedUnfilled] = []
    buy_missed: list[ParsedMiss] = []
    sell_missed: list[ParsedMiss] = []
    buy_previous: ParsedPrevious | None = None
    sell_previous: ParsedPrevious | None = None

    for heading, body in sections:
        if heading.startswith("デモ検証成績（買い"):
            buy_stats = _parse_stats_lines(body)
        elif heading.startswith("デモ検証成績（売り"):
            sell_stats = _parse_stats_lines(body)
        elif heading.startswith("デモ検証成績"):
            # 旧フォーマット（買い売り分離前）は買い扱い
            buy_stats = _parse_stats_lines(body)
        elif heading.startswith("不成立の履歴（買い"):
            buy_unfilled = _parse_unfilled(body)
        elif heading.startswith("不成立の履歴（売り"):
            sell_unfilled = _parse_unfilled(body)
        elif heading.startswith("前営業日の結果（買い"):
            buy_previous = _parse_previous(body)
        elif heading.startswith("前営業日の結果（売り"):
            sell_previous = _parse_previous(body)
        elif heading.startswith("不的中の履歴（買い"):
            buy_missed = _parse_missed(body)
        elif heading.startswith("不的中の履歴（売り"):
            sell_missed = _parse_missed(body)
        elif heading.startswith("本日の買い候補"):
            buy_candidates = _parse_candidates(body)
        elif heading.startswith("本日の売り候補"):
            sell_candidates = _parse_candidates(body)
        elif heading.startswith("本日のTOP候補"):
            # 旧フォーマット（買い売り分離前）は買い候補扱い
            buy_candidates = _parse_candidates(body)

    return ParsedReport(
        buy_stats_lines=buy_stats,
        sell_stats_lines=sell_stats,
        buy_candidates=buy_candidates,
        sell_candidates=sell_candidates,
        buy_unfilled=buy_unfilled,
        sell_unfilled=sell_unfilled,
        buy_missed=buy_missed,
        sell_missed=sell_missed,
        buy_previous=buy_previous,
        sell_previous=sell_previous,
    )
