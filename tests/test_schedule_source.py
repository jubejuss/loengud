from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from loengud.schedule import Course, MatchError, Seminar, match_recording
from loengud.source import parse_teams_filename

TZ = ZoneInfo("Europe/Tallinn")


def test_parse_teams_filename_utc_to_tallinn():
    title, start = parse_teams_filename("RIF25 Veebiarendus-20261119_081530-Meeting Recording.mp4", "UTC", "Europe/Tallinn")
    assert title == "RIF25 Veebiarendus"
    assert start == datetime(2026, 11, 19, 10, 15, 30, tzinfo=TZ)


def test_parse_teams_filename_estonian_suffix():
    r = parse_teams_filename("Seminar-20261119_101530-Koosoleku salvestis.mp4", "Europe/Tallinn", "Europe/Tallinn")
    assert r and r[1].hour == 10


def test_parse_non_teams_name():
    assert parse_teams_filename("minu video.mp4", "UTC", "Europe/Tallinn") is None


def _course(name, seminars, match_title=None, default_time=None):
    return Course(repo=Path(f"/r/{name}"), course=name, playlist_id=None, seminars=seminars,
                  match_title=match_title, default_time=default_time)


def test_match_single_by_date():
    c = _course("A", [Seminar(date(2026, 11, 19), "s4", "S4")])
    m = match_recording([c], datetime(2026, 11, 19, 10, 0, tzinfo=TZ), "x")
    assert m.seminar.dir == "s4"


def test_unmatched():
    c = _course("A", [Seminar(date(2026, 11, 19), "s4", "S4")])
    with pytest.raises(MatchError) as e:
        match_recording([c], datetime(2026, 11, 20, 10, 0, tzinfo=TZ), "x")
    assert e.value.kind == "unmatched"


def test_same_day_disambiguated_by_title_then_time():
    a = _course("A", [Seminar(date(2026, 11, 19), "a4", "A4")], match_title="RIF25")
    b = _course("B", [Seminar(date(2026, 11, 19), "b4", "B4", time="14:00-17:00")])
    assert match_recording([a, b], datetime(2026, 11, 19, 10, tzinfo=TZ), "RIF25 loeng").course.course == "A"
    a.match_title = None
    a.default_time = "10:00-13:00"
    assert match_recording([a, b], datetime(2026, 11, 19, 14, 5, tzinfo=TZ), "x").course.course == "B"
    with pytest.raises(MatchError) as e:
        match_recording([a, b], datetime(2026, 11, 19, 20, 0, tzinfo=TZ), "x")
    assert e.value.kind == "ambiguous"
