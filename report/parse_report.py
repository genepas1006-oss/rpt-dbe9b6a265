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


@dataclass(frozen=True)
class ParsedReport:
    buy_stats_lines: list[str]
    sell_stats_lines: list[str]
    buy_candidates: list[ParsedCandidate]
    sell_candidates: list[ParsedCandidate]

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
            )
        )
    return candidates


def parse_report(text: str) -> ParsedReport:
    sections = _split_sections(text)

    buy_stats: list[str] = []
    sell_stats: list[str] = []
    buy_candidates: list[ParsedCandidate] = []
    sell_candidates: list[ParsedCandidate] = []

    for heading, body in sections:
        if heading.startswith("デモ検証成績（買い"):
            buy_stats = _parse_stats_lines(body)
        elif heading.startswith("デモ検証成績（売り"):
            sell_stats = _parse_stats_lines(body)
        elif heading.startswith("デモ検証成績"):
            # 旧フォーマット（買い売り分離前）は買い扱い
            buy_stats = _parse_stats_lines(body)
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
    )
