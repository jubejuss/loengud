"""Keskne seadistus (~/.config/loengud/config.yaml)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path(os.environ.get("LOENGUD_CONFIG", "~/.config/loengud/config.yaml")).expanduser()


def _p(value: str | os.PathLike | None) -> Path | None:
    if value is None:
        return None
    return Path(os.path.expandvars(str(value))).expanduser()


@dataclass
class SourceConfig:
    recordings_dirs: list[Path]
    extensions: list[str] = field(default_factory=lambda: [".mp4"])
    min_age_minutes: int = 20
    ignore_before: date | None = None
    # Teamsi failinime ajatempli ajavöönd (nt "Koosolek-20261119_081530-Meeting Recording.mp4").
    filename_tz: str = "UTC"


@dataclass
class AsrConfig:
    # Kohalik kloon (soovitatud, versioon lukus) või "taltechnlp/est-asr-pipeline".
    pipeline: str = "~/tools/est-asr-pipeline"
    nextflow_bin: str = "nextflow"
    profile: str | None = None  # nt "lowmem"
    extra_args: list[str] = field(default_factory=lambda: ["--do_speaker_id", "false", "--do_language_id", "false"])
    timeout_hours: float = 8.0
    # Apple Silicon Macis: "--platform linux/amd64 --memory=10g" (pilt on ainult x86_64)
    docker_run_options: str | None = None
    keep_work: bool = False  # jäta Nextflow'i work/ kaust alles (silumiseks)


@dataclass
class YoutubeConfig:
    upload_mode: str = "studio"  # "studio" | "api"
    privacy: str = "unlisted"
    category_id: str = "27"  # Education
    client_secrets: Path = Path("~/.config/loengud/client_secret.json").expanduser()
    token: Path = Path("~/.config/loengud/youtube_token.json").expanduser()
    caption_language: str = "et"
    caption_name: str = "Eesti (automaatne, TalTech ASR)"
    staging_dir: Path = Path("~/Movies/Loengud-üleslaadimiseks").expanduser()
    # Esitusloendid, kuhu läheb IGA loeng (lisaks kursuse omale), nt Haapsalu kolledž
    common_playlist_ids: list[str] = field(default_factory=list)
    # Kui kaua oodatakse Studio-üleslaadimist enne hoiatust (päevades)
    studio_wait_warn_days: int = 3


@dataclass
class GitConfig:
    push: bool = True
    pull_before: bool = True
    commit_template: str = "{seminar_title}: salvestuse transkriptsioon ({date})"


@dataclass
class TimetableConfig:
    teacher_id: int | None = None      # Kalberg, Juho = 435
    url: str = "https://start.hk.tlu.ee/sahtelbeta/tunniplaan/tunniplaan.php"
    semester_start: date | None = None
    semester_end: date | None = None
    cache_hours: float = 12


@dataclass
class Config:
    timezone: str
    source: SourceConfig
    repos: list[Path]
    asr: AsrConfig
    youtube: YoutubeConfig
    git: GitConfig
    timetable: TimetableConfig
    work_dir: Path
    state_file: Path
    path: Path | None = None


def _merge(dc_cls, data: dict[str, Any] | None, path_fields: tuple[str, ...] = ()):
    data = dict(data or {})
    for k in path_fields:
        if k in data and data[k] is not None:
            data[k] = _p(data[k])
    return dc_cls(**data)


def load_config(path: Path | None = None) -> Config:
    path = path or DEFAULT_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"Seadistust ei leitud: {path}. Käivita `loengud init`, et luua mall."
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    src = dict(raw.get("source") or {})
    src["recordings_dirs"] = [_p(d) for d in src.get("recordings_dirs", [])]
    src["extensions"] = [e.lower() if e.startswith(".") else "." + e.lower() for e in src.get("extensions", [".mp4"])]
    if isinstance(src.get("ignore_before"), str):
        src["ignore_before"] = date.fromisoformat(src["ignore_before"])
    source = SourceConfig(**src)

    yt = _merge(YoutubeConfig, raw.get("youtube"), ("client_secrets", "token", "staging_dir"))
    if yt.upload_mode not in ("studio", "api"):
        raise ValueError("youtube.upload_mode peab olema 'studio' või 'api'")

    work_dir = _p(raw.get("work_dir", "~/loengud-work"))
    tt = dict(raw.get("timetable") or {})
    for k in ("semester_start", "semester_end"):
        if isinstance(tt.get(k), str):
            tt[k] = date.fromisoformat(tt[k])
    return Config(
        timezone=raw.get("timezone", "Europe/Tallinn"),
        source=source,
        repos=[_p(r) for r in raw.get("repos", [])],
        asr=_merge(AsrConfig, raw.get("asr")),
        youtube=yt,
        git=_merge(GitConfig, raw.get("git")),
        timetable=TimetableConfig(**tt),
        work_dir=work_dir,
        state_file=_p(raw.get("state_file", "~/.config/loengud/state.json")),
        path=path,
    )


CONFIG_TEMPLATE = """\
# Loengute töövoo keskne seadistus
timezone: Europe/Tallinn

source:
  # TLÜ OneDrive'i sünkroonitud Teamsi salvestuste kaust Macis.
  # Kontrolli täpset nime Finderis: ~/Library/CloudStorage/ all.
  recordings_dirs:
    - "~/Library/CloudStorage/OneDrive-TallinnUniversityHaapsaluCollege/Recordings"
  extensions: [".mp4"]
  # Faili ei puututa, kuni see on vähemalt nii mitu minutit muutmata (sünk käib veel).
  min_age_minutes: 20
  # Vanemaid salvestusi ignoreeritakse (vältimaks kogu arhiivi töötlemist).
  ignore_before: "2026-11-01"
  # Teamsi failinime ajatempli ajavöönd. Kontrolli ühe salvestuse peal (`loengud scan`).
  filename_tz: UTC

# Loengurepod (kohalikud GitHubi kloonid). Igas repos peab olema .loengud.yaml
repos:
  - "~/Projects/loengud/rif25-veebiarendus"

asr:
  # git clone https://github.com/taltechnlp/est-asr-pipeline ~/tools/est-asr-pipeline
  pipeline: "~/tools/est-asr-pipeline"
  nextflow_bin: nextflow
  profile: null          # väikese RAM-i korral: lowmem
  # keeletuvastus (PyTorch) ei tööta M1 amd64-emulatsioonis → kõik segmendid filtreeritakse välja
  extra_args: ["--do_speaker_id", "false", "--do_language_id", "false"]
  timeout_hours: 8
  # Apple Silicon (M1) puhul vajalik, Intel iMacis jäta null:
  docker_run_options: null   # nt "--platform linux/amd64 --memory=10g --cpus=6"

youtube:
  # studio = video laed ise YouTube Studiosse (failinimi = pealkiri), skript lisab subtiitrid + playlisti
  # api    = skript laeb ka video üles (vajab läbitud YouTube API auditit, muidu lukustub privaatseks)
  upload_mode: studio
  privacy: unlisted
  client_secrets: "~/.config/loengud/client_secret.json"
  token: "~/.config/loengud/youtube_token.json"
  caption_language: et
  caption_name: "Eesti (automaatne, TalTech ASR)"
  staging_dir: "~/Movies/Loengud-üleslaadimiseks"
  # Iga loeng lisatakse ka nendesse esitusloenditesse (lisaks kursuse omale):
  common_playlist_ids:
    - "PL2lxpfi7Jl2uqRbh4Ew7v0jdKjteolb4_"   # Haapsalu kolledž

# TLÜ Haapsalu kolledži tunniplaan: aeg → aine (kood) → kursuse repo, seminari nr = mitmes toimumiskord
timetable:
  teacher_id: 435              # Kalberg, Juho (start.hk.tlu.ee tunniplaan)
  semester_start: "2026-08-24"
  semester_end: "2027-01-24"

git:
  push: true
  pull_before: true
  commit_template: "{seminar_title}: salvestuse transkriptsioon ({date})"

work_dir: "~/loengud-work"
state_file: "~/.config/loengud/state.json"
"""
