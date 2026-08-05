"""Unit tests for the Cochin extractors.

These replace ``tests/test_extract.py``, whose subject — a block-driven state
machine over ``get_text("rawdict")`` — was retired. It assumed a verse header
occupied a block of its own and that Hebrew arrived in visual order; MuPDF ≥1.26
makes both false, and it had been failing since.
"""

from __future__ import annotations

import pytest

from pdf2osis.cochin import (
    CochinDocument,
    _resolve_part_notes,
    header_absence,
    parse_reference,
    reconcile_with_interlinear,
    states_absent,
)
from pdf2osis.models import Marker, VerseRecord
from pdf2osis.profiles import JAS, MAT
from pdf2osis.validate import _coverage_errors


def test_reference_keeps_a_source_range_and_its_alternate():
    parsed = parse_reference(
        "Revelation 14:19-20 (Cochin 14:19)", "Revelation", "Cochin"
    )
    chapter, verse, source_verse, alt = parsed
    assert (chapter, verse) == (14, "19")
    # The edition prints one record for two verses; the id stays stable while
    # the label keeps the range.
    assert source_verse == "19-20"
    assert alt == (14, "19")


def test_reference_ignores_a_footnote_marker_glued_to_the_verse():
    """"Revelation 1:117" is verse 1 carrying marker 17, not verse 117."""
    parsed = parse_reference("Revelation 1:1 17", "Revelation", "Cochin")
    assert parsed[:2] == (1, "1")


def test_reference_normalises_a_capitalised_suffix():
    assert parse_reference("Revelation 2:27A", "Revelation", "Cochin")[1] == "27a"


def test_james_reference_reads_its_kjv_parenthetical():
    parsed = parse_reference("James 2:15 (KJV 2:15-16)", "James", "KJV")
    assert parsed[0] == 2 and parsed[1] == "15"
    assert parsed[3] == (2, "15-16")


def test_prose_mentioning_a_reference_is_not_a_header():
    assert parse_reference(
        "Revelation 4:10 about praying and may possibly be dialoguing",
        "Revelation",
        "Cochin",
    ) is None


def test_absence_is_recognised_from_the_edition_s_own_wording():
    assert header_absence(
        "Revelation 9:9 (This verse does not exist in the Cochin manuscript)"
    ) == "This verse does not exist in the Cochin manuscript"
    assert header_absence("Revelation 9:10 (Cochin 9:9)") is None
    assert states_absent("Note: This verse does not exist in the Cochin manuscript.")
    assert states_absent("Translation: Does Not Exist")
    # The edition brackets the notice in some places and not others.
    assert states_absent("Translation: (This verse does not exist in the Cochin)") == (
        "This verse does not exist in the Cochin"
    )


def test_absence_is_not_read_into_prose_that_merely_says_the_words():
    """The phrase occurs mid-sentence meaning something else entirely."""
    # Revelation 14:19-20: verse 20 is absent, but this record holds verse 19.
    assert not states_absent(
        "NOTE: Verses 19 and 20 are combined into one verse in the manuscripts, "
        "and verse 20 does not exist in the"
    )
    # Matthew 8:10, translating the centurion narrative.
    assert not states_absent(
        "even with the children of Israel, there does not exist faith like this!"
    )
    # The comparison columns say it about the KJV and Aramaic texts, not about
    # the manuscript, so they are never consulted for absence.
    assert not states_absent("The Scriptures: does not exist")
    assert not states_absent("Aramaic: Does not exist")


def test_lettered_references_are_read_from_the_printed_header():
    """The suffixes are the edition's, not something this code invents.

    The source prints "Revelation 2:27A (Cochin 2:26)" and "Revelation 13:1a
    (Cochin 13:1)", so `parse_reference` reads them, lowercasing 27A to 27a.
    Nothing generates suffixes: a reference that genuinely repeated would
    collide, and `validate_records` fails on duplicate verse IDs.
    """
    assert parse_reference(
        "Revelation 2:27A (Cochin 2:26)", "Revelation", "Cochin"
    )[:2] == (2, "27a")
    assert parse_reference(
        "Revelation 13:1a (Cochin 13:1)", "Revelation", "Cochin"
    )[:2] == (13, "1a")


def test_interlinear_corrects_a_single_mis_decoded_letter():
    """The gloss table resolves letters the transcription's font confuses."""
    record = VerseRecord(chapter=1, verse="6", page=1)
    record.hebrew = "לפני ח֞ ואביו"
    record.interlinear_hebrew = "לפני ה֞ ואביו"
    assert reconcile_with_interlinear(record) == 1
    assert record.hebrew == "לפני ה֞ ואביו"
    assert record.extraction_disagreements


def test_interlinear_leaves_unrelated_words_alone():
    record = VerseRecord(chapter=1, verse="1", page=1)
    record.hebrew = "אלה הסודות"
    record.interlinear_hebrew = "דבר אחר"
    assert reconcile_with_interlinear(record) == 0
    assert record.hebrew == "אלה הסודות"


def test_interlinear_will_not_choose_between_two_candidates():
    """Two glosses one letter away is not evidence enough to change anything."""
    record = VerseRecord(chapter=1, verse="1", page=1)
    record.hebrew = "בית"
    record.interlinear_hebrew = "כית גית"
    assert reconcile_with_interlinear(record) == 0
    assert record.hebrew == "בית"


def test_coverage_check_catches_a_truncated_extraction():
    """A verse count alone cannot see that the wrong verses were dropped.

    `expected_first`/`expected_last` used to be carried on every profile and
    read by nothing; they are now enforced, so an extraction that loses the
    opening or closing verse fails even at the right total.
    """
    good = [VerseRecord(chapter=1, verse="1", page=1),
            VerseRecord(chapter=5, verse="20", page=2)]
    assert _coverage_errors(good, JAS) == []

    truncated = [VerseRecord(chapter=1, verse="2", page=1),
                 VerseRecord(chapter=5, verse="19", page=2)]
    errors = _coverage_errors(truncated, JAS)
    assert len(errors) == 2
    assert "first verse is 1:2, expected 1:1" in errors[0]
    assert "last verse is 5:19, expected 5:20" in errors[1]
    assert _coverage_errors([], JAS) == ["no records"]


def test_matthew_header_reads_its_cochin_parenthetical():
    """Matthew 17:23 and 17:24 are the only two headers that carry one.

    Matthew is headed "Chapter N:V" where the other editions print the book's
    name, so it used to be read by an anchored `Chapter N:V` pattern of its
    own. That pattern rejected a parenthetical outright, and those two verses
    vanished from a 910-verse book without an anomaly to show for it. The
    shared parser reads both forms, and keeps what the parenthetical says.
    """
    assert parse_reference("Chapter 17:23 (Cochin 17:22b)", "Chapter", "Cochin") == (
        17,
        "23",
        None,
        (17, "22b"),
    )
    assert parse_reference("Chapter 20:1", "Chapter", "Cochin") == (20, "1", None, None)


def test_parts_are_ordered_by_the_chapter_they_cover(tmp_path):
    """Ordering follows the chapter number, not the filename.

    A filename sort puts chapter 10 before chapter 9, and this publisher pads
    inconsistently and spells the book both "Mathew" and "Matthew". Reading the
    number out of the name survives all of that; sorting the names does not.
    """
    for name in (
        "Cochin-Mathew-Chapter-9_June-17-2026.pdf",
        "Cochin-Matthew-Chapter-10_publication_Nov-06_2025.pdf",
        "Cochin-Matthew-Chapter-02_publication_April-6-2026.pdf",
    ):
        (tmp_path / name).write_bytes(b"")

    assert [path.name for path in MAT.part_paths(tmp_path)] == [
        "Cochin-Matthew-Chapter-02_publication_April-6-2026.pdf",
        "Cochin-Mathew-Chapter-9_June-17-2026.pdf",
        "Cochin-Matthew-Chapter-10_publication_Nov-06_2025.pdf",
    ]


def test_two_files_claiming_one_chapter_are_refused(tmp_path):
    """Silently keeping one of them would drop a chapter from the book."""
    (tmp_path / "Cochin-Matthew-Chapter-05_May-5-2026.pdf").write_bytes(b"")
    (tmp_path / "Cochin-Matthew-Chapter-5_May-6-2026.pdf").write_bytes(b"")
    with pytest.raises(ValueError, match="claim chapter 5"):
        MAT.part_paths(tmp_path)


def test_a_single_volume_profile_reads_the_file_it_names(tmp_path):
    source = tmp_path / "james.pdf"
    assert JAS.part_paths(source) == [source]


def _one_part(chapter: str, number: str) -> list[VerseRecord]:
    record = VerseRecord(chapter=int(chapter), verse="1", page=1)
    record.hebrew_markers.append(Marker(offset=0, number=number))
    return [record]


def test_serialised_parts_do_not_share_a_footnote_number():
    """Each part numbers its notes from one, so the numbers collide on merge.

    Chapter 20's note 6 and chapter 24's note 6 are different notes; across
    Matthew 52 of 56 printed numbers are reused this way. Merging under the
    printed numbers lets one silently overwrite the other, so the parts are
    renumbered into one sequence as they are joined.
    """
    document = CochinDocument()
    first, second = _one_part("20", "6"), _one_part("24", "6")
    document.records = first + second

    following = _resolve_part_notes(document, first, {"6": "on chapter 20"}, 1, True)
    following = _resolve_part_notes(
        document, second, {"6": "on chapter 24"}, following, True
    )

    assert document.notes == {"1": "on chapter 20", "2": "on chapter 24"}
    assert first[0].hebrew_markers[0].number == "1"
    assert second[0].hebrew_markers[0].number == "2"
    assert following == 3


def test_a_single_volume_keeps_the_numbers_its_source_prints():
    """Revelation's notes run 15-588 and James's 8-33, neither from 1.

    Renumbering those would move every note in the published files, so it is
    confined to editions that actually come in parts.
    """
    document = CochinDocument()
    records = _one_part("1", "15")
    document.records = records

    _resolve_part_notes(document, records, {"15": "as printed"}, 1, False)

    assert document.notes == {"15": "as printed"}
    assert records[0].hebrew_markers[0].number == "15"


def test_a_marker_is_matched_against_its_own_part_only():
    """This ordering is what makes renumbering safe.

    Chapter 20 prints a marker 6 it never defines. Were the parts merged first
    and matched afterwards, chapter 24's note 6 would satisfy it and print a
    note about chapter 24 on a verse of chapter 20.
    """
    document = CochinDocument()
    first, second = _one_part("20", "6"), _one_part("24", "6")
    document.records = first + second

    following = _resolve_part_notes(document, first, {}, 1, True)
    _resolve_part_notes(document, second, {"6": "on chapter 24"}, following, True)

    assert first[0].hebrew_markers == []
    assert first[0].excluded_markers == ["6"]
    assert second[0].hebrew_markers[0].number == "1"
    assert document.notes == {"1": "on chapter 24"}
