"""Fidelity tests for Vatican, Vat. ebr. 530 (Luke and John).

This manuscript is heavily pointed and its PDF's embedded fonts carry no cmap
table at all, so text is rebuilt from ``rawdict`` glyph geometry. The previous
notebook reversed whole lines, which put every combining mark before its base
and left 42 raw presentation forms in the committed output — a failure coverage
checks cannot see. These tests pin the exact text and the pointing invariants.

Ground truth for the opening verses was read from the rendered pages.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import pytest
from lxml import etree

from pdf2osis.converter import convert_pdf
from pdf2osis.ebr530 import extract_ebr530
from pdf2osis.glyphs import is_syriac
from pdf2osis.osis import OSIS_NS, build_structured_osis
from pdf2osis.profiles import EBR530_JOHN, EBR530_LUKE
from pdf2osis.validate import STRICT_SCHEMA, validate_sloane_records

NS = {"osis": OSIS_NS}
ROOT = Path(__file__).resolve().parents[1]
PDF = EBR530_LUKE.default_path(ROOT / "data" / "00_source_files")
EXPECTED = json.loads(
    (Path(__file__).with_name("fixtures") / "ebr530_expected.json").read_text(
        encoding="utf-8"
    )
)
PROFILES = {"Luke": EBR530_LUKE, "John": EBR530_JOHN}

pytestmark = pytest.mark.skipif(not PDF.is_file(), reason=f"missing {PDF}")


@pytest.fixture(scope="module")
def documents():
    return {
        book: extract_ebr530(PDF, profile) for book, profile in PROFILES.items()
    }


@pytest.fixture(scope="module")
def outputs(documents):
    return {
        book: {
            variant: build_structured_osis(documents[book], profile, variant)
            for variant in profile.output_names()
        }
        for book, profile in PROFILES.items()
    }


@pytest.mark.parametrize("book", sorted(PROFILES))
def test_every_verse_matches_the_printed_page(documents, book):
    actual = {
        f"{book}.1.{r.verse}": r.hebrew for r in documents[book].records
    }
    assert actual == EXPECTED[book]["verses"]


def test_coverage_is_the_fragment_s_own_extent(documents):
    assert [r.verse for r in documents["Luke"].records] == [
        str(n) for n in range(1, 36)
    ]
    assert [r.verse for r in documents["John"].records] == [
        str(n) for n in range(1, 14)
    ]


def test_opening_verses_are_character_exact(documents):
    luke = {r.verse: r.hebrew for r in documents["Luke"].records}
    john = {r.verse: r.hebrew for r in documents["John"].records}
    assert luke["1"] == (
        "בִהְיוֹת כִּי הוּשָׂמוּ רַבִּים לְחַבֵר סִיפוּר הַדְּבָרִים אֲשֶר "
        "בֵינֵינוּ הֵם נֶאֱמָנִים"
    )
    assert john["1"].startswith(
        "בְרֵאשִׁית הָיָה הַדַבָר וְהַדַבָר הַיָה אֵצֶל הַאֱלֹהִים"
    )
    # הָיָה twice over: both qamatsin fall in the half-point overlap between the
    # he and the yod, which only the one-mark-per-letter rule separates.
    assert "וְהַאֱלֹהִים הוּא הָיָה הַדַבָר" in john["1"]


@pytest.mark.parametrize("book", sorted(PROFILES))
def test_no_presentation_forms_or_unmapped_glyphs_survive(documents, book):
    joined = "".join(r.hebrew for r in documents[book].records)
    joined += "".join(documents[book].notes.values())
    # U+FB20 needs compatibility decomposition, not canonical; the committed
    # output had 42 of them. U+02C2–4 are unmapped Identity-H CIDs.
    assert "ﬠ" not in joined
    assert not [char for char in joined if "יִ" <= char <= "ﭏ"]
    assert not [char for char in joined if "˂" <= char <= "˄"]
    assert "�" not in joined


@pytest.mark.parametrize("book", sorted(PROFILES))
def test_pointing_is_well_formed(documents, book):
    joined = unicodedata.normalize(
        "NFD", "".join(r.hebrew for r in documents[book].records)
    )
    shins = joined.count("ש")
    dots = joined.count("ׁ") + joined.count("ׂ")
    assert dots <= shins, f"{dots} shin/sin dots for {shins} shins"
    base = ""
    for char in joined:
        if not unicodedata.combining(char):
            base = char
        elif char in ("ׁ", "ׂ"):
            assert base == "ש", f"shin dot on {base!r}"
    for record in documents[book].records:
        stream = unicodedata.normalize("NFD", record.hebrew)
        assert not unicodedata.combining(stream[0]), record.hebrew[:30]
        assert unicodedata.normalize("NFC", record.hebrew) == record.hebrew


@pytest.mark.parametrize("book", sorted(PROFILES))
def test_verses_carry_no_latin_syriac_or_digits(documents, book):
    for record in documents[book].records:
        # Square brackets are kept: the editor uses them to supply letters a
        # scribe scratched out, as in Luke 1:8's אדנ[י]. Parentheses and digits
        # are verse and note markers and must not survive into the text.
        assert not re.search(r"[A-Za-z0-9()]", record.hebrew), record.hebrew[:40]
        assert not [c for c in record.hebrew if is_syriac(c)]
        assert record.english, f"{book} 1:{record.verse} has no translation"


def test_editorial_restorations_are_preserved(documents):
    """The editor brackets letters supplied where the scribe erased."""
    by_verse = {r.verse: r for r in documents["Luke"].records}
    assert "אדנ[י]" in by_verse["8"].hebrew
    assert documents["Luke"].notes["8"].startswith(
        "The scribe apparently scratched out Adonai"
    )


def test_notes_are_anchored_where_their_markers_are_printed(documents):
    for book, document in documents.items():
        anchors = {
            f"{book}.1.{r.verse}": sorted(
                {m.number for m in (*r.hebrew_markers, *r.english_markers)},
                key=int,
            )
            for r in document.records
            if r.hebrew_markers or r.english_markers
        }
        assert anchors == EXPECTED[book]["note_anchors"]
    luke = documents["Luke"]
    assert luke.notes["1"] == "The manuscript often omits Dagesh where expected."
    # The editor's own doubling, kept verbatim.
    assert "interchangeably interchangeably" in luke.notes["2"]
    assert luke.notes["14"].startswith("A Tsere (rather than a Patach) us expected")
    # Note 7 annotates בַכֹּהֵן, which this edition sets at the end of verse 7,
    # not verse 8 as the notebook's hand-audited table claimed.
    by_verse = {r.verse: r for r in luke.records}
    assert by_verse["7"].hebrew.endswith("וַיְהִי בַכֹּהֵן")
    assert "7" in {m.number for m in by_verse["7"].hebrew_markers}


def test_non_verse_material_is_captured(documents):
    kinds = {p.kind: p for p in documents["Luke"].passages}
    assert kinds["book-title"].hebrew == (
        "הַבְּשׂוֹרָה הַקְדוֹשָׁה שֶל יֵשוּעַ הַמַּשִׁיחַ כְּפִי לוּקָה"
    )
    # Notes 1 and 2 annotate the heading, and note 6 the chapter heading, so
    # none of the three belongs to a verse.
    assert [m.number for m in kinds["book-title"].markers] == ["1", "2"]
    assert kinds["chapter-title"].hebrew == "פֶרֶק רִאשׂוֹן"
    assert [m.number for m in kinds["chapter-title"].markers] == ["6"]
    assert "Vatican" in kinds["titlePage"].english

    john = {p.kind: p for p in documents["John"].passages}
    assert john["book-title"].hebrew == (
        "הַבְּשׂוֹרָה הַקְּדוֹשָׁה שֶׁל יֵשׁוּעַ הַמַּשִׁיחַ כְּפִי יוֹחָנָן"
    )


def test_translation_column_disagreement_is_reported(documents):
    """The source prints (3) twice on page 2; the second should read (4)."""
    assert any(
        "prints (3)" in anomaly for anomaly in documents["Luke"].anomalies
    )
    # The Hebrew column is authoritative, so no verse loses its translation.
    assert all(r.english for r in documents["Luke"].records)


def test_records_pass_validation(documents):
    for book, profile in PROFILES.items():
        assert validate_sloane_records(documents[book], profile) == []


@pytest.mark.parametrize("book", sorted(PROFILES))
def test_osis_validates_against_the_upstream_schema(outputs, book):
    schema = etree.XMLSchema(etree.parse(str(STRICT_SCHEMA)))
    for variant, payload in outputs[book].items():
        root = etree.fromstring(payload)
        assert schema.validate(root), (book, variant, schema.error_log)


@pytest.mark.parametrize("book", sorted(PROFILES))
def test_output_is_pretty_printed_one_verse_per_line(outputs, book):
    expected = 35 if book == "Luke" else 13
    for variant, payload in outputs[book].items():
        lines = payload.decode("utf-8").splitlines()
        starts = [line for line in lines if "<verse sID=" in line]
        assert len(starts) == expected, (book, variant)
        for line in starts:
            assert line.count("<verse sID=") == 1
            assert "<verse eID=" in line
        assert max(len(line) for line in lines) < 2000, (book, variant)


@pytest.mark.parametrize("book", sorted(PROFILES))
def test_osis_carries_the_non_verse_structures(outputs, book):
    root = etree.fromstring(outputs[book]["hebrew"])
    assert root.xpath("//osis:div[@type='introduction']", namespaces=NS)
    assert root.xpath("//osis:title[@type='chapter']", namespaces=NS)
    folios = root.xpath("//osis:milestone[@type='pb']/@n", namespaces=NS)
    assert folios == (["1r", "1v", "2r"] if book == "Luke" else ["2v"])
    verses = root.xpath("//osis:verse", namespaces=NS)
    starts = [v.get("sID") for v in verses if v.get("sID")]
    assert starts == [v.get("eID") for v in verses if v.get("eID")]


def test_header_carries_attributed_provenance(outputs):
    root = etree.fromstring(outputs["Luke"]["hebrew"])
    work = root.xpath("//osis:header/osis:work", namespaces=NS)[0]
    kinds = work.xpath("./osis:description/@type", namespaces=NS)
    assert {"x-contents", "x-provenance", "x-script", "x-editorial"} <= set(kinds)
    sources = work.xpath("./osis:source/text()", namespaces=NS)
    assert any("DigiVatLib" in source for source in sources)
    assert any("Gordon" in source for source in sources)
    shelfmark = work.xpath(
        "./osis:identifier[@type='x-shelfmark']/text()", namespaces=NS
    )
    assert shelfmark and "Vat. ebr. 530" in shelfmark[0]


def _rights(output: bytes, kind: str) -> str:
    root = etree.fromstring(output)
    work = root.xpath("//osis:header/osis:work", namespaces=NS)[0]
    found = work.xpath(f"./osis:rights[@type='x-{kind}']/text()", namespaces=NS)
    return found[0] if found else ""


def test_copyright_is_absent_from_the_plain_hebrew_variant(outputs):
    for book in PROFILES:
        assert _rights(outputs[book]["hebrew"], "copyright") == ""


def test_copyright_names_gordon_on_the_commented_and_translation_variants(outputs):
    for book in PROFILES:
        for variant in ("hebrew_commented", "translation"):
            assert _rights(outputs[book][variant], "copyright") == "© 2018 Nehemia Gordon."


def test_licence_states_all_rights_reserved_on_every_variant(outputs):
    # Gordon states this explicitly for Luke and John — the repository's own
    # CC BY-NC-SA default must never override a position he actually took.
    for book, profile in PROFILES.items():
        for variant in profile.output_names():
            assert _rights(outputs[book][variant], "license") == "All rights reserved."


def test_conversion_is_deterministic(tmp_path):
    first = convert_pdf(PDF, EBR530_LUKE, tmp_path)
    payloads = {p: p.read_bytes() for p in first.output_paths.values()}
    convert_pdf(PDF, EBR530_LUKE, tmp_path)
    assert {p: p.read_bytes() for p in first.output_paths.values()} == payloads
