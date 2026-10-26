"""docs/ の変更をgitにコミット・pushする（GitHub Pages公開用）。

PCがオフラインの場合や差分が無い場合でも日次実行全体を失敗させないよう、
git操作のエラーはログ出力のみに留める。
"""

import subprocess
from pathlib import Path


def publish_docs(repo_root: Path, commit_message: str) -> None:
    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )

    add_result = run("add", "docs")
    if add_result.returncode != 0:
        print(f"[publish] git add失敗: {add_result.stderr.strip()}")
        return

    commit_result = run("commit", "-m", commit_message)
    if commit_result.returncode != 0:
        # 差分なしの場合もここに来る（エラーではない）
        print(f"[publish] コミット対象なし、またはコミット失敗: {commit_result.stdout.strip()}")
        return

    push_result = run("push")
    if push_result.returncode != 0:
        print(f"[publish] git push失敗（オフライン等の可能性）: {push_result.stderr.strip()}")
        return

    print("[publish] docs/ を公開リポジトリへpushしました。")
