from pathlib import Path

from loengud.seminarlinks import render_block, seminar_md_path, update_file, upsert_block


def test_insert_after_h1_and_replace(tmp_path):
    md = tmp_path / "seminar.md"
    md.write_text("# Seminar 4: kvaliteet\n\nMeeskonna töövoog.\n\n## Eesmärk\n", encoding="utf-8")
    out = tmp_path / "salvestus"
    out.mkdir()
    (out / "transkriptsioon.md").write_text("x")
    assert update_file(md, [(1, "AAA", out / "transkriptsioon.md")])
    t = md.read_text()
    assert t.startswith("# Seminar 4: kvaliteet\n\n<!-- loengud:videod")
    assert "[YouTube](https://youtu.be/AAA) · [transkriptsioon](salvestus/transkriptsioon.md)" in t
    assert t.endswith("-->\n\nMeeskonna töövoog.\n\n## Eesmärk\n")
    # 2. osa lisandub: plokk asendatakse, mitte ei dubleerita
    assert update_file(md, [(2, "BBB", None), (1, "AAA", out / "transkriptsioon.md")])
    t2 = md.read_text()
    assert t2.count("<!-- /loengud:videod -->") == 1
    assert "[1. osa](https://youtu.be/AAA) · [2. osa](https://youtu.be/BBB)" in t2
    assert not update_file(md, [(1, "AAA", out / "transkriptsioon.md"), (2, "BBB", None)])


def test_no_heading_goes_to_top():
    block = render_block([(1, "X", None)], Path("/r/a.md"))
    assert upsert_block("Tekst\n", block) == block + "\nTekst\n"


def test_pattern_path(tmp_path):
    (tmp_path / "04-seminar.md").write_text("# 4\n")
    assert seminar_md_path(tmp_path, "salvestused/seminar_04", 4, "{n:02d}-seminar.md") == tmp_path / "04-seminar.md"
    assert seminar_md_path(tmp_path, "salvestused/seminar_04", 5, "{n:02d}-seminar.md") is None
