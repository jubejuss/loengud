"""est-asr result.json → SRT / WebVTT / Markdown transkriptsioon."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

SENT_END = (".", "!", "?", "…")


@dataclass
class Word:
    text: str
    start: float
    end: float
    speaker: str
    turn: int


@dataclass
class Cue:
    start: float
    end: float
    text: str  # võib sisaldada reavahetust


def load_words(result_json: Path | dict) -> tuple[list[Word], dict]:
    data = json.loads(Path(result_json).read_text(encoding="utf-8")) if not isinstance(result_json, dict) else result_json
    words: list[Word] = []
    turn_idx = 0
    for section in data.get("sections", []):
        if section.get("type") != "speech":
            continue
        for turn in section.get("turns", []) or []:
            spk = str(turn.get("speaker", ""))
            for w in turn.get("words", []) or []:
                text = str(w.get("word_with_punctuation", w.get("word", ""))).strip()
                if not text or text.startswith("<") or text.startswith("["):
                    continue
                words.append(Word(text, float(w["start"]), float(w["end"]), spk, turn_idx))
            turn_idx += 1
    words.sort(key=lambda w: w.start)
    return words, data.get("speakers", {}) or {}


def wrap_lines(text: str, max_line: int) -> str:
    if len(text) <= max_line:
        return text
    # parim tasakaalustatud murdekoht kahe rea vahel
    best, best_score = None, None
    for i, ch in enumerate(text):
        if ch != " ":
            continue
        a, b = text[:i], text[i + 1:]
        if len(a) > max_line or len(b) > max_line:
            continue
        score = abs(len(a) - len(b))
        if a.endswith((",", ".", "?", "!", ":", ";")):
            score -= 8  # eelista murdu kirjavahemärgi järel
        if best_score is None or score < best_score:
            best, best_score = i, score
    if best is None:
        return text  # ei mahu kahele reale – segmenteerija ei tohiks siia jõuda
    return text[:best] + "\n" + text[best + 1:]


def segment(words: list[Word], max_line: int = 42, max_lines: int = 2, max_duration: float = 7.0,
            min_duration: float = 1.0, max_gap: float = 1.2, min_chars_for_sentence_break: int = 18) -> list[Cue]:
    max_chars = max_line * max_lines
    cues: list[Cue] = []
    cur: list[Word] = []

    def flush():
        if cur:
            cues.append(Cue(cur[0].start, cur[-1].end, " ".join(w.text for w in cur)))
            cur.clear()

    for w in words:
        if cur:
            text_len = len(" ".join(x.text for x in cur)) + 1 + len(w.text)
            gap = w.start - cur[-1].end
            if (text_len > max_chars or w.end - cur[0].start > max_duration
                    or gap > max_gap or w.turn != cur[-1].turn):
                flush()
        cur.append(w)
        cur_len = len(" ".join(x.text for x in cur))
        if w.text.endswith(SENT_END) and cur_len >= min_chars_for_sentence_break:
            flush()
        elif w.text.endswith((",", ";", ":")) and cur_len >= max_chars * 0.6:
            flush()
    flush()

    # liiga lühikese ekraaniaja pikendamine (mitte üle järgmise algust)
    for i, c in enumerate(cues):
        nxt = cues[i + 1].start if i + 1 < len(cues) else c.end + min_duration
        if c.end - c.start < min_duration:
            c.end = min(c.start + min_duration, max(nxt - 0.05, c.end))
        c.text = wrap_lines(c.text, max_line)
    return cues


def _ts(t: float, sep: str) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def to_srt(cues: list[Cue]) -> str:
    out = []
    for i, c in enumerate(cues, 1):
        out.append(f"{i}\n{_ts(c.start, ',')} --> {_ts(c.end, ',')}\n{c.text}\n")
    return "\n".join(out)


def to_vtt(cues: list[Cue]) -> str:
    out = ["WEBVTT", "Language: et", ""]
    for c in cues:
        out.append(f"{_ts(c.start, '.')} --> {_ts(c.end, '.')}\n{c.text}\n")
    return "\n".join(out)


def hms(t: float) -> str:
    t = int(t)
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


def paragraphs(words: list[Word], max_seconds: float = 75.0) -> list[tuple[float, str, str]]:
    """(algus, kõneleja, tekst) lõigud: uus lõik kõnelejavahetusel või ~75 s järel lause lõpus."""
    paras: list[tuple[float, str, str]] = []
    cur: list[Word] = []
    for w in words:
        if cur and (w.speaker != cur[-1].speaker or w.start - cur[-1].end > 4.0):
            paras.append((cur[0].start, cur[0].speaker, " ".join(x.text for x in cur)))
            cur = []
        cur.append(w)
        if w.text.endswith(SENT_END) and w.end - cur[0].start >= max_seconds:
            paras.append((cur[0].start, cur[0].speaker, " ".join(x.text for x in cur)))
            cur = []
    if cur:
        paras.append((cur[0].start, cur[0].speaker, " ".join(x.text for x in cur)))
    return paras


def to_markdown(words: list[Word], speakers: dict, meta: dict, video_id: str | None = None) -> str:
    fm = ["---"]
    for k, v in meta.items():
        if v is None or v == "":
            continue
        sval = str(v).replace('"', '\\"')
        fm.append(f'{k}: "{sval}"')
    if video_id:
        fm.append(f'video: "https://youtu.be/{video_id}"')
    fm.append("---\n")
    body = [f"# {meta.get('title', 'Transkriptsioon')}\n"]
    if video_id:
        body.append(f"Video: https://youtu.be/{video_id}\n")
    body.append("> Automaatne transkriptsioon (TalTech est-asr, tekstiks.ee mootor). "
                "Võib sisaldada tuvastusvigu; ajatemplid viitavad salvestuse algusele.\n")

    multi_speaker = len({w.speaker for w in words}) > 1
    labels: dict[str, str] = {}
    for start, spk, text in paragraphs(words):
        stamp = hms(start)
        stamp_md = f"[**{stamp}**](https://youtu.be/{video_id}?t={int(start)})" if video_id else f"**{stamp}**"
        prefix = ""
        if multi_speaker:
            if spk not in labels:
                name = (speakers.get(spk) or {}).get("name")
                labels[spk] = name or f"Kõneleja {len(labels) + 1}"
            prefix = f"**{labels[spk]}:** "
        body.append(f"{stamp_md} {prefix}{text}\n")
    return "\n".join(fm) + "\n".join(body)
