"""このツールが生成するMarkdown（見出し・太字・リストのみ）をHTMLスニペットに変換する。

generate_report.py が出力する固定フォーマットのみを対象とした簡易コンバータであり、
汎用Markdown仕様への対応は意図していない。

承認済み配色ルール（2026-10-26）: プラス符号付きの数値は上昇方向として赤、
マイナス符号付きの数値は下落方向として緑で表示する（日本の相場表示の慣例に合わせる）。
"""

import html
import re

_DELTA_RE = re.compile(r"([+\-]\d+(?:\.\d+)?%)")


def color_deltas(text: str) -> str:
    """「+3.89%」「-3.00%」のような符号付き数値を赤/緑のspanで装飾する。

    text は既にHTMLエスケープ済みであることを前提とする。
    """

    def repl(m: re.Match) -> str:
        token = m.group(1)
        color_var = "var(--up)" if token.startswith("+") else "var(--down)"
        return f'<span style="color:{color_var}">{token}</span>'

    return _DELTA_RE.sub(repl, text)


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
    bolded = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    return color_deltas(bolded)
