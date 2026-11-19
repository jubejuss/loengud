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


def test_whispercpp_collapsed_timestamps_are_spread():
    from loengud.asr import whisper_json_to_result
    seg = [{"offsets": {"from": 1000, "to": 1000}, "text": f" sõna{i}"} for i in range(10)]
    seg.append({"offsets": {"from": 1000, "to": 3000}, "text": " lõpp."})
    seg.append({"offsets": {"from": 3100, "to": 3500}, "text": " Järgmine"})
    words, _ = subtitles.load_words(whisper_json_to_result({"transcription": seg}))
    starts = [w.start for w in words]
    assert starts == sorted(starts) and len(set(starts)) == len(starts)
    assert all(w.end > w.start for w in words)
    for c in subtitles.segment(words):
        assert c.end > c.start


def test_describe_parse_and_render():
    from loengud import describe
    raw = 'Siin on vastus:\n{"summary": "Teema X.", "chapters": [{"t": "0:05", "title": "Sissejuhatus"}, {"t": "4:57", "title": "AI"}, {"t": "4:59", "title": "liiga lähedal"}, {"t": "1:13:17", "title": "Riskid"}, {"t": "9:99:99", "title": "vale"}]}'
    d = describe.parse_response(raw, duration=5400)
    assert d["chapters"][0] == (0, "Algus")
    assert (297, "AI") in d["chapters"] and all(t != "liiga lähedal" for _, t in d["chapters"])
    text = describe.render(d, "Kursus, Seminar 4 (19.11.2026)", ["Materjalid: x", ""])
    assert "0:00 Algus" in text and "1:13:17 Riskid" in text and text.endswith("Materjalid: x")


def test_whisper_loop_removed():
    from loengud.asr import whisper_json_to_result
    phrase = ["kas", "sa", "oled", "võtnud,"]
    seg, t = [], 0
    for w in ["Okei,", "siis"] + phrase * 6 + ["Paari", "tagasi."]:
        seg.append({"offsets": {"from": t, "to": t + 300}, "text": " " + w}); t += 320
    words, _ = subtitles.load_words(whisper_json_to_result({"transcription": seg}))
    assert [w.text for w in words] == ["Okei,", "siis", "kas", "sa", "oled", "võtnud,", "Paari", "tagasi."]
    # tavaline kordus ("ja ja") jääb alles
    seg2 = [{"offsets": {"from": i * 300, "to": i * 300 + 250}, "text": " " + w} for i, w in enumerate(["ja", "ja", "nii."])]
    words2, _ = subtitles.load_words(whisper_json_to_result({"transcription": seg2}))
    assert [w.text for w in words2] == ["ja", "ja", "nii."]
