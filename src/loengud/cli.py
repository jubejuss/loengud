"""Käsurida: `loengud <käsk>`."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from .config import CONFIG_TEMPLATE, DEFAULT_CONFIG_PATH, load_config
from .state import run_lock

REPO_TEMPLATE = """\
# Loengurepo ajakava töövoo jaoks (loengud)
course: "Veebiarendus (RIF25)"
# Kui samal päeval on mitu kursust, sobitatakse ka Teamsi koosoleku pealkirja järgi:
# match_title: "RIF25"
# Vaikimisi kellaaeg, kui seminaril oma `time` puudub (aitab sama päeva seminare eristada):
# default_time: "10:00-13:15"
recording_subdir: salvestus      # seminari kausta all: salvestus/transkriptsioon.md jms
youtube:
  playlist_id: "PLxxxxxxxxxxxxxxxx"   # kursuse esitusloend, vt docs/esitusloendid.md
  # extra_playlist_ids: []            # lisaks ühisele (config.yaml common_playlist_ids)
  title_template: "{course} – {seminar_title} ({date_et})"
  # description_template: |
  #   {course} · {seminar_title}
  #   {materials_line}
seminars:
  - date: 2026-11-20
    dir: seminarid/04-css-grid
    title: "Seminar 4: CSS Grid"
    # time: "10:00-13:15"
"""


def cmd_init(args) -> int:
    path = Path(args.config or DEFAULT_CONFIG_PATH).expanduser()
    if path.exists() and not args.force:
        print(f"{path} on juba olemas (--force kirjutab üle).")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
        print(f"Loodud: {path}")
    if args.repo:
        rf = Path(args.repo).expanduser() / ".loengud.yaml"
        if rf.exists() and not args.force:
            print(f"{rf} on juba olemas.")
        else:
            rf.write_text(REPO_TEMPLATE, encoding="utf-8")
            print(f"Loodud: {rf}")
    return 0


def cmd_auth(args) -> int:
    from .youtube import get_service
    cfg = load_config(args.config_path)
    svc = get_service(cfg.youtube, interactive=True)
    ch = svc.channels().list(part="snippet", mine=True).execute().get("items", [])
    print("Autenditud kanal:", ch[0]["snippet"]["title"] if ch else "(kanal puudub)")
    return 0


def _pipeline(args):
    from .pipeline import Pipeline
    return Pipeline(load_config(args.config_path))


def cmd_run(args) -> int:
    cfg = load_config(args.config_path)
    with run_lock(cfg.work_dir / "loengud.lock") as ok:
        if not ok:
            print("Teine käivitus juba töötab – lõpetan.")
            return 0
        from .pipeline import Pipeline
        p = Pipeline(cfg)
        problems = p.run(only=Path(args.only).expanduser() if args.only else None, dry_run=args.dry_run)
    print(f"\nValmis. Probleeme: {problems}" + (" – vaata `loengud status`" if problems else ""))
    return 1 if problems and not args.dry_run else 0


def cmd_status(args) -> int:
    p = _pipeline(args)
    recs = p.state.recordings
    if not recs:
        print("Olekus pole veel ühtegi salvestust. Käivita `loengud scan`.")
        return 0
    for key, r in sorted(recs.items(), key=lambda kv: kv[1].get("start", "")):
        if not args.all and r.get("stage") in ("done", "ignored"):
            continue
        flag = "✗" if r.get("problem") else ("✓" if r.get("stage") == "done" else "…")
        where = f"{Path(r['repo']).name}/{r['seminar_dir']}" if r.get("repo") else "—"
        vid = f" https://youtu.be/{r['video_id']}" if r.get("video_id") else ""
        print(f"{flag} {r.get('start', '')[:16]}  {r.get('stage'):<16} {where}{vid}\n    {key}")
        if r.get("problem"):
            print(f"    probleem ({r.get('problem_kind')}): {r['problem']}")
        if r.get("stage") == "awaiting_upload":
            print(f"    lae Studiosse üles: {r.get('staged')}")
    return 0


def cmd_assign(args) -> int:
    p = _pipeline(args)
    p.assign(Path(args.recording).expanduser(), Path(args.repo).expanduser(), args.seminar, args.part)
    print("Määratud. Käivita `loengud run`.")
    return 0


def cmd_attach(args) -> int:
    _pipeline(args).attach_video(Path(args.recording).expanduser(), args.video)
    print("Seotud. `loengud run --only …` lisab sellele videole subtiitrid ja esitusloendid.")
    return 0


def cmd_timetable(args) -> int:
    from . import tunniplaan
    cfg = load_config(args.config_path)
    tt = cfg.timetable
    if not (tt.teacher_id and tt.semester_start and tt.semester_end):
        print("Seadista config.yaml → timetable (teacher_id, semester_start, semester_end).")
        return 2
    sessions = tunniplaan.fetch(tt.teacher_id, tt.semester_start, tt.semester_end, tt.url)
    for s in sessions:
        print(f"{s.date} {s.start}-{s.end}  {s.code:<11} #{tunniplaan.ordinal(sessions, s):<2} {s.subject}  [{s.group}]")
    return 0


def cmd_ignore(args) -> int:
    _pipeline(args).ignore(Path(args.recording).expanduser())
    print("Ignoreeritud.")
    return 0


def cmd_retry(args) -> int:
    _pipeline(args).retry(Path(args.recording).expanduser(), args.from_stage)
    print(f"Etapp seatud: {args.from_stage}. Käivita `loengud run`.")
    return 0


def cmd_subs(args) -> int:
    from . import subtitles
    words, speakers = subtitles.load_words(Path(args.result_json))
    cues = subtitles.segment(words)
    out = Path(args.out or Path(args.result_json).with_suffix(""))
    out.parent.mkdir(parents=True, exist_ok=True)
    Path(f"{out}.et.srt").write_text(subtitles.to_srt(cues), encoding="utf-8")
    Path(f"{out}.et.vtt").write_text(subtitles.to_vtt(cues), encoding="utf-8")
    Path(f"{out}.md").write_text(subtitles.to_markdown(words, speakers, {"title": args.title or "Transkriptsioon"}),
                                 encoding="utf-8")
    print(f"{len(cues)} subtiitrit → {out}.et.srt / .et.vtt / .md")
    return 0


def cmd_doctor(args) -> int:
    ok = True

    def check(label, cond, hint=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"{'✓' if cond else '✗'} {label}" + ("" if cond else f"  → {hint}"))

    for tool, hint in [("ffmpeg", "brew install ffmpeg"), ("ffprobe", "brew install ffmpeg"),
                       ("git", "xcode-select --install"), ("java", "brew install openjdk@17"),
                       ("docker", "Docker Desktop / OrbStack")]:
        check(tool, shutil.which(tool), hint)
    try:
        cfg = load_config(args.config_path)
    except Exception as e:  # noqa: BLE001
        check("seadistus", False, str(e))
        return 1
    if cfg.asr.engine == "whispercpp":
        check(f"whisper.cpp ({cfg.asr.whisper_bin})", shutil.which(cfg.asr.whisper_bin), "brew install whisper-cpp")
        check(f"Whisperi mudel: {Path(cfg.asr.whisper_model).expanduser()}", Path(cfg.asr.whisper_model).expanduser().exists(),
              "vt README → whisper.cpp (TalTechNLP/whisper-large-v3-turbo-et-verbatim-2604 ggml)")
    else:
        check(f"nextflow ({cfg.asr.nextflow_bin})", shutil.which(cfg.asr.nextflow_bin) or Path(cfg.asr.nextflow_bin).expanduser().exists(),
              "curl -s https://get.nextflow.io | bash && mv nextflow ~/.local/bin/")
        pl = Path(cfg.asr.pipeline).expanduser()
        check(f"est-asr-pipeline: {pl}", pl.exists() or "/" in cfg.asr.pipeline and not cfg.asr.pipeline.startswith(("~", "/")),
              "git clone https://github.com/taltechnlp/est-asr-pipeline ~/tools/est-asr-pipeline")
        if shutil.which("docker"):
            r = subprocess.run(["docker", "image", "inspect", "alumae/est-asr-pipeline:0.1.4"], capture_output=True)
            check("Docker pilt alumae/est-asr-pipeline:0.1.4", r.returncode == 0,
                  "docker pull --platform linux/amd64 alumae/est-asr-pipeline:0.1.4")
        if sys.platform == "darwin":
            arm = subprocess.run(["uname", "-m"], capture_output=True, text=True).stdout.strip() == "arm64"
            if arm:
                check("Apple Silicon: asr.docker_run_options sisaldab --platform linux/amd64",
                      cfg.asr.docker_run_options and "linux/amd64" in cfg.asr.docker_run_options,
                      'asr.docker_run_options: "--platform linux/amd64 --memory=10g"')
    for d in cfg.source.recordings_dirs:
        check(f"salvestuste kaust: {d}", d.exists(), "kontrolli OneDrive'i sünki ja tee nime")
    for r in cfg.repos:
        check(f"repo: {r}", (r / ".loengud.yaml").exists(), f"loengud init --repo {r}")
    check("YouTube OAuth client secret", cfg.youtube.client_secrets.exists(), "vt README samm 3")
    check("YouTube token", cfg.youtube.token.exists(), "loengud auth")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="loengud", description="Teams-salvestus → TalTech ASR → YouTube + loengurepo")
    ap.add_argument("--config", dest="config_path", type=Path, default=None, help="seadistusfail")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="loo seadistusmall (ja --repo korral .loengud.yaml)")
    s.add_argument("--config", dest="config", default=None)
    s.add_argument("--repo")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_init)

    sub.add_parser("doctor", help="kontrolli keskkonda").set_defaults(fn=cmd_doctor)
    sub.add_parser("auth", help="logi YouTube'i sisse (OAuth)").set_defaults(fn=cmd_auth)

    s = sub.add_parser("scan", help="leia salvestused ja näita sobitust (ei muuda midagi)")
    s.set_defaults(fn=cmd_run, dry_run=True, only=None)

    s = sub.add_parser("run", help="töötle kõik ootel salvestused")
    s.add_argument("--only", help="ainult see salvestusfail")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("status", help="salvestuste olek")
    s.add_argument("--all", action="store_true", help="näita ka valmis/ignoreeritud")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("assign", help="määra salvestus käsitsi seminarile")
    s.add_argument("recording")
    s.add_argument("--repo", required=True)
    s.add_argument("--seminar", required=True, help="seminari kaust .loengud.yaml-ist, nt seminarid/04-css-grid")
    s.add_argument("--part", type=int)
    s.set_defaults(fn=cmd_assign)

    s = sub.add_parser("attach", help="seo salvestus juba YouTube'is oleva videoga (subtiitrid + esitusloendid)")
    s.add_argument("recording")
    s.add_argument("--video", required=True, help="video ID või URL")
    s.set_defaults(fn=cmd_attach)

    sub.add_parser("tunniplaan", help="näita õppejõu tunniplaani ja seminaride numbreid").set_defaults(fn=cmd_timetable)

    s = sub.add_parser("ignore", help="jäta salvestus vahele")
    s.add_argument("recording")
    s.set_defaults(fn=cmd_ignore)

    s = sub.add_parser("retry", help="kerista etapp tagasi (nt pärast käsitsi parandust)")
    s.add_argument("recording")
    s.add_argument("--from", dest="from_stage", required=True,
                   help="viimane LÕPETATUD etapp: matched|transcribed|committed|uploaded|captioned")
    s.set_defaults(fn=cmd_retry)

    s = sub.add_parser("subs", help="teisenda olemasolev result.json → SRT/VTT/MD")
    s.add_argument("result_json")
    s.add_argument("--out")
    s.add_argument("--title")
    s.set_defaults(fn=cmd_subs)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except (FileNotFoundError, KeyError, ValueError) as e:
        print(f"Viga: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
