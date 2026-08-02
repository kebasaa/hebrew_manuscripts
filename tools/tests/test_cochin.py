"""Unit tests for the Cochin extractors.

These replace ``tests/test_extract.py``, whose subject — a block-driven state
machine over ``get_text("rawdict")`` — was retired. It assumed a verse header
occupied a block of its own and that Hebrew arrived in visual order; MuPDF ≥1.26
makes both false, and it had been failing since.
"""

from __future__ import annotations

from pdf2osis.cochin import (
    header_absence,
    parse_reference,
    reconcile_with_interlinear,
    states_absent,
)
from pdf2osis.models import VerseRecord
from pdf2osis.profiles import JAS
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
