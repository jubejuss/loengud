"""Püsiv olek: iga salvestuse edenemine töövoos (idempotentne taaskäivitus)."""
from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

# Etapid järjekorras
STAGES = [
    "discovered",
    "matched",
    "transcribed",
    "committed",          # transkriptsioon + subtiitrid repos
    "awaiting_upload",    # studio-režiim: ootab käsitsi üleslaadimist
    "uploaded",           # video YouTube'is (id teada)
    "captioned",
    "done",
]
TERMINAL_SKIP = {"ignored"}
PROBLEM = {"unmatched", "ambiguous", "error"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class State:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, Any] = {"recordings": {}}
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
            self.data.setdefault("recordings", {})

    @property
    def recordings(self) -> dict[str, dict[str, Any]]:
        return self.data["recordings"]

    def get(self, key: str) -> dict[str, Any] | None:
        return self.recordings.get(key)

    def upsert(self, key: str, **fields: Any) -> dict[str, Any]:
        rec = self.recordings.setdefault(key, {"created": now_iso()})
        rec.update(fields)
        rec["updated"] = now_iso()
        self.save()
        return rec

    def parts_for(self, repo: str, seminar_dir: str, exclude_key: str) -> list[int]:
        return [r.get("part", 1) for k, r in self.recordings.items()
                if k != exclude_key and r.get("repo") == repo and r.get("seminar_dir") == seminar_dir
                and r.get("status") not in PROBLEM | TERMINAL_SKIP]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)


@contextmanager
def run_lock(lock_path: Path) -> Iterator[bool]:
    """Väldib kahte paralleelset käivitust (launchd + käsitsi)."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "w")
    try:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        fh.write(str(os.getpid()))
        fh.flush()
        yield True
    finally:
        fh.close()
