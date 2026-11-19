"""launchd ajastus TLÜ HK tunniplaani järgi: töövoog käivitub pärast iga loengu lõppu.

Kaks LaunchAgent'i:
  ee.vileandkell.loengud          – `loengud run`: loengu lõpp +30/+75/+150 min ja iga päev 21:00 (varu)
  ee.vileandkell.loengud.ajastus  – `loengud ajastus install`: iga hommik 07:10 loeb tunniplaani uuesti
"""
from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

LABEL_RUN = "ee.vileandkell.loengud"
LABEL_REFRESH = "ee.vileandkell.loengud.ajastus"
AGENTS = Path("~/Library/LaunchAgents").expanduser()
OFFSETS_MIN = (30, 75, 150)
DAILY_FALLBACK = (21, 0)
REFRESH_AT = (7, 10)


def run_times(sessions, tz: str, codes: set[str] | None, today: date | None = None,
              offsets=OFFSETS_MIN) -> list[datetime]:
    today = today or datetime.now(ZoneInfo(tz)).date()
    out = set()
    for s in sessions:
        if codes and s.code not in codes:
            continue
        if date.fromisoformat(s.date) < today:
            continue
        end = s.end_dt(tz)
        for m in offsets:
            out.add((end + timedelta(minutes=m)).replace(second=0, microsecond=0))
    return sorted(out)


def _env() -> dict:
    home = str(Path.home())
    path = ":".join([f"{home}/.local/bin", "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin",
                     "/Applications/Docker.app/Contents/Resources/bin", f"{home}/.orbstack/bin"])
    return {"PATH": path, "LANG": "et_EE.UTF-8", "HOME": home}


def _bin() -> str:
    return shutil.which("loengud") or str(Path("~/.local/bin/loengud").expanduser())


def build_run_plist(times: list[datetime]) -> dict:
    cal = [{"Month": t.month, "Day": t.day, "Hour": t.hour, "Minute": t.minute} for t in times]
    cal.append({"Hour": DAILY_FALLBACK[0], "Minute": DAILY_FALLBACK[1]})
    log = str(Path("~/Library/Logs/loengud.log").expanduser())
    return {"Label": LABEL_RUN, "ProgramArguments": [_bin(), "run"], "EnvironmentVariables": _env(),
            "StartCalendarInterval": cal, "RunAtLoad": False, "LowPriorityIO": True, "Nice": 10,
            "StandardOutPath": log, "StandardErrorPath": log}


def build_refresh_plist() -> dict:
    log = str(Path("~/Library/Logs/loengud.log").expanduser())
    return {"Label": LABEL_REFRESH, "ProgramArguments": [_bin(), "ajastus", "install"],
            "EnvironmentVariables": _env(),
            "StartCalendarInterval": [{"Hour": REFRESH_AT[0], "Minute": REFRESH_AT[1]}],
            "RunAtLoad": False, "StandardOutPath": log, "StandardErrorPath": log}


def _launchctl(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def _loaded(label: str) -> bool:
    return _launchctl("print", f"gui/{os.getuid()}/{label}").returncode == 0


def _write_and_load(label: str, data: dict, force_reload: bool) -> bool:
    AGENTS.mkdir(parents=True, exist_ok=True)
    path = AGENTS / f"{label}.plist"
    new = plistlib.dumps(data)
    changed = not path.exists() or path.read_bytes() != new
    if changed:
        path.write_bytes(new)
    if changed or force_reload or not _loaded(label):
        if _loaded(label):
            _launchctl("bootout", f"gui/{os.getuid()}/{label}")
        r = _launchctl("bootstrap", f"gui/{os.getuid()}", str(path))
        if r.returncode != 0 and "already" not in (r.stderr or ""):
            raise RuntimeError(f"launchctl bootstrap {label}: {r.stderr.strip()}")
    return changed


def install(times: list[datetime], log=print) -> None:
    changed = _write_and_load(LABEL_RUN, build_run_plist(times), force_reload=False)
    # Värskendusjobi ei laeta enda seest ümber (see töötab parasjagu) – ainult kui puudub
    if not _loaded(LABEL_REFRESH):
        _write_and_load(LABEL_REFRESH, build_refresh_plist(), force_reload=False)
    nxt = [t for t in times if t > datetime.now(t.tzinfo)][:3]
    log(("Ajastus uuendatud" if changed else "Ajastus muutmata") +
        f": {len(times)} käivitust tunniplaanist + iga päev {DAILY_FALLBACK[0]}:{DAILY_FALLBACK[1]:02d}.")
    for t in nxt:
        log(f"  järgmine: {t:%a %d.%m %H:%M}")


def uninstall(log=print) -> None:
    for label in (LABEL_RUN, LABEL_REFRESH):
        if _loaded(label):
            _launchctl("bootout", f"gui/{os.getuid()}/{label}")
        p = AGENTS / f"{label}.plist"
        if p.exists():
            p.unlink()
    log("Ajastus eemaldatud.")
