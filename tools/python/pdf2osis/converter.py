from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
import os
from pathlib import Path
import tempfile

from .cochin import extract_cochin
from .models import VerseDocument
from .osis import build_multibook_osis, build_structured_osis
from .profiles import BookProfile
from .bsi_hnt import extract_bsi_nt
from .ebr530 import extract_ebr530
from .sloane import extract_sloane
from .sword import extract_sword_nt
from .validate import (
    validate_multibook_records,
    validate_osis,
    validate_records,
    validate_sloane_records,
)


class ConversionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ConversionReport:
    book: str
    input_path: Path
    output_paths: dict[str, Path]
    verses: int
    chapters: int
    empty_verses: tuple[str, ...]
    alternate_verses: int
    note_definitions: int
    emitted_notes: dict[str, int]
    transcription_interlinear_disagreements: int
    excluded_markers: tuple[str, ...]
    contamination_failures: tuple[str, ...]
    reference_comparison: dict[str, int] | None
    anomalies: tuple[str, ...]


def convert_pdf(
    input_path: str | Path,
    book_profile: BookProfile,
    output_dir: str | Path,
) -> ConversionReport:
    source = Path(input_path).resolve()
    destination = Path(output_dir).resolve()
    if not source.is_file():
        raise ConversionError(f"Input file not found: {source}")
    destination.mkdir(parents=True, exist_ok=True)

    document = None
    try:
        if book_profile.extractor == "sloane":
            document = extract_sloane(source, book_profile)
        elif book_profile.extractor == "ebr530":
            document = extract_ebr530(source, book_profile)
        else:
            document = extract_cochin(source, book_profile)
        records = document.records
        definitions = document.notes
        anomalies = document.anomalies
    except (ValueError, KeyError) as exc:
        raise ConversionError(str(exc)) from exc
    errors = (
        validate_records(records, book_profile)
        if book_profile.extractor == "cochin"
        else validate_sloane_records(document, book_profile)
    )
    if errors:
        raise ConversionError("Record validation failed:\n- " + "\n- ".join(errors))

    expected_ids = [
        f"{book_profile.osis_book}.{record.chapter}.{record.verse}"
        for record in records
    ]
    payloads: dict[str, bytes] = {}
    emitted_notes: dict[str, int] = {}
    for variant in book_profile.output_names():
        payload = build_structured_osis(document, book_profile, variant)
        try:
            validation = validate_osis(
                payload,
                book_profile,
                expected_ids,
            )
        except (ValueError, TypeError) as exc:
            raise ConversionError(
                f"{variant} OSIS validation failed: {exc}"
            ) from exc
        payloads[variant] = payload
        emitted_notes[variant] = validation.notes

    output_paths = {
        variant: destination / filename
        for variant, filename in book_profile.output_names().items()
    }
    temporary_paths: dict[str, Path] = {}
    try:
        for variant, payload in payloads.items():
            handle, temporary_name = tempfile.mkstemp(
                prefix=f".{output_paths[variant].name}.",
                suffix=".tmp",
                dir=destination,
            )
            temporary = Path(temporary_name)
            temporary_paths[variant] = temporary
            with os.fdopen(handle, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        for variant, temporary in temporary_paths.items():
            os.replace(temporary, output_paths[variant])
    finally:
        for temporary in temporary_paths.values():
            if temporary.exists():
                temporary.unlink()

    return ConversionReport(
        book=book_profile.key,
        input_path=source,
        output_paths=output_paths,
        verses=len(records),
        chapters=len({record.chapter for record in records}),
        empty_verses=tuple(record.label for record in records if record.empty),
        alternate_verses=sum(
            record.alt_verse is not None
            for record in records
        ),
        note_definitions=len(definitions),
        emitted_notes=emitted_notes,
        transcription_interlinear_disagreements=sum(
            len(record.extraction_disagreements)
            for record in records
        ),
        excluded_markers=tuple(
            f"{book_profile.osis_book}.{record.chapter}.{record.verse}: {item}"
            for record in records
            for item in record.excluded_markers
        ),
        contamination_failures=(),
        reference_comparison=None,
        anomalies=tuple(anomalies),
    )


def _convert_multibook(
    input_path: str | Path,
    book_profile: BookProfile,
    output_dir: str | Path,
    *,
    extract: Callable[[Path, BookProfile], dict[str, VerseDocument]],
) -> ConversionReport:
    """Convert a whole-Testament source to one multi-book OSIS file.

    Parallel to `convert_pdf` rather than a branch inside it: a whole-Testament
    source is a dict of per-book documents, not the single document every PDF
    extractor returns, so building on the same document shape would mean
    threading that distinction through validation and reporting too. Shared by
    `convert_sword_nt` and `convert_bsi_nt`, which differ only in how the
    source file becomes that dict.
    """
    source = Path(input_path).resolve()
    destination = Path(output_dir).resolve()
    if not source.is_file():
        raise ConversionError(f"Input file not found: {source}")
    destination.mkdir(parents=True, exist_ok=True)

    try:
        books = extract(source, book_profile)
    except (ValueError, KeyError) as exc:
        raise ConversionError(str(exc)) from exc
    errors = validate_multibook_records(books, book_profile)
    if errors:
        raise ConversionError("Record validation failed:\n- " + "\n- ".join(errors))

    expected_ids = [
        f"{osis_book}.{record.chapter}.{record.verse}"
        for osis_book, document in books.items()
        for record in document.records
    ]
    payloads: dict[str, bytes] = {}
    emitted_notes: dict[str, int] = {}
    for variant in book_profile.output_names():
        payload = build_multibook_osis(books, book_profile, variant)
        try:
            validation = validate_osis(
                payload,
                book_profile,
                expected_ids,
                expected_books=list(book_profile.expected_book_order),
            )
        except (ValueError, TypeError) as exc:
            raise ConversionError(
                f"{variant} OSIS validation failed: {exc}"
            ) from exc
        payloads[variant] = payload
        emitted_notes[variant] = validation.notes

    output_paths = {
        variant: destination / filename
        for variant, filename in book_profile.output_names().items()
    }
    temporary_paths: dict[str, Path] = {}
    try:
        for variant, payload in payloads.items():
            handle, temporary_name = tempfile.mkstemp(
                prefix=f".{output_paths[variant].name}.",
                suffix=".tmp",
                dir=destination,
            )
            temporary = Path(temporary_name)
            temporary_paths[variant] = temporary
            with os.fdopen(handle, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        for variant, temporary in temporary_paths.items():
            os.replace(temporary, output_paths[variant])
    finally:
        for temporary in temporary_paths.values():
            if temporary.exists():
                temporary.unlink()

    all_records = [
        record for document in books.values() for record in document.records
    ]
    return ConversionReport(
        book=book_profile.key,
        input_path=source,
        output_paths=output_paths,
        verses=len(all_records),
        chapters=sum(
            len({record.chapter for record in document.records})
            for document in books.values()
        ),
        empty_verses=tuple(
            f"{osis_book} {record.label}"
            for osis_book, document in books.items()
            for record in document.records
            if record.empty
        ),
        alternate_verses=0,
        note_definitions=0,
        emitted_notes=emitted_notes,
        transcription_interlinear_disagreements=0,
        excluded_markers=(),
        contamination_failures=(),
        reference_comparison=None,
        anomalies=(),
    )


convert_sword_nt = partial(_convert_multibook, extract=extract_sword_nt)
convert_bsi_nt = partial(_convert_multibook, extract=extract_bsi_nt)
