from __future__ import annotations

from collections import Counter
import unicodedata
from dataclasses import dataclass
from pathlib import Path
import re

from lxml import etree

from .models import VerseRecord
from .osis import OSIS_NS
from .profiles import BookProfile

FORBIDDEN_TEXT = (
    "The Return Letter of James",
    "The Scroll of Mysteries: Cochin Hebrew Revelation",
    "Image courtesy of MidJourney",
    "The Covenant with Yehovah",
    "Ketubah Covenant",
    "KJV:",
    "The Scriptures:",
    "Interlinear Chart",
)
INTERLINEAR_GLOSS_MARKERS = (
    "Pa’al/Qal",
    "pronom)",
    "(n ms)",
)
# The upstream OSIS schema, vendored so validation needs no network. Its
# xml.xsd import was repointed at the copy beside it.
SCHEMA_DIR = Path(__file__).with_name("schema")
STRICT_SCHEMA = SCHEMA_DIR / "osisCore.2.1.1.xsd"


@dataclass
class ValidationResult:
    verse_ids: list[str]
    notes: int


def _coverage_errors(
    records: list[VerseRecord], profile: BookProfile
) -> list[str]:
    """Check the extraction begins and ends where the source does.

    A verse count alone cannot catch an extraction that drops the opening or
    closing verse and picks up a spurious one elsewhere.
    """
    if not records:
        return ["no records"]
    errors = []
    for label, found, expected in (
        ("first", (records[0].chapter, records[0].verse), profile.expected_first),
        ("last", (records[-1].chapter, records[-1].verse), profile.expected_last),
    ):
        if found != expected:
            errors.append(
                f"{label} verse is {found[0]}:{found[1]}, "
                f"expected {expected[0]}:{expected[1]}"
            )
    return errors


def validate_records(
    records: list[VerseRecord],
    profile: BookProfile,
) -> list[str]:
    errors: list[str] = []
    if len(records) != profile.expected_verses:
        errors.append(
            f"expected {profile.expected_verses} verses, found {len(records)}"
        )
    chapters = sorted({record.chapter for record in records})
    expected_chapters = list(range(1, profile.expected_chapters + 1))
    if chapters != expected_chapters:
        errors.append(f"unexpected chapters: {chapters}")
    errors.extend(_coverage_errors(records, profile))
    ids = [
        f"{profile.osis_book}.{record.chapter}.{record.verse}"
        for record in records
    ]
    duplicates = [key for key, count in Counter(ids).items() if count > 1]
    if duplicates:
        errors.append("duplicate verse IDs: " + ", ".join(duplicates))
    first_text = next(
        (record.hebrew for record in records if record.hebrew),
        "",
    )
    if not first_text.startswith(profile.expected_hebrew_prefix):
        errors.append(
            "Hebrew RTL reconstruction failed: first text starts with "
            f"{first_text[:40]!r}"
        )
    for record in records:
        if record.empty:
            continue
        if not record.hebrew:
            errors.append(f"{profile.osis_book} {record.label} has no Hebrew")
        if re.search(r"[A-Za-z]", record.hebrew):
            errors.append(
                f"{profile.osis_book} {record.label} has Latin contamination "
                "in clean Hebrew"
            )
        if profile.has_translation and not record.english:
            errors.append(f"{profile.osis_book} {record.label} has no translation")
        combined = record.hebrew + " " + record.english
        for phrase in FORBIDDEN_TEXT:
            if phrase in combined:
                errors.append(
                    f"{profile.osis_book} {record.label} contains {phrase!r}"
                )
        for marker in INTERLINEAR_GLOSS_MARKERS:
            if marker in record.english:
                errors.append(
                    f"{profile.osis_book} {record.label} contains "
                    f"interlinear gloss marker {marker!r}"
                )
    return errors


def validate_multibook_records(
    books: dict[str, object], profile: BookProfile
) -> list[str]:
    """Record-level checks for a source spanning many books in one file.

    Chapter numbers reset per book, so the single-book checks in
    `validate_records` do not apply as written; this checks the same
    properties — total coverage, no stray Latin in clean Hebrew, no verse ID
    collisions — scoped per book instead.
    """
    errors: list[str] = []
    if tuple(books) != profile.expected_book_order:
        errors.append(
            f"book order is {list(books)}, expected "
            f"{list(profile.expected_book_order)}"
        )
    total = sum(len(document.records) for document in books.values())
    if total != profile.expected_verses:
        errors.append(f"expected {profile.expected_verses} verses, found {total}")
    all_ids = [
        f"{osis_book}.{record.chapter}.{record.verse}"
        for osis_book, document in books.items()
        for record in document.records
    ]
    duplicates = [key for key, count in Counter(all_ids).items() if count > 1]
    if duplicates:
        errors.append("duplicate verse IDs: " + ", ".join(duplicates))
    first_book = next(iter(books.values()), None)
    first_text = next(
        (record.hebrew for record in (first_book.records if first_book else ()) if record.hebrew),
        "",
    )
    if not first_text.startswith(profile.expected_hebrew_prefix):
        errors.append(
            "Hebrew RTL reconstruction failed: first text starts with "
            f"{first_text[:40]!r}"
        )
    for osis_book, document in books.items():
        for record in document.records:
            if record.empty:
                continue
            if not record.hebrew:
                errors.append(f"{osis_book} {record.label} has no Hebrew")
            if re.search(r"[A-Za-z]", record.hebrew):
                errors.append(
                    f"{osis_book} {record.label} has Latin contamination "
                    "in clean Hebrew"
                )
    return errors


def validate_osis(
    payload: bytes,
    profile: BookProfile,
    expected_ids: list[str],
    *,
    expected_books: list[str] | None = None,
) -> ValidationResult:
    """Validate one generated OSIS document.

    ``expected_books`` defaults to the profile's single book; a multi-book
    source (:func:`pdf2osis.osis.build_multibook_osis`) passes every book it
    wrote, in the same order, since a book div's presence and order matter as
    much as any one verse's.
    """
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    root = etree.fromstring(payload, parser)
    schema = etree.XMLSchema(etree.parse(str(STRICT_SCHEMA)))
    if not schema.validate(root):
        error = schema.error_log.last_error
        raise ValueError(
            f"OSIS schema validation failed against {STRICT_SCHEMA.name}"
            + (f": {error.message}" if error is not None else "")
        )
    namespace = {"osis": OSIS_NS}
    osis_text = root.find("osis:osisText", namespace)
    if osis_text is None:
        raise ValueError("missing osisText")
    work_id = osis_text.get("osisIDWork")
    ref_work = osis_text.get("osisRefWork")
    declared = {
        work.get("osisWork")
        for work in root.xpath("//osis:header/osis:work", namespaces=namespace)
    }
    if work_id not in declared:
        raise ValueError(f"osisIDWork {work_id!r} is not declared")
    if ref_work not in declared:
        raise ValueError(f"osisRefWork {ref_work!r} is not declared")
    books = root.xpath(
        "//osis:div[@type='book']/@osisID", namespaces=namespace
    )
    if books != (expected_books or [profile.osis_book]):
        raise ValueError(f"book divs {books} do not match expectations")
    verses = root.xpath("//osis:verse", namespaces=namespace)
    # In milestone form a verse is two elements; only the opening one carries
    # osisID. Check that every start is closed, in order.
    open_ids = [verse.get("sID") for verse in verses if verse.get("sID")]
    close_ids = [verse.get("eID") for verse in verses if verse.get("eID")]
    if open_ids and open_ids != close_ids:
        raise ValueError("unbalanced verse milestones")
    ids = [verse.get("osisID") for verse in verses if verse.get("osisID")]
    if ids != expected_ids:
        raise ValueError("OSIS verse coverage/order differs from parsed records")
    if len(ids) != len(set(ids)):
        raise ValueError("OSIS contains duplicate verse IDs")
    text = " ".join(root.itertext())
    contamination = [phrase for phrase in FORBIDDEN_TEXT if phrase in text]
    if contamination:
        raise ValueError("OSIS contains excluded text: " + ", ".join(contamination))
    notes = len(root.xpath("//osis:note", namespaces=namespace))
    return ValidationResult(ids, notes)


def validate_sloane_records(document, profile: BookProfile) -> list[str]:
    """Record-level checks for a pointed manuscript.

    Beyond coverage this asserts the niqqud invariants that the previous
    extraction violated: shin dots outnumbering shins, marks preceding their
    base, and marks left out of canonical order.
    """
    errors: list[str] = []
    records = document.records
    if len(records) != profile.expected_verses:
        errors.append(
            f"expected {profile.expected_verses} verses, found {len(records)}"
        )
    chapters = sorted({record.chapter for record in records})
    if chapters != list(range(1, profile.expected_chapters + 1)):
        errors.append(f"unexpected chapters: {chapters}")
    errors.extend(_coverage_errors(records, profile))
    ids = [
        f"{profile.osis_book}.{record.chapter}.{record.verse}"
        for record in records
    ]
    duplicates = [key for key, count in Counter(ids).items() if count > 1]
    if duplicates:
        errors.append("duplicate verse IDs: " + ", ".join(duplicates))
    first = next((record.hebrew for record in records if record.hebrew), "")
    if not first.startswith(profile.expected_hebrew_prefix):
        errors.append(
            "Hebrew reconstruction failed: first verse starts with "
            f"{first[:40]!r}"
        )
    texts = [record.hebrew for record in records]
    texts += [passage.hebrew for passage in document.passages if passage.hebrew]
    for record in records:
        label = f"{profile.osis_book} {record.chapter}:{record.verse}"
        if not record.hebrew:
            errors.append(f"{label} has no Hebrew")
        if re.search(r"[A-Za-z]", record.hebrew):
            errors.append(f"{label} has Latin contamination in Hebrew")
        if re.search(r"\d", record.hebrew):
            errors.append(f"{label} retains a digit in Hebrew")
        if not record.english:
            errors.append(f"{label} has no translation")
    errors.extend(_pointing_errors(texts, profile))
    return errors


def _pointing_errors(texts: list[str], profile: BookProfile) -> list[str]:
    errors: list[str] = []
    joined = "".join(texts)
    decomposed = unicodedata.normalize("NFD", joined)
    shins = decomposed.count("ש")
    dots = decomposed.count("ׁ") + decomposed.count("ׂ")
    if dots > shins:
        errors.append(
            f"{dots} shin/sin dots for only {shins} shins: dots are being "
            "attached to the wrong letters"
        )
    for text in texts:
        stream = unicodedata.normalize("NFD", text)
        for index, char in enumerate(stream):
            if not unicodedata.combining(char):
                continue
            if index == 0 or unicodedata.category(stream[index - 1]) == "Zs":
                errors.append(
                    f"combining mark U+{ord(char):04X} has no base letter in "
                    f"{text[:40]!r}"
                )
                break
        if unicodedata.normalize("NFC", text) != text:
            errors.append(f"text is not in canonical order: {text[:40]!r}")
    return errors
