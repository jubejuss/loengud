"""TalTechi est-asr-pipeline (sama mootor, mis tekstiks.ee) käivitamine."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

from .config import AsrConfig


class AsrError(RuntimeError):
    pass


def recording_id(path: Path, size: int) -> str:
    return hashlib.sha1(f"{path.name}:{size}".encode()).hexdigest()[:12]


def extract_audio(video: Path, out_wav: Path) -> Path:
    """16 kHz mono WAV ASCII-nimega – väldib Nextflow'i probleeme tühikute ja täpitähtedega."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    if out_wav.exists() and out_wav.stat().st_size > 0:
        return out_wav
    tmp = out_wav.with_suffix(".part.wav")
    cmd = ["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(video),
           "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(tmp)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise AsrError(f"ffmpeg ebaõnnestus: {r.stderr.strip()[-500:]}")
    tmp.rename(out_wav)
    return out_wav


def media_duration(path: Path) -> float | None:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=60, check=True,
        ).stdout.strip()
        return float(out)
    except Exception:
        return None


def build_command(cfg: AsrConfig, wav: Path, out_dir: Path, extra_config: Path | None) -> list[str]:
    pipeline = cfg.pipeline
    if pipeline.startswith(("~", "/", ".")):
        local = Path(pipeline).expanduser()
        if not (local / "transcribe.nf").exists():
            raise AsrError(f"{local}/transcribe.nf puudub – klooni taltechnlp/est-asr-pipeline sinna.")
        target = str(local / "transcribe.nf")
    else:
        target = pipeline  # GitHubi nimi, nt "taltechnlp/est-asr-pipeline"
    cmd = [cfg.nextflow_bin, "run", target]
    if extra_config:
        cmd += ["-c", str(extra_config)]
    if cfg.profile:
        cmd += ["-profile", cfg.profile]
    cmd += ["--in", str(wav), "--out_dir", str(out_dir) + "/"]
    cmd += [str(a) for a in cfg.extra_args]
    return cmd


def transcribe(cfg: AsrConfig, wav: Path, job_dir: Path, log=print) -> Path:
    """Käivitab pipeline'i ja tagastab result.json tee. Juba olemasolevat tulemust ei arvutata uuesti."""
    out_dir = job_dir / "result"
    result_json = out_dir / "result.json"
    if result_json.exists() and result_json.stat().st_size > 0:
        return result_json

    run_dir = job_dir / "nf-run"
    run_dir.mkdir(parents=True, exist_ok=True)
    extra_config = None
    if cfg.docker_run_options:
        extra_config = run_dir / "loengud.config"
        opts = cfg.docker_run_options.replace("'", "")
        extra_config.write_text(f"docker.enabled = true\ndocker.runOptions = '{opts}'\n", encoding="utf-8")

    cmd = build_command(cfg, wav, out_dir, extra_config)
    log("ASR: " + " ".join(cmd))
    with open(job_dir / "asr.log", "w", encoding="utf-8") as logf:
        try:
            r = subprocess.run(cmd, cwd=run_dir, stdout=logf, stderr=subprocess.STDOUT,
                               timeout=cfg.timeout_hours * 3600)
        except FileNotFoundError as e:
            raise AsrError(f"{cfg.nextflow_bin} puudub (paigalda Nextflow + Java): {e}") from e
        except subprocess.TimeoutExpired as e:
            raise AsrError(f"ASR ületas ajapiiri {cfg.timeout_hours} h") from e
    if r.returncode != 0 or not result_json.exists():
        tail = (job_dir / "asr.log").read_text(encoding="utf-8", errors="replace")[-1500:]
        raise AsrError(f"ASR ebaõnnestus (kood {r.returncode}). Logi lõpp:\n{tail}")
    if not cfg.keep_work:
        shutil.rmtree(run_dir / "work", ignore_errors=True)
    return result_json
