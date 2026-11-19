"""Otsast lõpuni: võlts-ASR + võlts-YouTube, päris git-repo ja remote."""
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from conftest import make_result
from loengud.config import load_config
from loengud.pipeline import Deps, Pipeline


class _Req:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeYouTube:
    def __init__(self):
        self.uploads: list[dict] = []  # {"id","title"}
        self.captions_by_video: dict[str, list] = {}
        self.playlist: set[str] = set()
        self.updated: list[dict] = []
        self.inserted_videos = 0

    # channels().list(...)
    def channels(self):
        yt = self
        class C:
            def list(self, **kw):
                return _Req(lambda: {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU1"}},
                                                "snippet": {"title": "Test"}}]})
        return C()

    def playlistItems(self):
        yt = self
        class P:
            def list(self, playlistId, **kw):
                if playlistId == "UU1":
                    return _Req(lambda: {"items": [{"snippet": {"title": v["title"], "resourceId": {"videoId": v["id"]}}}
                                                   for v in yt.uploads]})
                vid = kw.get("videoId")
                return _Req(lambda: {"items": [{"id": "x"}] if vid in yt.playlist else []})

            def insert(self, part, body):
                return _Req(lambda: yt.playlist.add(body["snippet"]["resourceId"]["videoId"]) or {})
        return P()

    def videos(self):
        yt = self
        class V:
            def insert(self, part, body, media_body):
                class Up:
                    def next_chunk(self_inner):
                        yt.inserted_videos += 1
                        vid = f"api{yt.inserted_videos}"
                        yt.uploads.append({"id": vid, "title": body["snippet"]["title"]})
                        return None, {"id": vid, "status": {"privacyStatus": "unlisted"}}
                return Up()

            def list(self, part, id):
                return _Req(lambda: {"items": [{"snippet": {"categoryId": "27"}, "status": {}}]})

            def update(self, part, body):
                return _Req(lambda: yt.updated.append(body) or {})
        return V()

    def captions(self):
        yt = self
        class Cap:
            def list(self, part, videoId):
                return _Req(lambda: {"items": yt.captions_by_video.get(videoId, [])})

            def insert(self, part, body, media_body):
                def do():
                    vid = body["snippet"]["videoId"]
                    yt.captions_by_video.setdefault(vid, []).append({"id": "cap1", "snippet": body["snippet"]})
                    return {"id": "cap1"}
                return _Req(do)

            def update(self, part, body, media_body):
                return _Req(lambda: {"id": body["id"]})
        return Cap()


def write_config(tmp_path, repo, rec_dir, mode):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"""
timezone: Europe/Tallinn
source:
  recordings_dirs: ["{rec_dir}"]
  min_age_minutes: 0
  filename_tz: UTC
repos: ["{repo}"]
youtube:
  upload_mode: {mode}
  staging_dir: "{tmp_path / 'staging'}"
  client_secrets: "{tmp_path / 'cs.json'}"
  token: "{tmp_path / 'tok.json'}"
git:
  push: true
work_dir: "{tmp_path / 'work'}"
state_file: "{tmp_path / 'state.json'}"
""", encoding="utf-8")
    return load_config(cfg)


def fake_asr(video, job_dir):
    out = job_dir / "result" / "result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(make_result(), ensure_ascii=False), encoding="utf-8")
    return out


def make_recording(rec_dir: Path, name: str) -> Path:
    rec_dir.mkdir(parents=True, exist_ok=True)
    p = rec_dir / name
    p.write_bytes(b"\x00" * 2048)
    old = time.time() - 3600
    os.utime(p, (old, old))
    return p


def remote_log(repo):
    return subprocess.run(["git", "-C", str(repo), "log", "origin/main", "--oneline"], capture_output=True, text=True).stdout


@pytest.mark.parametrize("mode", ["api", "studio"])
def test_full_flow(tmp_path, lecture_repo, mode):
    rec_dir = tmp_path / "OneDrive" / "Recordings"
    rec = make_recording(rec_dir, "RIF25 Veebiarendus-20261119_081530-Meeting Recording.mp4")
    make_recording(rec_dir, "Muu koosolek-20261121_081530-Meeting Recording.mp4")  # sobitamatu
    cfg = write_config(tmp_path, lecture_repo, rec_dir, mode)
    fake = FakeYouTube()
    logs = []
    p = Pipeline(cfg, Deps(transcribe=fake_asr, youtube_service=lambda: fake, log=logs.append))

    problems = p.run()
    assert problems == 1  # sobitamatu salvestus
    out = lecture_repo / "seminarid/04-css-grid/salvestus"
    assert (out / "transkriptsioon.md").exists()
    assert (out / "subtiitrid.et.srt").read_text().startswith("1\n")
    assert "salvestuse transkriptsioon" in remote_log(lecture_repo)

    st = p.state.get(str(rec))
    if mode == "studio":
        assert st["stage"] == "awaiting_upload"
        staged = Path(st["staged"])
        assert staged.exists() and staged.name.startswith("Veebiarendus (RIF25) – Seminar 4 - CSS Grid")
        # kasutaja laeb Studiosse; YouTube paneb pealkirjaks failinime
        fake.uploads.append({"id": "studio1", "title": staged.stem})
        p2 = Pipeline(cfg, Deps(transcribe=fake_asr, youtube_service=lambda: fake, log=logs.append))
        p2.run()
        st = p2.state.get(str(rec))
        assert not staged.exists()
        assert fake.updated and fake.updated[0]["snippet"]["title"] == "Veebiarendus (RIF25) – Seminar 4: CSS Grid (19.11.2026)"
        vid = "studio1"
    else:
        vid = "api1"
    assert st["stage"] == "done", logs
    assert st["video_id"] == vid
    assert fake.captions_by_video[vid][0]["snippet"]["language"] == "et"
    assert vid in fake.playlist
    md = (out / "transkriptsioon.md").read_text()
    assert f"https://youtu.be/{vid}?t=" in md
    assert "videolink" in remote_log(lecture_repo)

    # idempotentsus: teine käivitus ei tee midagi uut
    before = remote_log(lecture_repo)
    Pipeline(cfg, Deps(transcribe=fake_asr, youtube_service=lambda: fake, log=logs.append)).run()
    assert remote_log(lecture_repo) == before
    assert fake.inserted_videos == (1 if mode == "api" else 0)


def test_second_recording_same_seminar_becomes_part_2(tmp_path, lecture_repo):
    rec_dir = tmp_path / "rec"
    make_recording(rec_dir, "RIF25-20261119_081530-Meeting Recording.mp4")
    make_recording(rec_dir, "RIF25-20261119_100500-Meeting Recording.mp4")
    cfg = write_config(tmp_path, lecture_repo, rec_dir, "api")
    fake = FakeYouTube()
    Pipeline(cfg, Deps(transcribe=fake_asr, youtube_service=lambda: fake, log=lambda m: None)).run()
    out = lecture_repo / "seminarid/04-css-grid/salvestus"
    assert (out / "transkriptsioon.md").exists() and (out / "transkriptsioon-2.md").exists()
    titles = [u["title"] for u in fake.uploads]
    assert any("(osa 2)" in t for t in titles)


def test_assign_resolves_unmatched(tmp_path, lecture_repo):
    rec_dir = tmp_path / "rec"
    rec = make_recording(rec_dir, "Lisaloeng-20261121_081530-Meeting Recording.mp4")
    cfg = write_config(tmp_path, lecture_repo, rec_dir, "api")
    fake = FakeYouTube()
    p = Pipeline(cfg, Deps(transcribe=fake_asr, youtube_service=lambda: fake, log=lambda m: None))
    assert p.run() == 1
    p.assign(rec, lecture_repo, "seminarid/05-flexbox")
    assert p.run() == 0
    assert (lecture_repo / "seminarid/05-flexbox/salvestus/transkriptsioon.md").exists()
