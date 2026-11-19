"""Loengurepo ajakava (.loengud.yaml) ja salvestuse sobitamine seminariga kuupäeva järgi."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

import yaml

REPO_FILE = ".loengud.yaml"

DEFAULT_TITLE_TEMPLATE = "{course} – {seminar_title} ({date_et})"
DEFAULT_DESCRIPTION_TEMPLATE = (
    "{course} · {seminar_title}\n"
    "Salvestatud {date_et}.\n\n"
    "Subtiitrid on loodud automaatselt TalTechi eesti keele kõnetuvastusega "
    "(tekstiks.ee mootor) ja võivad sisaldada vigu.\n"
    "{materials_line}"
)


@dataclass
class Seminar:
    date: date
    dir: str
    title: str
    time: str | None = None  # "10:00-13:15"


@dataclass
class Course:
    repo: Path
    course: str
    playlist_id: str | None
    seminars: list[Seminar]
    title_template: str = DEFAULT_TITLE_TEMPLATE
    description_template: str = DEFAULT_DESCRIPTION_TEMPLATE
    recording_subdir: str = "salvestus"
    default_time: str | None = None
    match_title: str | None = None
    branch: str | None = None
    repo_url: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class Match:
    course: Course
    seminar: Seminar


class MatchError(Exception):
    def __init__(self, kind: str, message: str, candidates: list[Match] | None = None):
        super().__init__(message)
        self.kind = kind  # "unmatched" | "ambiguous"
        self.candidates = candidates or []


def _git_remote_https(repo: Path) -> str | None:
    try:
        url = subprocess.run(
            ["git", "-C", str(repo), "remote", "get-url", "origin"],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout.strip()
    except Exception:
        return None
    if url.startswith("git@github.com:"):
        url = "https://github.com/" + url.split(":", 1)[1]
    return url.removesuffix(".git")


def load_course(repo: Path) -> Course:
    f = repo / REPO_FILE
    if not f.exists():
        raise FileNotFoundError(f"{f} puudub – lisa repo juurkausta ajakava (vt README).")
    raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    yt = raw.get("youtube") or {}
    seminars = []
    for s in raw.get("seminars", []):
        d = s["date"]
        if isinstance(d, str):
            d = date.fromisoformat(d)
        seminars.append(Seminar(date=d, dir=str(s["dir"]).strip("/"), title=s.get("title") or s["dir"], time=s.get("time")))
    return Course(
        repo=repo,
        course=raw.get("course") or repo.name,
        playlist_id=yt.get("playlist_id"),
        seminars=seminars,
        title_template=yt.get("title_template", DEFAULT_TITLE_TEMPLATE),
        description_template=yt.get("description_template", DEFAULT_DESCRIPTION_TEMPLATE),
        recording_subdir=raw.get("recording_subdir", "salvestus"),
        default_time=raw.get("default_time"),
        match_title=raw.get("match_title"),
        branch=raw.get("branch"),
        repo_url=raw.get("repo_url") or _git_remote_https(repo),
        extra={k: v for k, v in raw.items() if k not in {"youtube", "seminars"}},
    )


def load_courses(repos: list[Path]) -> tuple[list[Course], list[str]]:
    courses, errors = [], []
    for r in repos:
        try:
            courses.append(load_course(r))
        except Exception as e:  # noqa: BLE001 – kuvame kasutajale
            errors.append(f"{r}: {e}")
    return courses, errors


def _parse_window(spec: str, day: date, tzinfo) -> tuple[datetime, datetime]:
    a, b = [x.strip() for x in spec.split("-", 1)]
    t1 = time.fromisoformat(a if len(a) > 2 else a + ":00")
    t2 = time.fromisoformat(b if len(b) > 2 else b + ":00")
    return datetime.combine(day, t1, tzinfo), datetime.combine(day, t2, tzinfo)


def match_recording(courses: list[Course], start: datetime, meeting_title: str,
                    tolerance: timedelta = timedelta(minutes=45)) -> Match:
    day = start.date()
    cands = [Match(c, s) for c in courses for s in c.seminars if s.date == day]
    if not cands:
        raise MatchError("unmatched", f"Ühtegi seminari kuupäevaga {day} ei leitud.")

    t = meeting_title.lower()
    explicit = [m for m in cands if m.course.match_title and m.course.match_title.lower() in t]
    if explicit:
        cands = explicit  # pealkiri ütleb otse, mis kursus
    else:
        neutral = [m for m in cands if not m.course.match_title]
        if neutral:
            cands = neutral  # välista kursused, mille match_title ei sobi
    if len(cands) == 1:
        return cands[0]

    timed = []
    for m in cands:
        spec = m.seminar.time or m.course.default_time
        if not spec:
            continue
        a, b = _parse_window(spec, day, start.tzinfo)
        if a - tolerance <= start <= b:
            timed.append(m)
    if len(timed) == 1:
        return timed[0]
    raise MatchError(
        "ambiguous",
        f"{day}: mitu sobivat seminari – lisa .loengud.yaml-i `time` või `match_title`, "
        f"või määra käsitsi `loengud assign`.",
        timed or cands,
    )


def find_seminar(course: Course, seminar_dir: str) -> Seminar:
    seminar_dir = seminar_dir.strip("/")
    for s in course.seminars:
        if s.dir == seminar_dir:
            return s
    raise KeyError(f"Seminari kausta {seminar_dir} pole {course.repo / REPO_FILE} failis.")


def fmt_date_et(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def template_vars(course: Course, seminar: Seminar, part: int, video_url: str | None = None) -> dict:
    title = seminar.title + (f" (osa {part})" if part > 1 else "")
    materials = f"{course.repo_url}/tree/{course.branch or 'main'}/{seminar.dir}" if course.repo_url else ""
    return {
        "course": course.course,
        "seminar_title": title,
        "seminar_dir": seminar.dir,
        "date": seminar.date.isoformat(),
        "date_et": fmt_date_et(seminar.date),
        "part": part,
        "repo_url": course.repo_url or "",
        "materials_url": materials,
        "materials_line": f"Materjalid ja transkriptsioon: {materials}" if materials else "",
        "video_url": video_url or "",
    }
