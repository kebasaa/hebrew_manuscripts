"""Fidelity tests for British Library MS Sloane 273.

The Hebrew here is fully pointed, and the failure mode the previous extraction
had was silent: consonants in the right order but vowels decoded as the wrong
marks and attached to the wrong letters. Coverage checks alone cannot catch
that, so these tests pin the exact text and assert pointing invariants.

The golden fixture was produced by the corrected extractor and checked against
the printed pages rendered from the PDF.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import pytest
from lxml import etree

from pdf2osis.converter import convert_pdf
from pdf2osis.osis import OSIS_NS, VARIANTS, build_structured_osis
from pdf2osis.profiles import SLOANE_REV
from pdf2osis.sloane import extract_sloane, gematria
from pdf2osis.validate import STRICT_SCHEMA, validate_sloane_records

NS = {"osis": OSIS_NS}
ROOT = Path(__file__).resolve().parents[1]
PDF = SLOANE_REV.default_path(ROOT / "data" / "00_source_files")
EXPECTED = json.loads(
    (Path(__file__).with_name("fixtures") / "sloane237_expected.json").read_text(
        encoding="utf-8"
    )
)

pytestmark = pytest.mark.skipif(not PDF.is_file(), reason=f"missing {PDF}")


@pytest.fixture(scope="module")
def document():
    return extract_sloane(PDF, SLOANE_REV)


@pytest.fixture(scope="module")
def outputs(tmp_path_factory, document):
    # Every variant, not just the published ones: these tests are about what
    # the OSIS says, and the bare `hebrew` is what shows the apparatus really
    # is confined to the annotated variants.
    return {
        variant: build_structured_osis(document, SLOANE_REV, variant)
        for variant in VARIANTS
    }


def verse_ids(document):
    return [f"Rev.{r.chapter}.{r.verse}" for r in document.records]


def test_every_verse_matches_the_printed_page(document):
    actual = {f"Rev.{r.chapter}.{r.verse}": r.hebrew for r in document.records}
    assert actual == EXPECTED["verses"]


def test_coverage_includes_the_verse_the_old_extraction_dropped(document):
    ids = verse_ids(document)
    assert ids == [f"Rev.1.{n}" for n in range(1, 21)] + [
        f"Rev.2.{n}" for n in range(1, 14)
    ]
    # Revelation 1:18 sits below the old hardcoded body cutoff of y=555 and was
    # discarded, then re-ingested as footnote text.
    by_id = {f"Rev.{r.chapter}.{r.verse}": r for r in document.records}
    assert by_id["Rev.1.18"].hebrew.startswith("וְהָחָי וְהָיִיתִי מֵת")


def test_opening_verses_are_character_exact(document):
    by_id = {f"Rev.{r.chapter}.{r.verse}": r for r in document.records}
    assert by_id["Rev.1.1"].hebrew.startswith(
        "חֲזוֹן יְהוֹשֻׁעַ מָשִׁיחַ שֶׁנְּתָנוֹ הָאֱלֹהִים"
    )
    assert by_id["Rev.1.2"].hebrew.startswith(
        "אֲשֶׁר הֵעִיד הַדְּבַר הָאֱלֹהִים"
    )
    # Footnote 2 records that the sheva under the tsade is missing here, so the
    # transcription really does read הֻצרָךְ rather than הֻצְרָךְ.
    assert "הֻצרָךְ" in by_id["Rev.1.1"].hebrew


def test_no_shin_dot_is_attached_to_the_wrong_letter(document):
    joined = unicodedata.normalize(
        "NFD", "".join(r.hebrew for r in document.records)
    )
    shins = joined.count("ש")
    dots = joined.count("ׁ") + joined.count("ׂ")
    # The previous extraction produced 233 dots for 109 shins because the font's
    # ToUnicode map decoded hiriq and qubuts as a shin dot.
    assert dots <= shins, f"{dots} shin/sin dots for {shins} shins"
    base = ""
    for char in joined:
        if not unicodedata.combining(char):
            base = char
        elif char in ("ׁ", "ׂ"):
            # Canonical order can place a vowel between the shin and its dot,
            # so the base is the last non-combining character, not the previous.
            assert base == "ש", f"shin dot on {base!r}"


def test_pointing_is_well_formed(document):
    for record in document.records:
        stream = unicodedata.normalize("NFD", record.hebrew)
        assert not unicodedata.combining(stream[0]), record.hebrew[:30]
        for index, char in enumerate(stream):
            if unicodedata.combining(char):
                assert not stream[index - 1].isspace()
        assert unicodedata.normalize("NFC", record.hebrew) == record.hebrew


def test_verses_carry_no_latin_digits_or_brackets(document):
    for record in document.records:
        assert not re.search(r"[A-Za-z0-9\[\]]", record.hebrew), record.hebrew[:40]


def test_manuscript_numbering_is_recorded_with_its_disagreements(document):
    numbers = {
        f"Rev.{r.chapter}.{r.verse}": r.ms_number
        for r in document.records
        if r.ms_number is not None
    }
    assert numbers == {k: v for k, v in EXPECTED["ms_numbers"].items()}
    disagreements = {
        key for key, value in numbers.items() if value != int(key.split(".")[-1])
    }
    assert disagreements == {
        "Rev.1.9", "Rev.1.15", "Rev.1.16", "Rev.1.17", "Rev.2.8",
    }
    assert len(document.anomalies) >= len(disagreements)


def test_catchwords_are_kept_and_numerals_are_not(document):
    """A line break repeats the next word's first letter; that is text."""
    by_id = {f"Rev.{r.chapter}.{r.verse}": r for r in document.records}
    assert "וְסָפְדוּ ע עָלָיו" in by_id["Rev.1.7"].hebrew
    assert "אוֹתוֹ נ נָפַלְתִּי" in by_id["Rev.1.17"].hebrew
    # These are numerals, not catchwords, and belong in milestones.
    divisions = {
        f"Rev.{r.chapter}.{r.verse}": [m.number for m in r.ms_divisions]
        for r in document.records
        if r.ms_divisions
    }
    assert divisions == EXPECTED["ms_divisions"]
    for record in document.records:
        for token in record.hebrew.split():
            value = gematria(token.strip("-:."))
            if value is not None and len(token) <= 2:
                assert abs(value - int(record.verse)) > 3, token


def test_notes_are_anchored_where_their_markers_are_printed(document):
    assert set(document.notes) == {str(n) for n in range(1, 16)}
    anchors = {
        f"Rev.{r.chapter}.{r.verse}": sorted(
            {m.number for m in (*r.hebrew_markers, *r.english_markers)}, key=int
        )
        for r in document.records
        if r.hebrew_markers or r.english_markers
    }
    assert anchors == EXPECTED["note_anchors"]
    assert document.notes["2"] == "Sheva is missing in the manuscript."
    assert document.notes["8"] == "Should be הֵמָּה."
    # Note 1 belongs to the incipit, which is not part of any verse.
    incipit = next(p for p in document.passages if p.kind == "incipit")
    assert [m.number for m in incipit.markers] == ["1"]


def test_non_verse_manuscript_text_is_captured(document):
    kinds = {p.kind: p for p in document.passages}
    assert kinds["incipit"].hebrew == (
        "א חֲזוֹן יוֹחָנָן הַקֹּדֶשׁ הַמְּדַבֶּרְאֵל מְשֻׁלָּח וּמְבַשֵּׂר:"
    )
    assert kinds["gate"].hebrew == "הַשַּׁעַר שֵׁנִי"
    assert kinds["gate"].chapter == 2
    assert "Sloane 273" in kinds["titlePage"].english
    folios = [label for r in document.records for label in
              [f.label for f in r.folios]]
    folios = [f.label for f in kinds["incipit"].folios] + folios
    assert folios == ["1r", "1v", "2r", "2v", "3r", "3v", "4r", "4v"]


def test_records_pass_their_own_validation(document):
    assert validate_sloane_records(document, SLOANE_REV) == []


@pytest.mark.parametrize("variant", sorted(SLOANE_REV.output_names()))
def test_osis_validates_against_the_upstream_schema(outputs, variant):
    schema = etree.XMLSchema(etree.parse(str(STRICT_SCHEMA)))
    root = etree.fromstring(outputs[variant])
    assert schema.validate(root), schema.error_log


def test_osis_uses_balanced_verse_and_chapter_milestones(outputs, document):
    root = etree.fromstring(outputs["hebrew"])
    verses = root.xpath("//osis:verse", namespaces=NS)
    starts = [v.get("sID") for v in verses if v.get("sID")]
    ends = [v.get("eID") for v in verses if v.get("eID")]
    assert starts == ends == verse_ids(document)
    # Milestone form is all-or-nothing: no verse may be a container.
    assert not [v for v in verses if v.text]
    chapters = root.xpath("//osis:chapter", namespaces=NS)
    assert [c.get("sID") for c in chapters if c.get("sID")] == ["Rev.1", "Rev.2"]
    assert [c.get("eID") for c in chapters if c.get("eID")] == ["Rev.1", "Rev.2"]


def test_osis_carries_the_non_verse_structures(outputs):
    root = etree.fromstring(outputs["hebrew"])
    assert root.xpath(
        "//osis:div[@type='introduction']/osis:title/text()", namespaces=NS
    )[0].endswith("וּמְבַשֵּׂר:")
    assert root.xpath(
        "//osis:title[@type='chapter']/text()", namespaces=NS
    ) == ["הַשַּׁעַר שֵׁנִי"]
    assert root.xpath("//osis:milestone[@type='pb']/@n", namespaces=NS) == [
        "1r", "1v", "2r", "2v", "3r", "3v", "4r", "4v",
    ]
    assert root.xpath("//osis:milestone[@type='x-ms-verse']/@n", namespaces=NS) == [
        "8", "12",
    ]
    assert root.xpath("//osis:div[@type='titlePage']", namespaces=NS)


def test_notes_appear_only_in_the_annotated_variants(outputs):
    counts = {
        variant: len(
            etree.fromstring(payload).xpath("//osis:note", namespaces=NS)
        )
        for variant, payload in outputs.items()
    }
    assert counts["hebrew"] == 0
    assert counts["hebrew_commented"] + counts["translation"] == 15
    root = etree.fromstring(outputs["hebrew_commented"])
    note = root.xpath("//osis:note", namespaces=NS)[0]
    # `footnote` is not an OSIS 2.1.1 note type.
    assert note.get("type") == "explanation"
    assert note.get("osisRef") and note.get("osisID", "").count("!") == 1


def test_conversion_is_deterministic(tmp_path):
    first = convert_pdf(PDF, SLOANE_REV, tmp_path)
    payloads = {p: p.read_bytes() for p in first.output_paths.values()}
    convert_pdf(PDF, SLOANE_REV, tmp_path)
    assert {p: p.read_bytes() for p in first.output_paths.values()} == payloads
    # The bare Hebrew is built but not published: Gordon's translation covers
    # the same transcription, so the catalogue carries it once, not twice.
    assert set(first.output_paths) == {"hebrew_commented", "translation"}


def test_output_is_pretty_printed_one_verse_per_line(outputs):
    """Milestone form defeats lxml's pretty printer without an explicit pass."""
    for variant, payload in outputs.items():
        lines = payload.decode("utf-8").splitlines()
        starts = [line for line in lines if "<verse sID=" in line]
        assert len(starts) == 33, variant
        for line in starts:
            # A verse opens and closes on its own line, so no line may carry
            # two verse starts, and each start is matched on its own line.
            assert line.count("<verse sID=") == 1, variant
            assert "<verse eID=" in line, variant
        assert max(len(line) for line in lines) < 2000, variant


def test_header_carries_attributed_provenance(outputs):
    root = etree.fromstring(outputs["hebrew"])
    work = root.xpath("//osis:header/osis:work", namespaces=NS)[0]
    kinds = work.xpath("./osis:description/@type", namespaces=NS)
    assert {"x-contents", "x-provenance", "x-script", "x-editorial"} <= set(kinds)
    sources = work.xpath("./osis:source/text()", namespaces=NS)
    assert any("British Library" in source for source in sources)
    assert any("Gordon" in source for source in sources)
    # The shelfmark is the catalogue's, and the date is the catalogue's range
    # rather than the invented "ca. 1600" it replaced.
    shelfmark = work.xpath(
        "./osis:identifier[@type='x-shelfmark']/text()", namespaces=NS
    )
    assert shelfmark == ["British Library, Sloane MS 237"]
    date = work.xpath("./osis:date", namespaces=NS)[0]
    assert date.get("type") == "Gregorian"
    assert date.text == "between 1500 and 1699"


def _rights(output: bytes, kind: str) -> str:
    root = etree.fromstring(output)
    work = root.xpath("//osis:header/osis:work", namespaces=NS)[0]
    found = work.xpath(f"./osis:rights[@type='x-{kind}']/text()", namespaces=NS)
    return found[0] if found else ""


def test_copyright_is_absent_from_the_plain_hebrew_variant(outputs):
    # Nobody in particular is credited with the bare transcription — the
    # commentary is Gordon's, not the manuscript's — so this is empty rather
    # than missing: an element present and blank, not omitted.
    assert _rights(outputs["hebrew"], "copyright") == ""


def test_copyright_names_gordon_on_the_commented_and_translation_variants(outputs):
    for variant in ("hebrew_commented", "translation"):
        assert _rights(outputs[variant], "copyright") == "© 2017 by Nehemia Gordon"


def test_licence_defaults_to_cc_by_nc_sa_on_every_variant(outputs):
    # This edition states no reuse terms of its own, unlike the Cochin
    # editions or Gordon's Ebr. 530 work — so every variant gets the
    # repository's stated default, never left blank.
    for variant in SLOANE_REV.output_names():
        assert "CC BY-NC-SA 4.0" in _rights(outputs[variant], "license")
