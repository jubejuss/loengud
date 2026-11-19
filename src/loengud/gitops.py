"""Loengurepo git-toimingud."""
from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=300)
    if check and r.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {r.stderr.strip() or r.stdout.strip()}")
    return r


def has_remote(repo: Path) -> bool:
    return bool(_git(repo, "remote", check=False).stdout.strip())


def pull(repo: Path) -> None:
    if has_remote(repo):
        _git(repo, "pull", "--rebase", "--autostash")


def commit_paths(repo: Path, paths: list[Path], message: str, push: bool) -> str | None:
    rel = [str(p.relative_to(repo)) for p in paths]
    _git(repo, "add", "--", *rel)
    if not _git(repo, "diff", "--cached", "--quiet", check=False).returncode:
        return None  # muudatusi pole
    _git(repo, "commit", "-m", message, "--", *rel)
    sha = _git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
    if push and has_remote(repo):
        _git(repo, "push")
    return sha
