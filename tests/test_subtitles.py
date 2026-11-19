import re

from loengud import subtitles
from conftest import make_result


def test_load_words_uses_punctuated_form(result_json):
    words, speakers = subtitles.load_words(result_json)
    assert words[0].text == "Tere"
    assert words[3].text == "seminari."
    assert set(speakers) == {"S1", "S2"}


def test_cues_respect_line_and_char_limits(result_json):
    words, _ = subtitles.load_words(result_json)
    cues = subtitles.segment(words)
    assert len(cues) >= 4
    for c in cues:
        lines = c.text.split("\n")
        assert len(lines) <= 2
        assert all(len(line) <= 42 for line in lines), c.text
        assert c.end > c.start
        assert c.end - c.start <= 7.0 + 1e-6 or len(c.text) < 20
    # ajad on kasvavas järjekorras ega kattu
    for a, b in zip(cues, cues[1:]):
        assert a.end <= b.start + 1e-6


def test_turn_change_breaks_cue(result_json):
    words, _ = subtitles.load_words(result_json)
    cues = subtitles.segment(words)
    assert any(c.text.startswith("Kas kellelgi") for c in cues)


def test_srt_and_vtt_format(result_json):
    words, _ = subtitles.load_words(result_json)
    cues = subtitles.segment(words)
    srt = subtitles.to_srt(cues)
    assert srt.startswith("1\n00:00:00,000 --> ")
    assert re.search(r"\d\d:\d\d:\d\d,\d{3} --> \d\d:\d\d:\d\d,\d{3}", srt)
    vtt = subtitles.to_vtt(cues)
    assert vtt.startswith("WEBVTT")
    assert "00:00:00.000 --> " in vtt


def test_markdown_has_timestamps_speakers_and_video_links(result_json):
    words, speakers = subtitles.load_words(result_json)
    md = subtitles.to_markdown(words, speakers, {"title": "Seminar 4"}, video_id="abc123")
    assert md.startswith("---\ntitle: \"Seminar 4\"")
    assert "https://youtu.be/abc123?t=0" in md
    assert "**Kõneleja 1:**" in md and "**Kõneleja 2:**" in md


def test_long_monologue_split_into_paragraphs():
    sents = ["See on üks pikk lause loengust, mis kestab mõnda aega."] * 40
    data = make_result(sents, ["S1"] * 40)
    words, _ = subtitles.load_words(data)
    paras = subtitles.paragraphs(words)
    assert len(paras) > 1


def test_wrap_prefers_balanced_split():
    s = subtitles.wrap_lines("Täna räägime CSS Gridist ja sellest, kuidas paigutust planeerida", 42)
    a, b = s.split("\n")
    assert len(a) <= 42 and len(b) <= 42


def test_whispercpp_json_conversion():
    from loengud.asr import whisper_json_to_result
    wj = {"transcription": [
        {"offsets": {"from": 0, "to": 400}, "text": " Tere"},
        {"offsets": {"from": 400, "to": 900}, "text": " tulemast."},
        {"offsets": {"from": 900, "to": 1000}, "text": " [MUSIC]"},
        {"offsets": {"from": 5000, "to": 5500}, "text": " Alustame"},
        {"offsets": {"from": 5500, "to": 6000}, "text": " Gitiga."},
    ]}
    res = whisper_json_to_result(wj)
    words, _ = subtitles.load_words(res)
    assert [w.text for w in words] == ["Tere", "tulemast.", "Alustame", "Gitiga."]
    assert words[2].start == 5.0 and words[2].turn != words[1].turn
    cues = subtitles.segment(words)
    assert cues[0].text == "Tere tulemast."
