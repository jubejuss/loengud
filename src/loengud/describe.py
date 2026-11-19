"""Videokirjeldus + YouTube'i peatükid transkriptsioonist keelemudeliga (vaikimisi `claude -p`)."""
from __future__ import annotations

import json
import re
import subprocess

from .config import DescribeConfig
from . import subtitles

PROMPT = """Sa oled ülikooli õppejõu assistent. Allpool on eestikeelse seminarisalvestuse automaatne transkriptsioon
(võib sisaldada tuvastusvigu ja grupitöö ajal taustamüra/kordusi). Iga lõigu ees on ajatempel [m:ss] või [h:mm:ss].

Kursus: {course}
Seminar: {seminar}
Kuupäev: {date}{part}

Koosta YouTube'i video kirjeldus EESTI KEELES ja tagasta AINULT JSON (ilma markdowni ja selgitusteta):
{{
  "summary": "2–4 lauset: mida seminaris käsitleti ja miks see oluline on; loomulik, mitte kantseliitlik keel",
  "chapters": [{{"t": "0:00", "title": "lühike peatüki nimi"}}, ...]
}}

Reeglid:
- 6–16 peatükki, esimene ALATI "0:00", ajad kasvavas järjekorras ja võetud transkriptsiooni ajatemplitest, vahe vähemalt 1 minut.
- Peatüki nimi kuni 50 märki, sisuline (mis teema), mitte "Jätk" vms.
- ÄRA kasuta üliõpilaste ega teiste isikute nimesid; ära tsiteeri üliõpilasi.
- Grupitöö/arutelu lõigu nimeta lihtsalt (nt "Tunnitöö tiimides", "Tiimide esitlused").
- Ära leiuta teemasid, mida transkriptsioonis pole.

TRANSKRIPTSIOON:
{transcript}
"""

TS_RE = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})$")


def to_seconds(ts: str) -> int | None:
    m = TS_RE.match(ts.strip())
    if not m:
        return None
    h, mm, ss = int(m.group(1) or 0), int(m.group(2)), int(m.group(3))
    return h * 3600 + mm * 60 + ss


def compact_transcript(words: list, max_chars: int = 120_000) -> str:
    lines = [f"[{subtitles.hms(start)}] {text}" for start, _spk, text in subtitles.paragraphs(words, max_seconds=60)]
    out = "\n".join(lines)
    return out if len(out) <= max_chars else out[:max_chars] + "\n[…transkriptsioon lühendatud…]"


def parse_response(text: str, duration: float) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("vastuses pole JSON-it")
    data = json.loads(m.group(0))
    summary = str(data.get("summary", "")).strip()
    chapters, last = [], -1
    for ch in data.get("chapters", []):
        sec = to_seconds(str(ch.get("t", "")))
        title = str(ch.get("title", "")).strip()[:60]
        if sec is None or not title or sec >= duration:
            continue
        if chapters and sec - last < 10:      # YouTube: peatükk vähemalt 10 s
            continue
        chapters.append((sec, title))
        last = sec
    if chapters and chapters[0][0] != 0:
        chapters.insert(0, (0, "Algus"))
    if len(chapters) < 3:                      # YouTube näitab peatükke alates kolmest
        chapters = []
    if not summary:
        raise ValueError("kokkuvõte puudub")
    return {"summary": summary, "chapters": chapters}


def generate(cfg: DescribeConfig, words: list, course: str, seminar: str, date: str, part: int, log=print) -> dict:
    prompt = PROMPT.format(course=course, seminar=seminar, date=date,
                           part=f" (osa {part})" if part > 1 else "", transcript=compact_transcript(words))
    log("  kirjeldus: " + " ".join(cfg.command))
    try:
        r = subprocess.run(cfg.command, input=prompt, capture_output=True, text=True, timeout=cfg.timeout_s)
    except FileNotFoundError as e:
        raise RuntimeError(f"{cfg.command[0]} puudub (Claude Code CLI)") from e
    if r.returncode != 0:
        raise RuntimeError(f"kirjelduse genereerimine ebaõnnestus: {(r.stderr or r.stdout).strip()[-400:]}")
    return parse_response(r.stdout, words[-1].end if words else 0)


def render(desc: dict, header: str, footer_lines: list[str]) -> str:
    parts = [header, "", desc["summary"]]
    if desc["chapters"]:
        parts += [""] + [f"{subtitles.hms(sec)} {title}" for sec, title in desc["chapters"]]
    foot = [l for l in footer_lines if l]
    if foot:
        parts += [""] + foot
    return "\n".join(parts).strip()[:4900]
