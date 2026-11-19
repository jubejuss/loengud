"""Seminari konspekt: loetav õppematerjal kõigi osade transkriptsioonidest (vaikimisi `claude -p`).

seminar.md = plaan; transkriptsioon*.md = täpne ülevaade; konspekt.md = mis päriselt toimus.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import describe as describe_mod
from . import seminarlinks, subtitles
from .config import DescribeConfig

FILENAME = "konspekt.md"
MARK_RE = re.compile(r"<!-- loengud:konspekt osad=([\d,]+)")
REF_RE = re.compile(r"\[\[(\d+)@((?:\d+:)?\d{1,2}:\d{2})\]\]")

PROMPT = """Sa oled kogenud ülikooli õppejõud ja hea õppematerjalide kirjutaja. Allpool on ühe seminari
ametlik plaan ja seminari automaatsed transkriptsioonid (eestikeelne kõnetuvastus, võib sisaldada
tuvastusvigu; grupitöö ajal taustamüra ja kordusi). Iga lõigu ees on ajatempel [m:ss] või [h:mm:ss].

Kursus: {course}
Seminar: {seminar}
Kuupäev: {date}
Salvestuse osad: {parts}

Kirjuta selle seminari KONSPEKT eesti keeles. See on õppematerjal üliõpilasele, kes tahab teada,
millest seminaris päriselt räägiti – ka sellele, kes kohal ei olnud. Plaan näitab, mis oli kavas;
konspekt kajastab, mis tegelikult toimus.

Sisu:
- Kata KÕIK seminaris sisuliselt käsitletud teemad, transkriptsiooni järjekorras, kõigist osadest.
  Selgita mõtted lahti nii, et tekst on iseseisvalt arusaadav: mõisted, põhjendused, näited,
  analoogiad ja praktilised soovitused, mida õppejõud tõi. Ära piirdu teemade loeteluga.
- Too eraldi esile see, mis tuli plaanile lisaks (kõrvalepõiked, lood päriselust, küsimuste peale
  antud selgitused) – need on sageli kõige huvitavamad.
- Grupitöö, iseseisva töö ja esitluste kohta kirjuta lühidalt, mis oli ülesanne ja mis üldised
  tähelepanekud õppejõud tegi; ära kirjelda taustamüra.
- Lõpus kodutöö või järgmised sammud, kui neist räägiti.
- Konspekti kasutatakse ka järgmisel aastal sama seminari ettevalmistamisel (see on elulisem kui
  plaan). Seepärast lisa lõppu jaotis, mis võrdleb plaani ja tegelikkust: mis jõuti, mis jäi
  tegemata või lükkus edasi, mis võttis plaanitust kauem või lühemalt, millised küsimused ja
  arusaamatused üliõpilastel tekkisid ning mis õppetunnid sellest järgmiseks korraks tulevad.
- Paranda vaikimisi ilmsed kõnetuvastuse vead (kasuta plaani terminoloogiat). Ära leiuta midagi,
  mida transkriptsioonis pole. Kui midagi jääb ebaselgeks, jäta see välja.
- ÄRA kasuta üliõpilaste ega teiste isikute nimesid ega tsiteeri üliõpilasi; räägi „õppejõud“,
  „üks tiim“, „üliõpilased küsisid“.

Vorm (Markdown):
- Alusta täpselt nii: "# Konspekt: {seminar}" ja selle järel üks lühike lõik: mis oli seminari
  fookus ja kuidas see kulges võrreldes plaaniga (kui palju plaanist jõuti).
- Seejärel "## "-pealkirjad teemade kaupa (sisulised pealkirjad, mitte "Osa 1"), vajadusel "### ".
- Hästi loetav: lühikesed lõigud, loomulik ja selge keel (mitte kantseliit), loetelud ainult seal,
  kus need tõesti aitavad; olulised mõisted **paksus kirjas** esimesel esinemisel.
- Iga teema pealkirja järele (samale reale) lisa viide salvestusele kujul [[osa@m:ss]],
  nt "## Riskide hindamine [[1@23:10]]" – osa number ja ajatempel transkriptsioonist.
- Lisaplaani asjad pane alajaotusse "## Lisaks plaanile" (kui neid oli), seejärel
  "## Kodutöö ja järgmised sammud" (kui neist räägiti) ja viimaseks "## Plaan ja tegelikkus"
  (lühike, konkreetne; ilma viideteta salvestusele).
- Pikkus vastavalt sisule (tavaliselt 1500–3500 sõna). Tagasta AINULT konspekti Markdown, ilma
  koodiploki märkideta ja ilma saatesõnata.

SEMINARI PLAAN (seminar.md):
{plan}

TRANSKRIPTSIOONID:
{transcripts}
"""


@dataclass
class PartInput:
    part: int
    video_id: str | None
    words: list


def plan_text(md_path: Path | None, max_chars: int = 20_000) -> str:
    if not md_path or not md_path.exists():
        return "(plaan puudub)"
    t = seminarlinks._BLOCK_RE.sub("", md_path.read_text(encoding="utf-8"))
    return t if len(t) <= max_chars else t[:max_chars] + "\n[…plaan lühendatud…]"


def build_prompt(course: str, seminar: str, date: str, plan: str, parts: list[PartInput]) -> str:
    per = max(40_000, 200_000 // max(1, len(parts)))
    chunks = [f"=== OSA {p.part} ===\n{describe_mod.compact_transcript(p.words, max_chars=per)}" for p in parts]
    return PROMPT.format(course=course, seminar=seminar, date=date,
                         parts=", ".join(str(p.part) for p in parts), plan=plan, transcripts="\n\n".join(chunks))


def link_refs(md: str, videos: dict[int, str | None]) -> str:
    def sub(m: re.Match) -> str:
        part, ts = int(m.group(1)), m.group(2)
        sec = describe_mod.to_seconds(ts)
        vid = videos.get(part)
        label = f"▶ {ts}" if len(videos) == 1 else f"▶ {part}. osa {ts}"
        return f"[{label}](https://youtu.be/{vid}?t={sec})" if vid and sec is not None else ""
    out = REF_RE.sub(sub, md)
    return re.sub(r"[ \t]+\n", "\n", out)


def clean(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^```(?:markdown|md)?\s*\n", "", t)
    t = re.sub(r"\n```\s*$", "", t)
    i = t.find("# Konspekt")
    if i > 0:
        t = t[i:]
    if not t.startswith("# "):
        raise ValueError("vastus ei alga pealkirjaga")
    if len(t.split()) < 200:
        raise ValueError("konspekt liiga lühike")
    return t.strip() + "\n"


def marker(parts: list[int]) -> str:
    return (f"<!-- loengud:konspekt osad={','.join(map(str, parts))} (automaatne; kui muudad käsitsi, "
            f"kustuta see rida – siis tööriist seda üle ei kirjuta) -->")


def existing_parts(path: Path) -> list[int] | None:
    """None = faili pole; [] = käsitsi muudetud (marker puudub); muidu kaetud osad."""
    if not path.exists():
        return None
    m = MARK_RE.search(path.read_text(encoding="utf-8")[:500])
    return [int(x) for x in m.group(1).split(",")] if m else []


def generate(cfg: DescribeConfig, course: str, seminar: str, date: str, plan: str, parts: list[PartInput],
             run=None, log=print) -> str:
    prompt = build_prompt(course, seminar, date, plan, parts)
    if run is None:
        log("  konspekt: " + " ".join(cfg.command))
        try:
            r = subprocess.run(cfg.command, input=prompt, capture_output=True, text=True,
                               timeout=cfg.konspekt_timeout_s)
        except FileNotFoundError as e:
            raise RuntimeError(f"{cfg.command[0]} puudub (Claude Code CLI)") from e
        if r.returncode != 0:
            raise RuntimeError(f"konspekti genereerimine ebaõnnestus: {(r.stderr or r.stdout).strip()[-400:]}")
        text = r.stdout
    else:
        text = run(prompt)
    md = link_refs(clean(text), {p.part: p.video_id for p in parts})
    nums = sorted(p.part for p in parts)
    note = ("> Automaatne kokkuvõte seminari salvestusest (kõnetuvastus + keelemudel). "
            "Võib sisaldada ebatäpsusi – täpse sõnastuse leiad transkriptsioonist.")
    head, _, rest = md.partition("\n")
    return f"{marker(nums)}\n{head}\n\n{note}\n{rest}"


def load_part(part: int, result_json: Path, video_id: str | None) -> PartInput:
    words, _ = subtitles.load_words(result_json)
    return PartInput(part=part, video_id=video_id, words=words)
