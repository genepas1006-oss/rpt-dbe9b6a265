"""このツールが生成するMarkdown（見出し・太字・リストのみ）をHTMLスニペットに変換する。

generate_report.py が出力する固定フォーマットのみを対象とした簡易コンバータであり、
汎用Markdown仕様への対応は意図していない。
"""

import html
import re


def md_to_html(text: str) -> str:
    html_lines: list[str] = []
    in_list = False

    def close_list():
        nonlocal in_list
        if in_list:
            html_lines.append("</ul>")
            in_list = False

    for raw_line in text.splitlines():
        line = raw_line.rstrip()

        if not line:
            close_list()
            continue

        heading_match = re.match(r"^(#{1,3})\s+(.*)$", line)
        if heading_match:
            close_list()
            level = len(heading_match.group(1)) + 1  # h2〜h4（ページ全体のh1と被らないように）
            html_lines.append(f"<h{level}>{_inline(heading_match.group(2))}</h{level}>")
            continue

        list_match = re.match(r"^-\s+(.*)$", line)
        if list_match:
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append(f"<li>{_inline(list_match.group(1))}</li>")
            continue

        close_list()
        html_lines.append(f"<p>{_inline(line)}</p>")

    close_list()
    return "\n".join(html_lines)


def _inline(text: str) -> str:
    escaped = html.escape(text)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
