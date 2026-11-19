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
    cmd = [cfg.nextflow_bin, "run", target, "-resume"]  # katkestamisel jätkab valmis sammudest
    if extra_config:
        cmd += ["-c", str(extra_config)]
    if cfg.profile:
        cmd += ["-profile", cfg.profile]
    cmd += ["--in", str(wav), "--out_dir", str(out_dir) + "/"]
    cmd += [str(a) for a in cfg.extra_args]
    return cmd


def has_words(result_json: Path) -> bool:
    try:
        import json
        d = json.loads(result_json.read_text(encoding="utf-8"))
        return any(t.get("words") for s in d.get("sections", []) for t in (s.get("turns") or []))
    except Exception:
        return False


def transcribe(cfg: AsrConfig, wav: Path, job_dir: Path, log=print) -> Path:
    """Käivitab pipeline'i ja tagastab result.json tee. Juba olemasolevat (mittetühja) tulemust ei arvutata uuesti."""
    out_dir = job_dir / "result"
    result_json = out_dir / "result.json"
    if result_json.exists() and has_words(result_json):
        return result_json
    if result_json.exists():
        result_json.rename(out_dir / f"result.empty-{int(__import__('time').time())}.json")

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
    if not has_words(result_json):
        result_json.rename(out_dir / f"result.empty-{int(__import__('time').time())}.json")
        raise AsrError(
            "ASR andis tühja tulemuse (kõnet ei tuvastatud). Kontrolli: kas salvestusel on heli; "
            "Apple Silicon'is lülita keeletuvastus välja (asr.extra_args: --do_language_id false). "
            f"Nextflow'i töökaust jäeti alles: {run_dir / 'work'}")
    if not cfg.keep_work:
        shutil.rmtree(run_dir / "work", ignore_errors=True)
    return result_json


# --- whisper.cpp (TalTechNLP/whisper-large-v3-turbo-et-verbatim GGML) ---------------------------

_JUNK = {"i", "h", "hm", "mm", "eh"}


def _drop_loops(words: list[dict], max_n: int = 8, min_repeats: int = 3) -> list[dict]:
    """Eemalda Whisperi kordustsüklid: sama 1–8-sõnaline fraas ≥3 korda järjest → jäta üks alles."""
    norm = lambda w: w["word_with_punctuation"].lower().strip(".,!?;:…")  # noqa: E731
    out: list[dict] = []
    i, n = 0, len(words)
    while i < n:
        best = None
        for size in range(1, max_n + 1):
            if i + size * min_repeats > n:
                break
            pat = [norm(w) for w in words[i:i + size]]
            reps = 1
            while i + (reps + 1) * size <= n and [norm(w) for w in words[i + reps * size:i + (reps + 1) * size]] == pat:
                reps += 1
            if reps >= min_repeats and (best is None or size * reps > best[0] * best[1]):
                best = (size, reps)
        if best:
            size, reps = best
            keep = words[i:i + size]
            keep[-1] = dict(keep[-1], end=words[i + size * reps - 1]["end"])
            out.extend(keep)
            i += size * reps
        else:
            out.append(words[i])
            i += 1
    return out


def _spread_collapsed(words: list[dict], min_word: float = 0.12) -> None:
    """Whisper annab vahel kümnetele sõnadele sama ajatempli → jaota need ühtlaselt naabrite vahele."""
    i, n = 0, len(words)
    while i < n:
        j = i
        while j + 1 < n and abs(words[j + 1]["start"] - words[i]["start"]) < 1e-3:
            j += 1
        if j > i:  # sõnad i..j on sama algusega
            lo = words[i]["start"]
            hi = max(words[j]["end"], words[j + 1]["start"] if j + 1 < n else words[j]["end"])
            if hi - lo < (j - i + 1) * min_word:
                hi = lo + (j - i + 1) * min_word
            step = (hi - lo) / (j - i + 1)
            for k in range(i, j + 1):
                words[k]["start"] = round(lo + (k - i) * step, 3)
                words[k]["end"] = round(lo + (k - i + 1) * step, 3)
        i = j + 1


def whisper_json_to_result(wj: dict, new_turn_gap: float = 2.0) -> dict:
    """whisper.cpp JSON (-ml 1 -sow → üks sõna segmendi kohta) → est-asr result.json formaat."""
    words = []
    for seg in wj.get("transcription", []):
        text = (seg.get("text") or "").strip()
        if not text or text.startswith("[") or text.startswith("("):
            continue
        core = "".join(ch for ch in text if ch.isalnum())
        if not core or core.lower() in _JUNK:      # ainult kirjavahemärgid või üksik "i"
            continue
        off = seg.get("offsets") or {}
        start, end = off.get("from", 0) / 1000.0, off.get("to", 0) / 1000.0
        if end <= start:
            end = start + 0.2
        words.append({"word": text.strip(".,!?;:").lower(), "word_with_punctuation": text,
                      "start": round(start, 3), "end": round(end, 3)})
    words = _drop_loops(words)
    _spread_collapsed(words)
    turns, cur = [], []
    for w in words:
        if cur and w["start"] - cur[-1]["end"] > new_turn_gap:
            turns.append(cur)
            cur = []
        cur.append(w)
    if cur:
        turns.append(cur)
    tjs = [{"speaker": "S1", "start": t[0]["start"], "end": t[-1]["end"],
            "transcript": " ".join(w["word_with_punctuation"] for w in t), "words": t} for t in turns]
    end = tjs[-1]["end"] if tjs else 0
    return {"speakers": {"S1": {}}, "sections": [{"type": "speech", "start": 0, "end": end, "turns": tjs}]}


def transcribe_whispercpp(cfg: AsrConfig, wav: Path, job_dir: Path, log=print) -> Path:
    import json
    out_dir = job_dir / "result"
    result_json = out_dir / "result.json"
    if result_json.exists() and has_words(result_json):
        return result_json
    out_dir.mkdir(parents=True, exist_ok=True)
    model = Path(cfg.whisper_model).expanduser()
    if not model.exists():
        raise AsrError(f"Whisperi mudel puudub: {model} (vt README → whisper.cpp)")
    base = out_dir / "whisper"
    cmd = [cfg.whisper_bin, "-m", str(model), "-f", str(wav), "-l", "et", "-t", str(cfg.whisper_threads),
           "-ml", "1", "-sow", "-oj", "-of", str(base), "-pp"]
    if cfg.whisper_max_context is not None and cfg.whisper_max_context >= 0:
        cmd += ["-mc", str(cfg.whisper_max_context)]
    if cfg.whisper_vad_model:
        vad = Path(cfg.whisper_vad_model).expanduser()
        if vad.exists():
            cmd += ["--vad", "-vm", str(vad)]
        else:
            log(f"  HOIATUS: VAD-mudel puudub ({vad}) – jätkan ilma VAD-ita")
    cmd += [str(a) for a in cfg.whisper_extra_args]
    log("ASR (whisper.cpp): " + " ".join(cmd))
    with open(job_dir / "asr.log", "w", encoding="utf-8") as logf:
        try:
            r = subprocess.run(cmd, stdout=logf, stderr=subprocess.STDOUT, timeout=cfg.timeout_hours * 3600)
        except FileNotFoundError as e:
            raise AsrError(f"{cfg.whisper_bin} puudub (brew install whisper-cpp): {e}") from e
    wj_path = base.with_suffix(".json")
    if r.returncode != 0 or not wj_path.exists():
        tail = (job_dir / "asr.log").read_text(encoding="utf-8", errors="replace")[-1500:]
        raise AsrError(f"whisper.cpp ebaõnnestus (kood {r.returncode}). Logi lõpp:\n{tail}")
    result = whisper_json_to_result(json.loads(wj_path.read_text(encoding="utf-8", errors="replace")))
    result_json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    if not has_words(result_json):
        result_json.rename(out_dir / f"result.empty-{int(__import__('time').time())}.json")
        raise AsrError("whisper.cpp andis tühja tulemuse – kontrolli, kas salvestusel on heli.")
    return result_json
