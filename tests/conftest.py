import json
import subprocess
from pathlib import Path

import pytest

SENTENCES = [
    "Tere tulemast neljandasse seminari.",
    "Täna räägime CSS Gridist ja sellest, kuidas paigutust planeerida, ilma et peaks iga elementi eraldi positsioneerima.",
    "Kõigepealt vaatame, mis on grid container ja grid item.",
    "Kas kellelgi on küsimusi?",
]


def make_result(sentences=SENTENCES, speakers=("S1", "S1", "S1", "S2"), word_dur=0.35, gap=0.05):
    t = 0.0
    turns = []
    for sent, spk in zip(sentences, speakers):
        words = []
        start = t
        for w in sent.split():
            words.append({"word": w.strip(".,?").lower(), "word_with_punctuation": w,
                          "start": round(t, 2), "end": round(t + word_dur, 2)})
            t += word_dur + gap
        turns.append({"speaker": spk, "start": start, "end": t, "transcript": sent, "words": words})
        t += 1.5
    return {"speakers": {"S1": {}, "S2": {}},
            "sections": [{"type": "non-speech", "start": 0, "end": 0},
                         {"type": "speech", "start": 0, "end": t, "turns": turns}]}


@pytest.fixture
def result_json(tmp_path) -> Path:
    p = tmp_path / "result.json"
    p.write_text(json.dumps(make_result(), ensure_ascii=False), encoding="utf-8")
    return p


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def lecture_repo(tmp_path) -> Path:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True, capture_output=True)
    repo = tmp_path / "rif25-veebiarendus"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "Test")
    (repo / "seminarid" / "04-css-grid").mkdir(parents=True)
    (repo / "seminarid" / "04-css-grid" / "README.md").write_text("# Seminar 4\n")
    (repo / ".loengud.yaml").write_text(
        """course: "Veebiarendus (RIF25)"
match_title: "RIF25"
youtube:
  playlist_id: "PLtest"
seminars:
  - date: 2026-11-19
    dir: seminarid/04-css-grid
    title: "Seminar 4: CSS Grid"
    time: "10:00-13:15"
  - date: 2026-11-26
    dir: seminarid/05-flexbox
    title: "Seminar 5: Flexbox"
""", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "init")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-u", "origin", "main")
    return repo
