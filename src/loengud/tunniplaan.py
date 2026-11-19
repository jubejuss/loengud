"""TLÜ Haapsalu kolledži tunniplaan (start.hk.tlu.ee/sahtelbeta/tunniplaan) õppejõu järgi.

Tunniplaani `tunniplaan.php` võtab POST-iga vormi (start, end, teachers, …) ja tagastab HTML-tabeli:
  <td class="dateline">Neljapäev, 05. november 2026</td>
  <td class="classline">Rakendusinformaatika 1. kursus</td>
  <tr class="fields_row"><td>14:15 - 17:30</td><td>Aine (HKI5113.HK) [...] <br><span class="teacher">…</span></td><td>4</td><td>Ruum</td></tr>
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_URL = "https://start.hk.tlu.ee/sahtelbeta/tunniplaan/tunniplaan.php"
MONTHS = {"jaanuar": 1, "veebruar": 2, "märts": 3, "aprill": 4, "mai": 5, "juuni": 6, "juuli": 7,
          "august": 8, "september": 9, "oktoober": 10, "november": 11, "detsember": 12}
CODE_RE = re.compile(r"\(([A-Z]{2,}\d{3,}[^)]*)\)")


@dataclass
class Session:
    date: str      # ISO
    start: str     # "14:15"
    end: str       # "17:30"
    subject: str   # "Sissejuhatus tarkvaraarendusse"
    code: str      # "HKI5113.HK"
    group: str     # "Rakendusinformaatika 1. kursus"
    room: str

    def start_dt(self, tz: str) -> datetime:
        return datetime.fromisoformat(f"{self.date}T{self.start}").replace(tzinfo=ZoneInfo(tz))

    def end_dt(self, tz: str) -> datetime:
        return datetime.fromisoformat(f"{self.date}T{self.end}").replace(tzinfo=ZoneInfo(tz))


def parse_et_date(text: str) -> date | None:
    m = re.search(r"(\d{1,2})\.\s*([a-zäöüõ]+)\s+(\d{4})", text.lower())
    if not m or m.group(2) not in MONTHS:
        return None
    return date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[dict] = []
        self._date = self._group = None
        self._cls = None        # dateline/classline/fields_row td being read
        self._in_fields = False
        self._cells: list[str] = []
        self._buf: list[str] = []
        self._in_td = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr":
            self._in_fields = "fields_row" in (a.get("class") or "")
            self._cells = []
        elif tag == "td":
            self._in_td = True
            self._buf = []
            self._cls = a.get("class") or ""
        elif tag == "br" and self._in_td:
            self._buf.append("\n")

    def handle_endtag(self, tag):
        if tag == "td" and self._in_td:
            text = "".join(self._buf).strip()
            self._in_td = False
            if "dateline" in self._cls:
                self._date = parse_et_date(text)
            elif "classline" in self._cls:
                self._group = text
            elif self._in_fields:
                self._cells.append(text)
        elif tag == "tr" and self._in_fields and len(self._cells) >= 2 and self._date:
            times = re.findall(r"\d{1,2}:\d{2}", self._cells[0])
            name = self._cells[1].split("\n")[0]
            m = CODE_RE.search(name)
            if len(times) >= 2:
                self.rows.append(dict(
                    date=self._date.isoformat(), start=times[0].zfill(5), end=times[1].zfill(5),
                    subject=CODE_RE.sub("", name).split("[")[0].strip(),
                    code=m.group(1).strip() if m else "", group=self._group or "",
                    room=self._cells[3] if len(self._cells) > 3 else ""))
            self._in_fields = False

    def handle_data(self, data):
        if self._in_td:
            self._buf.append(data)


def parse(html: str) -> list[Session]:
    p = _Parser()
    p.feed(html)
    return [Session(**r) for r in p.rows]


def fetch(teacher_id: int | str, start: date, end: date, url: str = DEFAULT_URL, timeout: int = 30) -> list[Session]:
    body = urllib.parse.urlencode({"start": start.isoformat(), "end": end.isoformat(), "checked": "1",
                                   "classes": "", "subjects": "", "teachers": str(teacher_id), "rooms": ""}).encode()
    req = urllib.request.Request(url, data=body, headers={"User-Agent": "loengud/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return parse(r.read().decode("utf-8", errors="replace"))


def load_cached(cache: Path, teacher_id, start: date, end: date, url: str = DEFAULT_URL,
                max_age_h: float = 12) -> list[Session]:
    key = f"{teacher_id}:{start}:{end}"
    if cache.exists():
        try:
            d = json.loads(cache.read_text(encoding="utf-8"))
            if d.get("key") == key and time.time() - d.get("ts", 0) < max_age_h * 3600:
                return [Session(**s) for s in d["sessions"]]
        except Exception:
            pass
    sessions = fetch(teacher_id, start, end, url)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"key": key, "ts": time.time(), "sessions": [asdict(s) for s in sessions]},
                                ensure_ascii=False, indent=1), encoding="utf-8")
    return sessions


def session_at(sessions: list[Session], when: datetime, tz: str, before_min: int = 45, after_min: int = 15) -> list[Session]:
    """Tunnid, mille ajavahemikku (± tolerants) salvestuse algus jääb."""
    from datetime import timedelta
    return [s for s in sessions
            if s.start_dt(tz) - timedelta(minutes=before_min) <= when <= s.end_dt(tz) + timedelta(minutes=after_min)]


def ordinal(sessions: list[Session], target: Session) -> int:
    """Mitmes sama aine (koodi) toimumiskord see semestris on (1-põhine). Sama päeva korduvad read loetakse üheks."""
    days = sorted({s.date for s in sessions if s.code == target.code})
    return days.index(target.date) + 1
