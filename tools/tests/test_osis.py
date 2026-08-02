from __future__ import annotations

from lxml import etree

from pdf2osis.cochin import CochinDocument
from pdf2osis.models import Marker, VerseRecord
from pdf2osis.osis import OSIS_NS, build_structured_osis
from pdf2osis.profiles import REV
from pdf2osis.validate import validate_osis

NAMESPACE = {"osis": OSIS_NS}


def build(records: list[VerseRecord], variant: str, notes: dict | None = None):
    document = CochinDocument(records=records, notes=notes or {})
    return build_structured_osis(document, REV, variant)


def verse_text(root: etree._Element, osis_id: str) -> str:
    """Milestoned verse text runs from the sID element to its matching eID."""
    start = root.xpath(
        f"//osis:verse[@sID='{osis_id}']", namespaces=NAMESPACE
    )[0]
    parts = [start.tail or ""]
    node = start
    while (node := node.getnext()) is not None:
        if etree.QName(node).localname == "verse" and node.get("eID"):
            break
        parts.append("".join(node.itertext()))
        parts.append(node.tail or "")
    return "".join(parts).strip()


def test_osis_escapes_text_declares_work_and_interleaves_note() -> None:
    record = VerseRecord(
        chapter=1,
        verse="1",
        source_verse="1",
        page=16,
        hebrew="אלה & הסודות",
        english="These & mysteries",
        hebrew_markers=[Marker(4, "20")],
        english_markers=[Marker(6, "20")],
        notes={"20": "A & B"},
    )
    payload = build([record], "hebrew_commented", {"20": "A & B"})
    result = validate_osis(payload, REV, ["Rev.1.1"])
    assert result.notes == 1
    root = etree.fromstring(payload)
    assert verse_text(root, "Rev.1.1") == "אלה A & B& הסודות"
    osis_text = root.find(f"{{{OSIS_NS}}}osisText")
    assert osis_text is not None
    assert osis_text.get("osisIDWork") == "CochinOo.1.16.2_REV_Hebrew_Commented"


def test_combined_source_range_uses_stable_id_and_range_label() -> None:
    record = VerseRecord(
        chapter=14,
        verse="19",
        source_verse="19-20",
        page=239,
        alt_chapter=14,
        alt_verse="19",
        hebrew="והיקב",
        english="And the winepress",
    )
    root = etree.fromstring(build([record], "hebrew"))
    verse = root.xpath("//osis:verse[@sID]", namespaces=NAMESPACE)[0]
    assert verse.get("osisID") == "Rev.14.19"
    assert verse.get("n") == "19-20"
    # The edition's own reference rides on subType, whose values must begin
    # with `x-`; a private-namespace attribute would fail strict OSIS.
    assert verse.get("subType") == "x-alt-14.19"


def test_note_without_a_marker_is_not_guessed_onto_verse() -> None:
    record = VerseRecord(
        chapter=1,
        verse="1",
        source_verse="1",
        page=16,
        hebrew="אלה הסודות",
        english="These mysteries",
        notes={"20": "Interlinear source note"},
    )
    root = etree.fromstring(build([record], "hebrew_commented", {"20": "x"}))
    assert root.xpath("//osis:note", namespaces=NAMESPACE) == []
    assert verse_text(root, "Rev.1.1") == "אלה הסודות"


def test_verses_are_milestoned_and_notes_use_a_standard_type() -> None:
    records = [
        VerseRecord(chapter=1, verse="1", page=16, hebrew="אלה",
                    english="These", hebrew_markers=[Marker(3, "20")]),
        VerseRecord(chapter=1, verse="2", page=16, hebrew="הסודות",
                    english="mysteries"),
    ]
    payload = build(records, "hebrew_commented", {"20": "A note"})
    root = etree.fromstring(payload)
    verses = root.xpath("//osis:verse", namespaces=NAMESPACE)
    starts = [v.get("sID") for v in verses if v.get("sID")]
    assert starts == ["Rev.1.1", "Rev.1.2"]
    assert starts == [v.get("eID") for v in verses if v.get("eID")]
    # Milestone form is all-or-nothing: no verse may hold its own text.
    assert not [v for v in verses if v.text]
    note = root.xpath("//osis:note", namespaces=NAMESPACE)[0]
    # `footnote` is not an OSIS 2.1.1 note type.
    assert note.get("type") == "explanation"
    assert note.get("osisRef") == "Rev.1.1"
    assert note.get("osisID") == "Rev.1.1!note.20"
    lines = payload.decode("utf-8").splitlines()
    assert len([line for line in lines if "<verse sID=" in line]) == 2
