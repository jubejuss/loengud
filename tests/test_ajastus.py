from datetime import date

from loengud import ajastus, tunniplaan
from test_tunniplaan import HTML


def test_run_times_after_lessons_only_future_and_codes():
    sessions = tunniplaan.parse(HTML)
    times = ajastus.run_times(sessions, "Europe/Tallinn", {"HKI5113.HK"}, today=date(2026, 11, 1))
    # ainult 19.11 SJTA (10.09 on minevikus): lõpp 17:30 → 18:00, 18:45, 20:00
    assert [t.strftime("%d.%m %H:%M") for t in times] == ["19.11 18:00", "19.11 18:45", "19.11 20:00"]
    plist = ajastus.build_run_plist(times)
    cal = plist["StartCalendarInterval"]
    assert {"Month": 11, "Day": 19, "Hour": 18, "Minute": 0} in cal and {"Hour": 21, "Minute": 0} in cal
    assert plist["ProgramArguments"][-1] == "run" and "/.local/bin" in plist["EnvironmentVariables"]["PATH"]


def test_run_times_all_codes_when_none():
    sessions = tunniplaan.parse(HTML)
    times = ajastus.run_times(sessions, "Europe/Tallinn", None, today=date(2026, 11, 12))
    assert len(times) == 3 * 3  # 12.11 kaks tundi + 19.11
