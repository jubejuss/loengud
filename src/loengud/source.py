"""Teamsi salvestuste leidmine OneDrive'i sünkroonitud kaustast."""
from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import Config

# "RIF25 Veebiarendus-20261119_081530-Meeting Recording.mp4"
# "Seminar-20261119_081530-Koosoleku salvestis.mp4"
TEAMS_NAME_RE = re.compile(r"^(?P<title>.*?)-(?P<ts>\d{8}_\d{6})-(?P<rest>[^-]+)$")


@dataclass
class Recording:
    path: Path
    size: int
    mtime: float
    meeting_title: str
    start: datetime  # ajavöönd: config.timezone
    start_source: str  # "filename" | "ffprobe" | "mtime"

    @property
    def key(self) -> str:
        return str(self.path)


def parse_teams_filename(name: str, filename_tz: str, local_tz: str) -> tuple[str, datetime] | None:
    stem = Path(name).stem
    m = TEAMS_NAME_RE.match(stem)
    if not m:
        return None
    naive = datetime.strptime(m.group("ts"), "%Y%m%d_%H%M%S")
    aware = naive.replace(tzinfo=ZoneInfo(filename_tz))
    return m.group("title").strip(), aware.astimezone(ZoneInfo(local_tz))


def ffprobe_creation_time(path: Path) -> datetime | None:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
            capture_output=True, text=True, timeout=120, check=True,
        ).stdout
        tags = json.loads(out).get("format", {}).get("tags", {})
        ct = tags.get("creation_time")
        if ct:
            return datetime.fromisoformat(ct.replace("Z", "+00:00"))
    except Exception:
        return None
    return None


def discover(cfg: Config, now: float | None = None) -> list[Recording]:
    now = now or time.time()
    tz = ZoneInfo(cfg.timezone)
    found: list[Recording] = []
    for root in cfg.source.recordings_dirs:
        if not root.exists():
            continue
        for p in sorted(root.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in cfg.source.extensions:
                continue
            if p.name.startswith("."):
                continue
            st = p.stat()
            if now - st.st_mtime < cfg.source.min_age_minutes * 60:
                continue  # võib veel sünkroniseerida
            parsed = parse_teams_filename(p.name, cfg.source.filename_tz, cfg.timezone)
            if parsed:
                title, start, src = parsed[0], parsed[1], "filename"
            else:
                ct = ffprobe_creation_time(p)
                title = p.stem
                if ct:
                    start, src = ct.astimezone(tz), "ffprobe"
                else:
                    start, src = datetime.fromtimestamp(st.st_mtime, tz), "mtime"
            if cfg.source.ignore_before and start.date() < cfg.source.ignore_before:
                continue
            found.append(Recording(p, st.st_size, st.st_mtime, title, start, src))
    return found


def to_utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()
