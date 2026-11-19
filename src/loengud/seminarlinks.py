"""Seminari kirjelduse (seminar.md) algusesse YouTube'i- ja transkriptsioonilingid.

Plokk on märgendite vahel, seega uuendatakse seda korduvalt (nt kui lisandub 2. osa)
ja muu sisu jääb puutumata.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

START = "<!-- loengud:videod (automaatne, ära muuda käsitsi) -->"
END = "<!-- /loengud:videod -->"
_BLOCK_RE = re.compile(r"<!-- loengud:videod[^>]*-->.*?<!-- /loengud:videod -->\n?", re.S)
CANDIDATES = ("seminar.md", "README.md", "readme.md")


def seminar_md_path(repo: Path, seminar_dir: str, number: int | None, pattern: str | None = None) -> Path | None:
    """`pattern` (repo juure suhtes, nt "{n:02d}-seminar.md") või seminarikausta seminar.md/README.md."""
    if pattern and number is not None:
        p = repo / pattern.format(n=number)
        return p if p.exists() else None
    for name in CANDIDATES:
        p = repo / seminar_dir / name
        if p.exists():
            return p
    return None


def render_block(parts: list[tuple[int, str, Path | None]], md_path: Path, konspekt: Path | None = None) -> str:
    """parts: [(osa, video_id, transkriptsiooni fail või None)], osa järgi sorteeritud."""
    parts = sorted(parts)
    multi = len(parts) > 1

    def label(p: int) -> str:
        return f"{p}. osa" if multi else "YouTube"

    videos = " · ".join(f"[{label(p)}](https://youtu.be/{vid})" for p, vid, _ in parts)
    line = f"> 🎥 **Salvestus:** {videos}"
    def rel(t: Path) -> str:
        return Path(os.path.relpath(t, md_path.parent)).as_posix()

    if konspekt is not None:
        line = f"> 📘 **[Konspekt: mida seminaris räägiti]({rel(konspekt)})**  \n" + line
    tr = [(p, t) for p, _, t in parts if t is not None]
    if tr:
        links = " · ".join(f"[{p}. osa]({rel(t)})" if multi else f"[transkriptsioon]({rel(t)})" for p, t in tr)
        line += f"  \n> 📝 **Tekst:** {links}" if multi else f" · {links}"
    return f"{START}\n{line}\n{END}\n"


def upsert_block(text: str, block: str) -> str:
    """Asenda olemasolev plokk; muidu lisa esimese H1-pealkirja järele (või faili algusesse)."""
    if _BLOCK_RE.search(text):
        return _BLOCK_RE.sub(lambda _: block, text, count=1)
    lines = text.splitlines(keepends=True)
    i = 0
    if lines and lines[0].strip() == "---":  # YAML front matter
        for j in range(1, len(lines)):
            if lines[j].strip() == "---":
                i = j + 1
                break
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and lines[i].startswith("# "):
        head = "".join(lines[: i + 1])
        if not head.endswith("\n"):
            head += "\n"
        rest = "".join(lines[i + 1:]).lstrip("\n")
        return f"{head}\n{block}\n{rest}"
    head = "".join(lines[:i])
    rest = "".join(lines[i:])
    return f"{head}{block}\n{rest}"


def update_file(md_path: Path, parts: list[tuple[int, str, Path | None]], konspekt: Path | None = None) -> bool:
    """Tagastab True, kui faili muudeti."""
    old = md_path.read_text(encoding="utf-8")
    new = upsert_block(old, render_block(parts, md_path, konspekt))
    if new == old:
        return False
    md_path.write_text(new, encoding="utf-8")
    return True
