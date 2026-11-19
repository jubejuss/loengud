"""Töövoo orkestreerimine: salvestus → seminar → ASR → repo → YouTube."""
from __future__ import annotations

import shutil
import subprocess
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import asr as asr_mod
from . import gitops, subtitles
from . import youtube as yt
from .config import Config
from .schedule import Course, MatchError, Seminar, find_seminar, load_courses, match_smart, template_vars
from . import tunniplaan
from .source import Recording, discover
from .state import STAGES, State


def stage_idx(stage: str | None) -> int:
    return STAGES.index(stage) if stage in STAGES else -1


@dataclass
class Deps:
    """Väliste süsteemide sõltuvused – testides asendatavad."""
    transcribe: Callable[[Path, Path], Path] | None = None  # (video, job_dir) -> result.json
    youtube_service: Callable[[], object] | None = None
    log: Callable[[str], None] = field(default=lambda m: print(m, flush=True))


def output_names(part: int) -> dict[str, str]:
    sfx = f"-{part}" if part > 1 else ""
    return {"md": f"transkriptsioon{sfx}.md", "srt": f"subtiitrid{sfx}.et.srt", "vtt": f"subtiitrid{sfx}.et.vtt"}


def clone_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    if sys.platform == "darwin":
        r = subprocess.run(["cp", "-c", str(src), str(dst)], capture_output=True)
        if r.returncode == 0:
            return
    shutil.copy2(src, dst)


class Pipeline:
    def __init__(self, cfg: Config, deps: Deps | None = None):
        self.cfg = cfg
        self.deps = deps or Deps()
        self.log = self.deps.log
        self.state = State(cfg.state_file)
        self.courses, self.course_errors = load_courses(cfg.repos)
        self._yt = None
        self._sessions = None

    def sessions(self):
        """Tunniplaan (vahemälus). Kui pole seadistatud või võrk ei vasta → None (varuvariandid)."""
        tt = self.cfg.timetable
        if self._sessions is None and tt.teacher_id and tt.semester_start and tt.semester_end:
            try:
                self._sessions = tunniplaan.load_cached(self.cfg.work_dir / "tunniplaan.json", tt.teacher_id,
                                                        tt.semester_start, tt.semester_end, tt.url, tt.cache_hours)
            except Exception as e:  # noqa: BLE001
                self.log(f"HOIATUS: tunniplaani ei saanud laadida ({e}) – sobitan pealkirja/ajakava järgi")
                self._sessions = []
        return self._sessions or None

    def seminar_from_state(self, course: Course, st: dict) -> Seminar:
        try:
            return find_seminar(course, st["seminar_dir"])
        except KeyError:
            from datetime import date as _d
            return Seminar(date=_d.fromisoformat(st["seminar_date"]), dir=st["seminar_dir"],
                           title=st.get("seminar_title") or st["seminar_dir"], number=st.get("seminar_number"))

    # --- abid ----------------------------------------------------------------
    def course_by_repo(self, repo: str) -> Course:
        for c in self.courses:
            if str(c.repo) == repo:
                return c
        raise KeyError(f"Repo {repo} pole seadistuses või selle .loengud.yaml ei laadinud.")

    def youtube(self):
        if self._yt is None:
            self._yt = self.deps.youtube_service() if self.deps.youtube_service else yt.get_service(self.cfg.youtube)
        return self._yt

    def transcribe(self, video: Path, job_dir: Path) -> Path:
        if self.deps.transcribe:
            return self.deps.transcribe(video, job_dir)
        wav = asr_mod.extract_audio(video, job_dir / "audio.wav")
        result = asr_mod.transcribe(self.cfg.asr, wav, job_dir, log=self.log)
        wav.unlink(missing_ok=True)
        return result

    # --- põhitsükkel -------------------------------------------------------------
    def scan(self) -> list[tuple[Recording, dict]]:
        out = []
        for rec in discover(self.cfg):
            st = self.state.get(rec.key) or {}
            if st.get("size") not in (None, rec.size) and stage_idx(st.get("stage")) < stage_idx("committed"):
                st = {}  # fail muutus enne töötlemist – alusta otsast
            if not st:
                st = self.state.upsert(rec.key, stage="discovered", size=rec.size, problem=None,
                                       meeting_title=rec.meeting_title, start=rec.start.isoformat(),
                                       start_source=rec.start_source)
            out.append((rec, st))
        return out

    def run(self, only: Path | None = None, dry_run: bool = False) -> int:
        for e in self.course_errors:
            self.log(f"HOIATUS: {e}")
        problems = 0
        for rec, st in self.scan():
            if only and rec.path.resolve() != only.resolve():
                continue
            if st.get("stage") in ("done", "ignored"):
                continue
            self.log(f"\n▶ {rec.path.name}  ({rec.start:%d.%m.%Y %H:%M}, {rec.start_source})")
            try:
                self.process(rec, dry_run=dry_run)
            except Exception as e:  # noqa: BLE001
                problems += 1
                self.state.upsert(rec.key, problem=f"{type(e).__name__}: {e}", problem_kind="error")
                self.log(f"  ✗ {type(e).__name__}: {e}")
                if self.cfg.path is None:  # testides näita jälge
                    traceback.print_exc()
            else:
                if (self.state.get(rec.key) or {}).get("problem"):
                    problems += 1
        return problems

    def process(self, rec: Recording, dry_run: bool = False) -> None:
        key = rec.key
        st = self.state.get(key)

        # 1) sobitamine
        if not st.get("repo"):
            try:
                m = match_smart(self.courses, rec.start, rec.meeting_title, self.sessions(), self.cfg.timezone)
            except MatchError as e:
                self.state.upsert(key, problem=str(e), problem_kind=e.kind,
                                  candidates=[f"{c.course.repo}:{c.seminar.dir}" for c in e.candidates])
                self.log(f"  ? {e}")
                return
            parts = self.state.parts_for(str(m.course.repo), m.seminar.dir, key)
            part = (max(parts) + 1) if parts else 1
            if dry_run:
                self.log(f"  → {m.course.course}: {m.seminar.title} [{m.seminar.dir}] osa {part} (kuivkäivitus)")
                return
            st = self.state.upsert(key, repo=str(m.course.repo), seminar_dir=m.seminar.dir, part=part,
                                   seminar_title=m.seminar.title, seminar_date=m.seminar.date.isoformat(),
                                   seminar_number=m.seminar.number,
                                   stage="matched", problem=None, problem_kind=None)
        course = self.course_by_repo(st["repo"])
        seminar = self.seminar_from_state(course, st)
        part = st.get("part", 1)
        tv = template_vars(course, seminar, part)
        title = course.title_template.format(**tv)
        description = course.description_template.format(**tv).strip()
        self.log(f"  → {course.course}: {seminar.title} [{seminar.dir}] osa {part}")
        if dry_run:
            self.log(f"  etapp: {st.get('stage')}")
            return

        out_dir = course.repo / seminar.dir / course.recording_subdir
        names = output_names(part)
        rid = asr_mod.recording_id(rec.path, rec.size)
        job_dir = self.cfg.work_dir / rid

        # 2) transkribeerimine
        if stage_idx(st["stage"]) < stage_idx("transcribed"):
            self.log("  ASR käib (võib võtta tunde)…")
            result = self.transcribe(rec.path, job_dir)
            st = self.state.upsert(key, stage="transcribed", result_json=str(result), problem=None)

        # 3) repo
        if stage_idx(st["stage"]) < stage_idx("committed"):
            self._write_outputs(course, seminar, part, Path(st["result_json"]), out_dir, names, rec,
                                video_id=st.get("video_id"), title=title)
            msg = self.cfg.git.commit_template.format(**tv)
            sha = self._commit(course, [out_dir / n for n in names.values()], msg)
            st = self.state.upsert(key, stage="committed", commit=sha, problem=None)
            self.log(f"  ✓ repo: {out_dir.relative_to(course.repo)} ({sha or 'muutusteta'})")

        # 4) YouTube video
        if stage_idx(st["stage"]) < stage_idx("uploaded"):
            if st.get("existing_video_id"):
                vid = st["existing_video_id"]
                self.log(f"  olemasolev video {vid} – pealkirja/kirjeldust ei muuda")
            elif self.cfg.youtube.upload_mode == "api":
                self.log("  YouTube: laen video üles…")
                vid = yt.upload_video(self.youtube(), rec.path, title, description, self.cfg.youtube, log=self.log)
            else:
                vid = self._studio_flow(rec, key, st, title, description)
                if not vid:
                    return
            st = self.state.upsert(key, stage="uploaded", video_id=vid, problem=None)
            # lisa videolink transkriptsiooni
            self._write_outputs(course, seminar, part, Path(st["result_json"]), out_dir, names, rec,
                                video_id=vid, title=title)
            self._commit(course, [out_dir / names["md"]], f"{tv['seminar_title']}: videolink")
            self.log(f"  ✓ video: https://youtu.be/{vid}")

        # 5) subtiitrid
        if stage_idx(st["stage"]) < stage_idx("captioned"):
            cid = yt.upsert_captions(self.youtube(), st["video_id"], out_dir / names["srt"], self.cfg.youtube)
            st = self.state.upsert(key, stage="captioned", caption_id=cid)
            self.log("  ✓ subtiitrid lisatud")

        # 6) esitusloend
        if stage_idx(st["stage"]) < stage_idx("done"):
            pids = course.all_playlist_ids(self.cfg.youtube.common_playlist_ids)
            if not pids:
                self.log("  (esitusloendit pole .loengud.yaml-is ega config.yaml-is määratud)")
            for pid in pids:
                added = yt.ensure_in_playlist(self.youtube(), pid, st["video_id"])
                self.log(f"  ✓ esitusloend {pid}: " + ("lisatud" if added else "juba olemas"))
            self.state.upsert(key, stage="done", problem=None, problem_kind=None)

    # --- alamsammud ---------------------------------------------------------------
    def _write_outputs(self, course, seminar, part, result_json: Path, out_dir: Path, names: dict,
                       rec: Recording, video_id: str | None, title: str) -> None:
        words, speakers = subtitles.load_words(result_json)
        if not words:
            raise RuntimeError("ASR tulemus on tühi (kõnet ei tuvastatud?)")
        cues = subtitles.segment(words)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / names["srt"]).write_text(subtitles.to_srt(cues), encoding="utf-8")
        (out_dir / names["vtt"]).write_text(subtitles.to_vtt(cues), encoding="utf-8")
        meta = {
            "title": title,
            "course": course.course,
            "seminar": seminar.title,
            "date": seminar.date.isoformat(),
            "part": part if part > 1 else None,
            "duration": subtitles.hms(words[-1].end),
            "recorded": rec.start.isoformat(timespec="minutes"),
            "source_file": rec.path.name,
            "asr": "TalTech est-asr-pipeline (tekstiks.ee mootor)",
            "generated": datetime.now().astimezone().isoformat(timespec="minutes"),
        }
        (out_dir / names["md"]).write_text(subtitles.to_markdown(words, speakers, meta, video_id), encoding="utf-8")

    def _commit(self, course: Course, paths: list[Path], message: str) -> str | None:
        if self.cfg.git.pull_before:
            gitops.pull(course.repo)
        return gitops.commit_paths(course.repo, paths, message, push=self.cfg.git.push)

    def _studio_flow(self, rec: Recording, key: str, st: dict, title: str, description: str) -> str | None:
        staged = self.cfg.youtube.staging_dir / f"{yt.safe_filename(title)}.mp4"
        if stage_idx(st["stage"]) < stage_idx("awaiting_upload"):
            clone_or_copy(rec.path, staged)
            st = self.state.upsert(key, stage="awaiting_upload", staged=str(staged),
                                   awaiting_since=datetime.now().astimezone().isoformat(timespec="minutes"))
        vid = yt.find_uploaded_video(self.youtube(), title)
        if not vid:
            self.log(f"  ⏳ ootab üleslaadimist YouTube Studiosse: {staged}")
            return None
        self.log(f"  leitud Studios üles laaditud video {vid} – uuendan pealkirja, kirjelduse, privaatsuse")
        yt.update_metadata(self.youtube(), vid, title, description, self.cfg.youtube, log=self.log)
        Path(st.get("staged") or staged).unlink(missing_ok=True)
        return vid

    # --- käsitsi sekkumine ---------------------------------------------------------
    def attach_video(self, recording: Path, video_id: str) -> None:
        """Seo salvestus juba YouTube'is oleva videoga (ei laadi üles, ei muuda pealkirja)."""
        self.scan()
        key = str(recording)
        if not self.state.get(key):
            raise KeyError(f"Salvestust {recording} ei leitud.")
        vid = video_id.split("v=")[-1].split("/")[-1].split("?")[0].split("&")[0]
        self.state.upsert(key, existing_video_id=vid)

    def assign(self, recording: Path, repo: Path, seminar_dir: str, part: int | None = None) -> None:
        course = self.course_by_repo(str(repo.expanduser()))
        from .schedule import seminar_for_number  # noqa: F401
        try:
            sem = find_seminar(course, seminar_dir)
        except KeyError:
            sem = None
        self.scan()
        key = str(recording)
        if not self.state.get(key):
            raise KeyError(f"Salvestust {recording} ei leitud (kas see on `recordings_dirs` all ja piisavalt vana?)")
        parts = self.state.parts_for(str(course.repo), seminar_dir.strip("/"), key)
        rec_start = (self.state.get(key) or {}).get("start", "")[:10]
        self.state.upsert(key, repo=str(course.repo), seminar_dir=seminar_dir.strip("/"),
                          part=part or ((max(parts) + 1) if parts else 1),
                          seminar_title=sem.title if sem else seminar_dir.strip("/").split("/")[-1],
                          seminar_date=(sem.date.isoformat() if sem else rec_start),
                          stage="matched", problem=None, problem_kind=None)

    def ignore(self, recording: Path) -> None:
        self.scan()
        self.state.upsert(str(recording), stage="ignored", problem=None, problem_kind=None)

    def retry(self, recording: Path, from_stage: str) -> None:
        if from_stage not in STAGES:
            raise ValueError(f"Tundmatu etapp; võimalikud: {', '.join(STAGES)}")
        self.state.upsert(str(recording), stage=from_stage, problem=None, problem_kind=None)
