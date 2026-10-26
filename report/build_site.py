"""reports/*.md から外出先閲覧用の静的HTMLページ（docs/index.html）を生成する。

GitHub Pagesで公開することを想定し、外部サービス・ログイン・サーバー実行を
一切必要としない単一の静的HTMLファイルとして出力する。
"""

from pathlib import Path

from report.md_to_html import md_to_html

PAGE_TITLE = "日本株デイクローズ・リサーチ"

_STYLE = """
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       max-width: 720px; margin: 0 auto; padding: 16px; line-height: 1.6;
       color: #1a1a1a; background: #fafafa; }
h1 { font-size: 1.4rem; }
h2 { font-size: 1.15rem; margin-top: 1.6em; border-bottom: 2px solid #ddd; padding-bottom: 4px; }
h3 { font-size: 1.0rem; margin-top: 1.2em; }
.updated { color: #666; font-size: 0.85rem; }
.latest { background: #fff; border: 1px solid #ddd; border-radius: 8px;
          padding: 12px 16px; margin: 16px 0; }
details { margin: 8px 0; border: 1px solid #e0e0e0; border-radius: 6px; padding: 8px 12px; }
summary { cursor: pointer; font-weight: bold; }
ul { padding-left: 1.3em; }
"""


def build_index(reports_dir: Path, docs_dir: Path, generated_at: str) -> Path:
    docs_dir.mkdir(parents=True, exist_ok=True)

    report_files = sorted(reports_dir.glob("*.md"), reverse=True)

    latest_html = ""
    history_html_parts: list[str] = []

    for i, path in enumerate(report_files):
        body = md_to_html(path.read_text(encoding="utf-8"))
        if i == 0:
            latest_html = f'<div class="latest">{body}</div>'
        else:
            history_html_parts.append(
                f"<details><summary>{path.stem}</summary>{body}</details>"
            )

    if not report_files:
        latest_html = "<p>まだレポートが生成されていません。</p>"

    page = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{PAGE_TITLE}</title>
<style>{_STYLE}</style>
</head>
<body>
<h1>{PAGE_TITLE}</h1>
<p class="updated">最終更新: {generated_at}</p>
{latest_html}
<h2>過去のレポート</h2>
{"".join(history_html_parts) if history_html_parts else "<p>履歴なし</p>"}
</body>
</html>
"""

    index_path = docs_dir / "index.html"
    index_path.write_text(page, encoding="utf-8")
    return index_path
