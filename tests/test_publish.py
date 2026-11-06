"""report.publish のテスト（一時ディレクトリ上の実gitリポジトリで検証）。"""

import subprocess
from pathlib import Path

from report.publish import publish_docs


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=cwd, capture_output=True, text=True, check=True,
    ).stdout.strip()


def _setup(tmp_path: Path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    pc = tmp_path / "pc"
    other = tmp_path / "other"
    for d in (pc, other):
        subprocess.run(["git", "clone", "-q", str(remote), str(d)], check=True, capture_output=True)
        git(d, "checkout", "-q", "-B", "main")
    (pc / "docs").mkdir()
    (pc / "docs" / "index.html").write_text("v0", encoding="utf-8")
    git(pc, "add", "-A")
    git(pc, "commit", "-q", "-m", "init")
    git(pc, "push", "-q", "origin", "main")
    git(other, "pull", "-q", "origin", "main")
    return remote, pc, other


def _env_user(monkeypatch):
    for k, v in {"GIT_AUTHOR_NAME": "t", "GIT_COMMITTER_NAME": "t",
                 "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_EMAIL": "t@example.invalid"}.items():
        monkeypatch.setenv(k, v)


def test_pushes_when_remote_is_in_sync(tmp_path, monkeypatch):
    _env_user(monkeypatch)
    remote, pc, _ = _setup(tmp_path)
    (pc / "docs" / "index.html").write_text("v1", encoding="utf-8")

    result = publish_docs(pc, "docs: v1")

    assert result.status == "pushed"
    assert git(pc, "rev-parse", "HEAD") == git(remote, "rev-parse", "main")


def test_pushes_even_when_remote_moved_ahead(tmp_path, monkeypatch):
    """再発防止の本体: 別の場所からmainが進んでいても、公開が拒否されない。"""
    _env_user(monkeypatch)
    remote, pc, other = _setup(tmp_path)
    (other / "other.txt").write_text("x", encoding="utf-8")
    git(other, "add", "-A")
    git(other, "commit", "-q", "-m", "unrelated change")
    git(other, "push", "-q", "origin", "main")

    (pc / "docs" / "index.html").write_text("v1", encoding="utf-8")
    result = publish_docs(pc, "docs: v1")

    assert result.status == "pushed"
    assert git(pc, "rev-parse", "HEAD") == git(remote, "rev-parse", "main")
    assert git(remote, "show", "main:docs/index.html") == "v1"
    assert git(remote, "show", "main:other.txt") == "x"


def test_docs_conflict_prefers_local_generated_version(tmp_path, monkeypatch):
    _env_user(monkeypatch)
    remote, pc, other = _setup(tmp_path)
    (other / "docs" / "index.html").write_text("remote-edit", encoding="utf-8")
    git(other, "add", "-A")
    git(other, "commit", "-q", "-m", "remote edits docs")
    git(other, "push", "-q", "origin", "main")

    (pc / "docs" / "index.html").write_text("local-latest", encoding="utf-8")
    result = publish_docs(pc, "docs: latest")

    assert result.status == "pushed"
    assert git(remote, "show", "main:docs/index.html") == "local-latest"


def test_unpushed_commits_from_earlier_failures_are_sent_too(tmp_path, monkeypatch):
    _env_user(monkeypatch)
    remote, pc, _ = _setup(tmp_path)
    (pc / "docs" / "index.html").write_text("day1", encoding="utf-8")
    git(pc, "add", "-A")
    git(pc, "commit", "-q", "-m", "day1 (push failed earlier)")

    (pc / "docs" / "index.html").write_text("day2", encoding="utf-8")
    result = publish_docs(pc, "docs: day2")

    assert result.status == "pushed"
    assert git(remote, "show", "main:docs/index.html") == "day2"
    assert git(remote, "rev-list", "--count", "main") == "3"


def test_no_diff_still_syncs_and_reports_status(tmp_path, monkeypatch):
    _env_user(monkeypatch)
    _, pc, _ = _setup(tmp_path)
    assert publish_docs(pc, "docs: none").status == "nothing_to_commit"


def test_unreachable_remote_returns_failed_instead_of_raising(tmp_path, monkeypatch):
    _env_user(monkeypatch)
    _, pc, _ = _setup(tmp_path)
    git(pc, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    (pc / "docs" / "index.html").write_text("v1", encoding="utf-8")

    result = publish_docs(pc, "docs: v1")

    assert result.status == "failed"
    assert not result.ok


def test_git_output_is_decoded_as_utf8_regardless_of_locale(tmp_path, monkeypatch):
    """Windows(cp932)でgitのUTF-8出力を読めず落ちた不具合の再発防止。"""
    import report.publish as publish_module

    seen = []
    real_run = subprocess.run

    def spy(*args, **kwargs):
        seen.append((kwargs.get("encoding"), kwargs.get("errors")))
        return real_run(*args, **kwargs)

    monkeypatch.setattr(publish_module.subprocess, "run", spy)
    _env_user(monkeypatch)
    _, pc, _ = _setup(tmp_path)
    (pc / "docs" / "index.html").write_text("v1", encoding="utf-8")

    publish_docs(pc, "docs: 不成立履歴UIの更新")

    assert seen and all(s == ("utf-8", "replace") for s in seen)
