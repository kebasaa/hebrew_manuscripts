"""The cataloguing fields, and the names the corpus is published under.

These are the contract between the converter and `src/build_manifest.py` at the
repository root: the manifest reads five `<description type="x-…">` elements out
of every header, and Milah's download dialog reads the manifest. A field that
stops being written does not fail anything — it quietly empties a column.
"""

from __future__ import annotations

import re

from lxml import etree
import pytest

from pdf2osis.osis import OSIS_NS, build_structured_osis
from pdf2osis.models import VerseDocument, VerseRecord
from pdf2osis.profiles import BOOK_PROFILES, BSI_HNT, DELITZSCH, MAT, REV

#: The five, in the order `pdf2osis.osis._work` writes them. Spelled out here
#: rather than derived, so that renaming a field in the profile without
#: updating the manifest breaks a test instead of a column.
CATALOGUING = (
    "x-folios",
    "x-material",
    "x-provenance",
    "x-translated-from",
    "x-exemplar",
)


def _header(profile, variant: str) -> etree._Element:
    """The `<work>` element of a minimal document built from `profile`."""
    document = VerseDocument()
    document.records.append(
        VerseRecord(chapter=1, verse="1", page=1, hebrew="א", english="a")
    )
    root = etree.fromstring(build_structured_osis(document, profile, variant))
    return root.find(f".//{{{OSIS_NS}}}header/{{{OSIS_NS}}}work")


def _description(work: etree._Element, kind: str) -> str:
    """Read a description the way `build_manifest.description_text` does."""
    for description in work.findall(f"{{{OSIS_NS}}}description"):
        if description.get("type") == kind:
            return re.sub(r"\s+", " ", "".join(description.itertext())).strip()
    raise AssertionError(f"no <description type={kind!r}>")


@pytest.mark.parametrize("key", sorted(BOOK_PROFILES))
def test_every_variant_carries_all_five_cataloguing_fields(key: str) -> None:
    """Written whether or not there is an answer.

    An absent element and an empty one say the same nothing to a reader looking
    for the folios of a manuscript. The empty one at least records that the
    question was put and has no published answer — several of these genuinely
    have none, and inventing one would be worse than saying so.
    """
    profile = BOOK_PROFILES[key]
    for variant in profile.output_names():
        work = _header(profile, variant)
        for kind in CATALOGUING:
            _description(work, kind)


def test_an_unanswered_field_reads_back_as_no_answer() -> None:
    """No catalogue records what Cochin Oo.1.16.2 is written on."""
    work = _header(REV, "hebrew_commented")
    assert REV.material == ""
    assert _description(work, "x-material") == ""
    # Self-closing, as the hand-catalogued files in manuscripts/ are.
    element = work.xpath(
        "osis:description[@type='x-material']", namespaces={"osis": OSIS_NS}
    )[0]
    assert element.text is None
    assert len(element) == 0


def test_an_answered_field_reaches_the_header_intact() -> None:
    work = _header(MAT, "hebrew_commented")
    assert _description(work, "x-folios") == MAT.folios
    assert "1r–21v" in _description(work, "x-folios")
    assert "Kurt Sutton" in _description(work, "x-provenance")


def test_a_contested_question_records_the_disagreement() -> None:
    """The Cochin source language is disputed, so both sides are named.

    Picking one and stating it flatly would turn an open scholarly question
    into a fact of the catalogue.
    """
    work = _header(REV, "hebrew_commented")
    translated = _description(work, "x-translated-from")
    assert "van Dort" in translated and "van Rensburg" in translated
    assert "Statenvertaling" in translated and "Peshitta" in translated


def test_provenance_is_written_once() -> None:
    """It used to live in `descriptions`; moving it must not double it."""
    for key, profile in BOOK_PROFILES.items():
        assert not any(kind == "x-provenance" for kind, _ in profile.descriptions), key
        work = _header(profile, sorted(profile.output_names())[0])
        found = work.xpath(
            "osis:description[@type='x-provenance']", namespaces={"osis": OSIS_NS}
        )
        assert len(found) == 1, key


def test_published_names_match_the_catalogue() -> None:
    """The names in manuscripts/, which the manifest and Milah both key on.

    The bare Hebrew is published only where there is no separate translation:
    where there is one, the commented Hebrew already carries that transcription.
    """
    published = {
        name
        for profile in BOOK_PROFILES.values()
        if profile is not BSI_HNT
        for name in profile.output_names().values()
    }
    assert published == {
        "REV_CochinOo.1.16.2_hebrew_commented.osis",
        "REV_CochinOo.1.16.2_translation.osis",
        "JAS_CochinOo.1.32_hebrew_commented.osis",
        "JAS_CochinOo.1.32_translation.osis",
        "MAT_CochinOo.1.32_hebrew_commented.osis",
        "MAT_CochinOo.1.32_translation.osis",
        "REV_Sloane237_hebrew_commented.osis",
        "REV_Sloane237_translation.osis",
        "LUK_Ebr530_hebrew_commented.osis",
        "LUK_Ebr530_translation.osis",
        "JOH_Ebr530_hebrew_commented.osis",
        "JOH_Ebr530_translation.osis",
        "NT_Delitzsch_hebrew.osis",
        "NT_Delitzsch_hebrew_commented.osis",
    }


def test_the_bare_hebrew_is_still_buildable_where_it_is_not_published() -> None:
    """Not published is not the same as not produced.

    The apparatus-free Hebrew is what shows that the notes really are confined
    to the commented variants, so it must stay available to build.
    """
    assert "hebrew" not in REV.output_names()
    work = _header(REV, "hebrew")
    assert work is not None
    # And where there is no translation, it is the variant that is published.
    assert "hebrew" in DELITZSCH.output_names()
