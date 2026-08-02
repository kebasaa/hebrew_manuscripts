"""Fidelity tests for the Bible Society in Israel's modern Hebrew NT.

Like Delitzsch, this is a whole-Testament source producing one multi-book
file rather than a PDF. Unlike Delitzsch, there is no module to read — the
text is scraped chapter by chapter from a third-party mirror
(`pdf2osis.bsi_hnt`) into a local JSON cache, and these tests read that
cache. They skip if it is not present locally rather than failing, and never
touch the network themselves.

Ground truth for the spot-checked verses is the well-known text of each
passage.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from pdf2osis.bsi_hnt import extract_bsi_nt
from pdf2osis.converter import convert_bsi_nt
from pdf2osis.osis import OSIS_NS, build_multibook_osis
from pdf2osis.profiles import BSI_HNT
from pdf2osis.validate import STRICT_SCHEMA, validate_multibook_records

NS = {"osis": OSIS_NS}
ROOT = Path(__file__).resolve().parents[1]
CACHE = BSI_HNT.default_path(ROOT / "tools" / "data" / "00_source_files")

pytestmark = pytest.mark.skipif(not CACHE.is_file(), reason=f"missing {CACHE}")


@pytest.fixture(scope="module")
def books():
    return extract_bsi_nt(CACHE, BSI_HNT)


@pytest.fixture(scope="module")
def outputs(books):
    return {
        variant: build_multibook_osis(books, BSI_HNT, variant)
        for variant in BSI_HNT.output_names()
    }


def test_covers_all_27_nt_books_in_canonical_order(books):
    assert tuple(books) == BSI_HNT.expected_book_order
    assert len(books) == 27


def test_no_translation_variant_is_produced():
    assert set(BSI_HNT.output_names()) == {"hebrew", "hebrew_commented"}


def test_verses_carry_no_stray_whitespace(books):
    ragged = [
        f"{osis_book} {r.label}"
        for osis_book, document in books.items()
        for r in document.records
        if r.hebrew != r.hebrew.strip()
    ]
    assert ragged == []


@pytest.mark.parametrize(
    ("osis_id", "expected"),
    [
        ("Matt.1.1", 'סֵפֶר הַיּוּחֲסִין שֶׁל יֵשׁוּעַ הַמָּשִׁיחַ בֶּן־דָּוִד בֶּן־אַבְרָהָם:'),
        ("John.1.1", 'בְּרֵאשִׁית הָיָה הַדָּבָר, וְהַדָּבָר הָיָה עִם הָאֱלֹהִים, וֵאלֹהִים הָיָה הַדָּבָר.'),
    ],
)
def test_spot_checked_verses_match_the_well_known_text(books, osis_id, expected):
    osis_book, chapter, verse = osis_id.split(".")
    record = next(
        r
        for r in books[osis_book].records
        if r.chapter == int(chapter) and r.verse == verse
    )
    assert record.hebrew == expected


def test_this_is_a_distinct_translation_from_delitzsch(books):
    """Different wording for the same verse is the point, not a bug: this
    and the Delitzsch module are two different, real translations."""
    matt_1_1 = next(
        r for r in books["Matt"].records if r.chapter == 1 and r.verse == "1"
    )
    # Delitzsch opens Matthew "Sefer toldot" (archaic); this opens "Sefer
    # hayuchasin" (modern) — related but not identical wording.
    assert matt_1_1.hebrew.startswith("סֵפֶר הַיּוּחֲסִין")
    assert not matt_1_1.hebrew.startswith("סֵפֶר תּוֹלְדֹת")


def test_pointed_but_without_cantillation(books):
    """Printed with niqqud, unlike plain modern-Hebrew prose — but with none
    of the cantillation marks Delitzsch's module also carries."""
    joined = "".join(r.hebrew for d in books.values() for r in d.records)
    niqqud = any("ְ" <= c <= "ּ" or c in "ׁׂ" for c in joined)
    cantillation = any("֑" <= c <= "֯" for c in joined)
    assert niqqud
    assert not cantillation


def test_records_pass_multibook_validation(books):
    assert validate_multibook_records(books, BSI_HNT) == []


def test_osis_validates_against_the_upstream_schema(outputs):
    schema = etree.XMLSchema(etree.parse(str(STRICT_SCHEMA)))
    for variant, payload in outputs.items():
        root = etree.fromstring(payload)
        assert schema.validate(root), (variant, schema.error_log)


def test_all_27_books_are_one_file_in_canonical_order(outputs):
    for variant, payload in outputs.items():
        root = etree.fromstring(payload)
        book_ids = root.xpath("//osis:div[@type='book']/@osisID", namespaces=NS)
        assert tuple(book_ids) == BSI_HNT.expected_book_order, variant


def test_milestones_are_balanced_across_the_whole_document(outputs):
    for variant, payload in outputs.items():
        root = etree.fromstring(payload)
        verses = root.xpath("//osis:verse", namespaces=NS)
        starts = [v.get("sID") for v in verses if v.get("sID")]
        ends = [v.get("eID") for v in verses if v.get("eID")]
        assert starts and starts == ends, variant
        assert starts[0] == "Matt.1.1"
        assert starts[-1] == "Rev.22.21"


def test_rights_state_there_is_no_reuse_permission(outputs):
    """No license is granted at all here, unlike Delitzsch's non-commercial
    permission — the header must say so, not just credit the publisher."""
    root = etree.fromstring(outputs["hebrew"])
    work = root.xpath("//osis:header/osis:work", namespaces=NS)[0]
    rights = work.xpath("./osis:rights/text()", namespaces=NS)
    assert rights and "Bible Society in Israel" in rights[0]
    assert "No reuse or redistribution permission" in rights[0]


def test_conversion_is_deterministic(tmp_path):
    first = convert_bsi_nt(CACHE, BSI_HNT, tmp_path)
    payloads = {p: p.read_bytes() for p in first.output_paths.values()}
    convert_bsi_nt(CACHE, BSI_HNT, tmp_path)
    assert {p: p.read_bytes() for p in first.output_paths.values()} == payloads
