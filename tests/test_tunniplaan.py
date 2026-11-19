from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from loengud import tunniplaan as tp
from loengud.schedule import Course, Seminar, match_smart, title_number

TZ = "Europe/Tallinn"
HTML = """<table id="timetable"><tr><th>AEG</th></tr>
<tr><td class="weekline" colspan="4">45. nädal</td></tr>
<tr><td class="dateline" colspan="4">Neljapäev, 10. september 2026</td></tr>
<tr><td class="classline" colspan="4">Rakendusinformaatika 1. kursus</td></tr>
<tr class="fields_row" value="1"><td>14:15 - 17:30</td><td class="max_width_250">Sissejuhatus tarkvaraarendusse (HKI5113.HK) [<span class="hover" value=""></span>] <br><span class="teacher">Juho Kalberg</span></td><td class="center eaps">4</td><td>Arvutilabor 203</td></tr>
<tr><td class="dateline" colspan="4">Neljapäev, 12. november 2026</td></tr>
<tr><td class="classline" colspan="4">Rakendusinformaatika 2. kursus</td></tr>
<tr class="fields_row" value="2"><td>10:00 - 13:15</td><td>Veebiraamistike rakendamine (HKI5122.HK) [<span></span>] <br><span class="teacher">Juho Kalberg</span></td><td>4</td><td>Arvutilabor 203</td></tr>
<tr class="fields_row" value="3"><td>14:15 - 17:30</td><td>Kasutajaliidese disain (HKI5120.HK) [<span></span>] <br><span class="teacher">Juho Kalberg</span></td><td>4</td><td>Arvutilabor 203</td></tr>
<tr><td class="dateline" colspan="4">Neljapäev, 19. november 2026</td></tr>
<tr><td class="classline" colspan="4">Rakendusinformaatika 1. kursus</td></tr>
<tr class="fields_row" value="4"><td>14:15 - 17:30</td><td>Sissejuhatus tarkvaraarendusse (HKI5113.HK) [<span></span>] <br><span class="teacher">Juho Kalberg</span></td><td>4</td><td></td></tr>
</table>"""


def test_parse():
    s = tp.parse(HTML)
    assert len(s) == 4
    assert s[0].date == "2026-09-10" and s[0].start == "14:15" and s[0].code == "HKI5113.HK"
    assert s[0].subject == "Sissejuhatus tarkvaraarendusse" and s[0].group.startswith("Rakendusinformaatika")
    assert tp.ordinal(s, s[3]) == 2


def test_title_number():
    assert title_number("SJTA 3") == 3
    assert title_number("Sissejuhatus Tarkvaraarendusse 4") == 4
    assert title_number("Koosolek") is None
    assert title_number("RIF25") is None


def _c(name, code, titles, repo):
    return Course(repo=repo, course=name, playlist_id=None, seminars=[], subject_codes=[code], match_titles=titles)


def test_match_smart_timetable(tmp_path):
    (tmp_path / "seminarid" / "seminar_02").mkdir(parents=True)
    (tmp_path / "seminarid" / "seminar_02" / "seminar.md").write_text("# Seminar 2: Git ja GitHub\n")
    sjta = _c("SJTA", "HKI5113.HK", ["SJTA", "Sissejuhatus tarkvara"], tmp_path)
    kd = _c("KD", "HKI5120.HK", ["Kasutajaliides"], tmp_path / "kd")
    sessions = tp.parse(HTML)
    # pealkirjas numbrit pole → järjekorranumber tunniplaanist
    m = match_smart([sjta, kd], datetime(2026, 11, 19, 14, 16, tzinfo=ZoneInfo(TZ)), "Koosolek", sessions, TZ)
    assert m.course is sjta and m.seminar.dir == "seminarid/seminar_02" and m.seminar.title == "Seminar 2: Git ja GitHub"
    # teine osa 16:10 sobib samuti
    m = match_smart([sjta, kd], datetime(2026, 11, 19, 16, 10, tzinfo=ZoneInfo(TZ)), "x", sessions, TZ)
    assert m.course is sjta
    # pealkirja number võidab
    m = match_smart([sjta, kd], datetime(2026, 11, 12, 15, 20, tzinfo=ZoneInfo(TZ)), "KAsutajaliideste disain 3", sessions, TZ)
    assert m.course is kd and m.seminar.number == 3 and m.seminar.dir == "seminarid/seminar_03"


def test_match_by_title_without_timetable(tmp_path):
    sjta = _c("SJTA", "HKI5113.HK", ["SJTA"], tmp_path)
    m = match_smart([sjta], datetime(2026, 11, 5, 14, 16, tzinfo=ZoneInfo(TZ)), "SJTA 3", None, TZ)
    assert m.seminar.dir == "seminarid/seminar_03" and m.seminar.date == date(2026, 11, 5)
