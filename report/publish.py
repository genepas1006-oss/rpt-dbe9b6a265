"""docs/ の変更をgitにコミット・pushする（GitHub Pages公開用）。

PCがオフラインの場合や差分が無い場合でも日次実行全体を失敗させないよう、
git操作のエラーは例外にせず、結果を PublishResult で返す。

2026-11-01修正: 以前はpushが拒否されても標準出力に1行出すだけで、公開されないまま
日次実行が「成功」扱いになっていた（リモートが先に進むと non-fast-forward で拒否される）。
現在は push 前に origin を取り込み（docs は生成物なので衝突時はローカルの最新版を優先）、
失敗時は理由を返して呼び出し側が通知・非ゼロ終了できるようにしている。
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PublishResult:
    status: str  # "pushed" | "nothing_to_commit" | "failed"
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status != "failed"


def publish_docs(repo_root: Path, commit_message: str) -> PublishResult:
    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            # Windowsの既定(cp932)だとgitのUTF-8出力を読めず落ちることがあるため固定する
            encoding="utf-8",
            errors="replace",
        )

    add_result = run("add", "docs")
    if add_result.returncode != 0:
        return PublishResult("failed", f"git add失敗: {add_result.stderr.strip()}")

    commit_result = run("commit", "-m", commit_message)
    nothing_new = commit_result.returncode != 0
    if nothing_new and "nothing to commit" not in (commit_result.stdout + commit_result.stderr):
        return PublishResult("failed", f"git commit失敗: {commit_result.stderr.strip()}")

    branch = run("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    # リモートが先に進んでいてもpushが拒否されないよう、先に取り込む。
    # docs/index.html は生成物のため、衝突時はローカル（最新の全レポートから作った版）を採用する。
    pull_result = run("pull", "--rebase", "-X", "theirs", "origin", branch)
    if pull_result.returncode != 0:
        run("rebase", "--abort")
        return PublishResult(
            "failed", f"git pull --rebase失敗（オフライン等の可能性）: {pull_result.stderr.strip()}"
        )

    # 以前のpush失敗で溜まった未pushコミットも、ここで一緒に送られる。
    push_result = run("push", "origin", branch)
    if push_result.returncode != 0:
        return PublishResult("failed", f"git push失敗: {push_result.stderr.strip()}")

    if nothing_new:
        return PublishResult("nothing_to_commit", "docs/ に差分なし（pushは最新）")
    return PublishResult("pushed", "docs/ を公開リポジトリへpushしました。")
