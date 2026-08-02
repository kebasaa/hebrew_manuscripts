"""Fidelity tests for the Delitzsch Hebrew New Testament (SWORD module).

Unlike every other source in this package, this one is not a PDF — it is a
CrossWire SWORD module, read directly by :mod:`pdf2osis.sword` via
``pysword``, and it spans the whole New Testament rather than one book. The
module file is downloaded, not committed, so these tests skip if it is not
present locally rather than failing.

Ground truth for the spot-checked verses is the well-known text of each
passage, not a rendered page — there is no page here to render.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from pdf2osis.converter import convert_sword_nt
from pdf2osis.osis import OSIS_NS, build_multibook_osis
from pdf2osis.profiles import DELITZSCH
from pdf2osis.sword import extract_sword_nt
from pdf2osis.validate import STRICT_SCHEMA, validate_multibook_records

NS = {"osis": OSIS_NS}
ROOT = Path(__file__).resolve().parents[1]
MODULE = DELITZSCH.default_path(ROOT / "data" / "00_source_files")

pytestmark = pytest.mark.skipif(not MODULE.is_file(), reason=f"missing {MODULE}")


@pytest.fixture(scope="module")
def books():
    return extract_sword_nt(MODULE, DELITZSCH)


@pytest.fixture(scope="module")
def outputs(books):
    return {
        variant: build_multibook_osis(books, DELITZSCH, variant)
        for variant in DELITZSCH.output_names()
    }


def test_covers_all_27_nt_books_in_canonical_order(books):
    assert tuple(books) == DELITZSCH.expected_book_order
    assert len(books) == 27


def test_total_verse_count_matches_the_module_s_own_versification(books):
    total = sum(len(document.records) for document in books.values())
    assert total == DELITZSCH.expected_verses == 7959


def test_no_translation_variant_is_produced():
    assert set(DELITZSCH.output_names()) == {"hebrew", "hebrew_commented"}


@pytest.mark.parametrize(
    ("osis_id", "expected"),
    [
        ("Matt.1.1", "סֵפֶר תּוֹלְדֹת יֵשׁוּעַ הַמָּשִׁיחַ בֶּן־דָּוִד בֶּן־אַבְרָהָם׃"),
        (
            "John.1.1",
            "בְּרֵאשִׁית הָיָה הַדָּבָר וְהַדָּבָר הָיָה אֵת הָאֱלֹהִים וֵאלֹהִים הָיָה הַדָּבָר׃",
        ),
        (
            "Rev.22.21",
            "חֶסֶד אֲדֹנֵינוּ יֵשׁוּעַ הַמָּשִׁיחַ עִם־כֻּלְּכֶם וְכָל־הַקְּדוֹשִׁים אָמֵן׃",
        ),
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


def test_the_three_known_versification_gaps_are_empty_and_explained(books):
    """2 Cor 13:14, 3 John 1:15, Rev 12:18: NRSV slots the module leaves
    unfilled, a fact about the source rather than a bug in the extractor."""
    gaps = [
        ("2Cor", 13, "14"),
        ("3John", 1, "15"),
        ("Rev", 12, "18"),
    ]
    for osis_book, chapter, verse in gaps:
        record = next(
            r
            for r in books[osis_book].records
            if r.chapter == chapter and r.verse == verse
        )
        assert record.empty
        assert not record.hebrew
        assert record.absence and "versification slot" in record.absence

    # And nothing else in the whole NT is unexpectedly empty.
    unexpected = [
        f"{osis_book} {r.label}"
        for osis_book, document in books.items()
        for r in document.records
        if r.empty and (osis_book, r.chapter, r.verse) not in gaps
    ]
    assert unexpected == []


def test_records_pass_multibook_validation(books):
    assert validate_multibook_records(books, DELITZSCH) == []


def test_osis_validates_against_the_upstream_schema(outputs):
    schema = etree.XMLSchema(etree.parse(str(STRICT_SCHEMA)))
    for variant, payload in outputs.items():
        root = etree.fromstring(payload)
        assert schema.validate(root), (variant, schema.error_log)


def test_all_27_books_are_one_file_in_canonical_order(outputs):
    for variant, payload in outputs.items():
        root = etree.fromstring(payload)
        book_ids = root.xpath("//osis:div[@type='book']/@osisID", namespaces=NS)
        assert tuple(book_ids) == DELITZSCH.expected_book_order, variant


def test_milestones_are_balanced_across_the_whole_document(outputs):
    for variant, payload in outputs.items():
        root = etree.fromstring(payload)
        verses = root.xpath("//osis:verse", namespaces=NS)
        starts = [v.get("sID") for v in verses if v.get("sID")]
        ends = [v.get("eID") for v in verses if v.get("eID")]
        assert starts and starts == ends, variant
        assert starts[0] == "Matt.1.1"
        assert starts[-1] == "Rev.22.21"


def test_rights_and_translator_credit_appear_on_the_hebrew_variant(outputs):
    """This source has no translation variant to carry them, so its Hebrew
    variants do — otherwise the copyright notice would appear nowhere at all."""
    root = etree.fromstring(outputs["hebrew"])
    work = root.xpath("//osis:header/osis:work", namespaces=NS)[0]
    rights = work.xpath("./osis:rights/text()", namespaces=NS)
    assert rights and "Streams in the Negev" in rights[0]
    assert "non-commercial" in rights[0]
    creator = work.xpath("./osis:creator/text()", namespaces=NS)
    assert creator == ["Franz Delitzsch"]


def test_conversion_is_deterministic(tmp_path):
    first = convert_sword_nt(MODULE, DELITZSCH, tmp_path)
    payloads = {p: p.read_bytes() for p in first.output_paths.values()}
    convert_sword_nt(MODULE, DELITZSCH, tmp_path)
    assert {p: p.read_bytes() for p in first.output_paths.values()} == payloads
