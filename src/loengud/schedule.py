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
    number: int | None = None


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
    extra_playlist_ids: list[str] = field(default_factory=list)
    subject_codes: list[str] = field(default_factory=list)   # nt ["HKI5113.HK"] (tunniplaanist)
    match_titles: list[str] = field(default_factory=list)    # Teamsi pealkirja alamstringid, nt ["SJTA", "Sissejuhatus tarkvara"]
    seminar_dir_pattern: str = "seminarid/seminar_{n:02d}"

    def all_playlist_ids(self, common: list[str] | None = None) -> list[str]:
        """Kursuse esitusloend + lisaloendid + ühised (nt Haapsalu kolledž), duplikaatideta."""
        ids = ([self.playlist_id] if self.playlist_id else []) + self.extra_playlist_ids + list(common or [])
        return list(dict.fromkeys(i for i in ids if i))


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
        seminars.append(Seminar(date=d, dir=str(s["dir"]).strip("/"), title=s.get("title") or s["dir"],
                                time=s.get("time"), number=s.get("number")))
    codes = raw.get("subject_codes") or ([raw["subject_code"]] if raw.get("subject_code") else [])
    meta = repo / "metadata" / "data.json"
    if not codes and meta.exists():
        try:
            import json
            c = json.loads(meta.read_text(encoding="utf-8")).get("code")
            codes = [c] if c else []
        except Exception:
            pass
    titles = raw.get("match_titles") or ([raw["match_title"]] if raw.get("match_title") else [])
    return Course(
        repo=repo,
        course=raw.get("course") or repo.name,
        playlist_id=yt.get("playlist_id"),
        extra_playlist_ids=[str(p) for p in (yt.get("extra_playlist_ids") or [])],
        seminars=seminars,
        title_template=yt.get("title_template", DEFAULT_TITLE_TEMPLATE),
        description_template=yt.get("description_template", DEFAULT_DESCRIPTION_TEMPLATE),
        recording_subdir=raw.get("recording_subdir", "salvestus"),
        default_time=raw.get("default_time"),
        match_title=raw.get("match_title"),
        subject_codes=[str(c) for c in codes],
        match_titles=[str(t) for t in titles],
        seminar_dir_pattern=raw.get("seminar_dir_pattern", "seminarid/seminar_{n:02d}"),
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


# --- tunniplaani + pealkirja järgi sobitamine -------------------------------------------------

import re as _re

_TITLE_NUM_RE = _re.compile(r"\s(\d{1,2})\s*$")  # tühik enne numbrit: "SJTA 3", mitte "RIF25"


def title_number(meeting_title: str) -> int | None:
    """'SJTA 3' -> 3, 'Sissejuhatus Tarkvaraarendusse 4' -> 4."""
    m = _TITLE_NUM_RE.search(meeting_title.strip())
    return int(m.group(1)) if m else None


def _norm(t: str) -> str:
    return _re.sub(r"\s+", " ", t.casefold()).strip()


def course_by_title(courses: list[Course], meeting_title: str) -> list[Course]:
    t = _norm(meeting_title)
    return [c for c in courses if any(_norm(x) in t for x in c.match_titles)]


def _heading(path: Path) -> str | None:
    for name in ("seminar.md", "README.md", "readme.md"):
        f = path / name
        if f.exists():
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines()[:30]:
                if line.startswith("# "):
                    return line[2:].strip()
    return None


def seminar_for_number(course: Course, n: int, day: date) -> Seminar:
    for s in course.seminars:
        if s.number == n:
            return s
    rel = course.seminar_dir_pattern.format(n=n)
    if not (course.repo / rel).exists():
        # proovi leida olemasolev kaust, mille nimes on number (seminar_4, 04-css, seminar-04…)
        parent = (course.repo / rel).parent
        if parent.exists():
            for d in sorted(parent.iterdir()):
                if d.is_dir() and _re.search(rf"(^|\D)0*{n}(\D|$)", d.name):
                    rel = str(d.relative_to(course.repo))
                    break
    head = _heading(course.repo / rel)
    title = f"Seminar {n}" + (f": {head}" if head and not head.lower().startswith("seminar") else "")
    if head and head.lower().startswith("seminar"):
        title = head
    return Seminar(date=day, dir=rel, title=title, number=n)


def match_smart(courses: list[Course], start: datetime, meeting_title: str, sessions=None,
                tz: str = "Europe/Tallinn") -> Match:
    """1) tunniplaan (aeg → ainekood → kursus, järjekorranumber) 2) pealkiri (kursus + number) 3) kuupäevaajakava."""
    from . import tunniplaan as tp

    tnum = title_number(meeting_title)
    by_title = course_by_title(courses, meeting_title)

    if sessions:
        hits = [s for s in tp.session_at(sessions, start, tz)
                if any(s.code in c.subject_codes for c in courses)]
        pairs = [(c, s) for s in hits for c in courses if s.code in c.subject_codes]
        if len(pairs) > 1 and by_title:
            pairs = [(c, s) for c, s in pairs if c in by_title] or pairs
        if len(pairs) == 1:
            c, s = pairs[0]
            n = tnum or tp.ordinal(sessions, s)
            return Match(c, seminar_for_number(c, n, date.fromisoformat(s.date)))
        if len(pairs) > 1:
            raise MatchError("ambiguous", f"Tunniplaanis on samal ajal mitu ainet: "
                             f"{', '.join(s.subject for _, s in pairs)} – lisa kursustele `match_titles`.")

    if len(by_title) == 1 and tnum:
        return Match(by_title[0], seminar_for_number(by_title[0], tnum, start.date()))

    return match_recording(courses, start, meeting_title)


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
