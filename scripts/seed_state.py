"""PC上の data/ と reports/ を、GitHub Actions用の `state` ブランチへ初回登録する。

使い方（リポジトリのルートで1回だけ実行）:
    python scripts/seed_state.py

作業ツリーやブランチには触れず、一時ディレクトリ経由で push する。
state ブランチが既にある場合は上書きするので、初回以外は実行しないこと。
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(*args: str, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def main() -> int:
    sources = [p for p in (ROOT / "data", ROOT / "reports") if p.exists()]
    if not sources:
        print("data/ も reports/ も見つかりません。", file=sys.stderr)
        return 1

    remote = subprocess.run(
        ["git", "remote", "get-url", "origin"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True
    ).stdout.strip()

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        run("git", "init", "-q", "-b", "state", cwd=work)
        for src in sources:
            shutil.copytree(src, work / src.name)
        run("git", "add", "-A", cwd=work)
        run("git", "-c", "user.name=seed", "-c", "user.email=seed@example.invalid",
            "commit", "-q", "-m", "state: 初回登録", cwd=work)
        run("git", "push", "--force", remote, "state:state", cwd=work)
    print("state ブランチへ登録しました。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
