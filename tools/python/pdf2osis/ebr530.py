"""Extraction for Biblioteca Apostolica Vaticana, Vat. ebr. 530.

Part 1, fragment 11, folios 1r–2v carry Luke 1:1–35 and John 1:1–13. The layout
is a two-column Word table like Sloane 237's, but the font situation is the
mirror image: the ToUnicode CMap is sound while the embedded subsets carry no
``cmap`` table at all, and ``get_texttrace`` merges runs — and sometimes two
printed lines — into one span. So this profile reads ``rawdict`` and places every
glyph by its own coordinates; see :func:`pdf2osis.glyphs.glyph_line_text`.

Both books live in one PDF. A profile names one of them and the other is skipped,
which keeps one profile to one set of output files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz

from .glyphs import is_hebrew
from .layout import Line, footnote_definitions, page_lines
from .models import Folio, Marker, Passage, VerseRecord
from .profiles import BookProfile

# Verse numbers are printed inline as (N), at body size in both columns.
VERSE_MARKER_RE = re.compile(r"\(\s*(\d{1,3})\s*\)")
FOLIO_RE = re.compile(r"\[\s*folio\s+(\d{1,3}[rv])\s*\]", re.I)
NOTE_DIGIT_RE = re.compile(r"\d{1,3}")
# Both chapter headings read "פרק ראשון", but page 2 sets the shin with a sin
# dot and page 10 with a shin dot, so the match stops before the dot.
CHAPTER_HEADING_RE = re.compile(r"פֶרֶק\s+רִא")
# Its English counterpart, set beside it in the translation column.
ENGLISH_HEADING_RE = re.compile(r"^\s*Chapter\s+(?:One|\d+)\s*$", re.I)

# Luke runs from page 1 to the top of page 10; John starts lower on that page.
# Between them sit the folio marker, the John title and its chapter heading.
LUKE_LAST_PAGE = 10
LUKE_PAGE_10_BOTTOM = 240.0
JOHN_PAGE_10_TOP = 410.0
BLANK_PAGE = 13


@dataclass
class Ebr530Document:
    records: list[VerseRecord] = field(default_factory=list)
    passages: list[Passage] = field(default_factory=list)
    notes: dict[str, str] = field(default_factory=dict)
    anomalies: list[str] = field(default_factory=list)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def book_at(page_number: int, y: float) -> str | None:
    """Which book a line belongs to, or None for the material between them."""
    if page_number == 1:
        return "Luke"
    if 2 <= page_number < LUKE_LAST_PAGE:
        return "Luke"
    if page_number == LUKE_LAST_PAGE:
        if y < LUKE_PAGE_10_BOTTOM:
            return "Luke"
        if y >= JOHN_PAGE_10_TOP:
            return "John"
        return None
    if LUKE_LAST_PAGE < page_number < BLANK_PAGE:
        return "John"
    return None


def _extract_markers(text: str) -> tuple[str, list[Marker]]:
    """Pull footnote reference digits out of running text, keeping offsets."""
    markers: list[Marker] = []
    out: list[str] = []
    cursor = 0
    for match in NOTE_DIGIT_RE.finditer(text):
        out.append(text[cursor:match.start()])
        markers.append(Marker(sum(len(part) for part in out), match.group(0)))
        cursor = match.end()
    out.append(text[cursor:])
    return "".join(out), markers


def _split_verses(text: str) -> list[tuple[int | None, str]]:
    """Break a line at its ``(N)`` verse markers."""
    chunks: list[tuple[int | None, str]] = []
    cursor = 0
    leading = True
    for match in VERSE_MARKER_RE.finditer(text):
        before = text[cursor:match.start()]
        if _clean(before) or leading:
            chunks.append((None, before))
        chunks.append((int(match.group(1)), ""))
        cursor = match.end()
        leading = False
    tail = text[cursor:]
    if chunks:
        number, existing = chunks[-1]
        chunks[-1] = (number, existing + tail)
    else:
        chunks.append((None, tail))
    return chunks


def _append(record: VerseRecord, field_name: str, text: str) -> None:
    text, markers = _extract_markers(text)
    text = _clean(text)
    existing = getattr(record, field_name)
    shift = len(existing) + 1 if existing and text else len(existing)
    if text:
        setattr(record, field_name, _clean(f"{existing} {text}"))
    target = (
        record.hebrew_markers if field_name == "hebrew" else record.english_markers
    )
    for marker in markers:
        target.append(
            Marker(
                offset=min(shift + marker.offset, len(getattr(record, field_name))),
                number=marker.number,
            )
        )


def extract_ebr530(pdf_path: Path, profile: BookProfile) -> Ebr530Document:
    document = Ebr530Document()
    book = profile.osis_book_name
    records: dict[int, VerseRecord] = {}
    order: list[int] = []
    kwargs: dict[str, Any] = {
        "footer_top": profile.footer_top,
        "column_split": profile.column_split,
        "source": "rawdict",
    }

    with fitz.open(pdf_path) as pdf:
        from .glyphs import GlyphDecoder

        decoder = GlyphDecoder(pdf)
        document.notes = _collect_notes(pdf, decoder, profile)
        title_lines: list[str] = []
        heading: str | None = None
        title_markers: list[Marker] = []
        heading_markers: list[Marker] = []
        folios: list[Folio] = []
        current: VerseRecord | None = None

        for index, page in enumerate(pdf):
            number = index + 1
            hebrew = page_lines(page, decoder, column="hebrew", **kwargs)
            english = page_lines(page, decoder, column="english", **kwargs)

            for line in english:
                for match in FOLIO_RE.finditer(line.text):
                    if book_at(number, line.y) in (book, None):
                        folios.append(Folio(label=match.group(1).lower()))

            starts: list[tuple[float, int]] = []
            for line in hebrew:
                where = book_at(number, line.y)
                if CHAPTER_HEADING_RE.search(line.text):
                    if where == book or (number == LUKE_LAST_PAGE and book == "John"):
                        text, markers = _extract_markers(line.text)
                        heading = _clean(text)
                        heading_markers = markers
                    continue
                if where is None or where != book:
                    # The book titles sit above the first verse of each book.
                    if _is_title_line(line, number, book):
                        text, markers = _extract_markers(line.text)
                        shift = sum(len(part) + 1 for part in title_lines)
                        title_lines.append(_clean(text))
                        title_markers.extend(
                            Marker(shift + m.offset, m.number) for m in markers
                        )
                    continue
                if _is_title_line(line, number, book):
                    text, markers = _extract_markers(line.text)
                    shift = sum(len(part) + 1 for part in title_lines)
                    title_lines.append(_clean(text))
                    title_markers.extend(
                        Marker(shift + m.offset, m.number) for m in markers
                    )
                    continue
                for verse, chunk in _split_verses(line.text):
                    if verse is not None:
                        if verse not in records:
                            records[verse] = VerseRecord(
                                chapter=1, verse=str(verse), page=number
                            )
                            order.append(verse)
                        current = records[verse]
                        starts.append((line.y, verse))
                        if folios:
                            for folio in folios:
                                current.folios.append(
                                    Folio(label=folio.label, offset=0)
                                )
                            folios = []
                    if current is not None and chunk.strip():
                        _append(current, "hebrew", chunk)

            _attach_english(
                records, order, starts, english, number, book, document.anomalies
            )

        if title_lines:
            document.passages.append(
                Passage(
                    kind="book-title",
                    page=1,
                    hebrew=" ".join(title_lines),
                    chapter=None,
                    markers=title_markers,
                )
            )
        if heading:
            document.passages.append(
                Passage(
                    kind="chapter-title",
                    page=1,
                    hebrew=heading,
                    chapter=1,
                    markers=heading_markers,
                )
            )
        document.passages.insert(0, _title_page(pdf[0], decoder, profile))

    document.records = [records[key] for key in order]
    _finalise(document, profile)
    return document


def _is_title_line(line: Line, page_number: int, book: str) -> bool:
    """The two book titles are the only Hebrew above their first verse."""
    if book == "Luke":
        return page_number == 1 and any(is_hebrew(c) for c in line.text)
    return (
        page_number == LUKE_LAST_PAGE
        and LUKE_PAGE_10_BOTTOM <= line.y < JOHN_PAGE_10_TOP
        and any(is_hebrew(c) for c in line.text)
        and not CHAPTER_HEADING_RE.search(line.text)
    )


# The two columns are set side by side, so an English line belongs to the last
# Hebrew verse that opened at or above it.
_COLUMN_ALIGNMENT = 14.0


def _attach_english(
    records: dict[int, VerseRecord],
    order: list[int],
    starts: list[tuple[float, int]],
    lines: list[Line],
    page_number: int,
    book: str,
    anomalies: list[str],
) -> None:
    """Pair the translation column to the verses opened in the Hebrew column.

    The English column prints its own ``(N)`` markers, but they cannot be
    trusted: page 2 prints ``(3)`` twice where the second should read ``(4)``,
    which silently swallows a whole verse. The Hebrew column is authoritative,
    so English is paired by position and its markers are used only to check.
    """
    current: int | None = order[-1] if order else None
    for line in lines:
        if book_at(page_number, line.y) != book:
            continue
        if FOLIO_RE.search(line.text) or ENGLISH_HEADING_RE.match(line.text):
            continue
        above = [verse for y, verse in starts if y <= line.y + _COLUMN_ALIGNMENT]
        if above:
            current = above[-1]
        printed = VERSE_MARKER_RE.search(line.text)
        if printed is not None and above:
            number = int(printed.group(1))
            if number != current and number in records:
                anomalies.append(
                    f"{book} 1:{current}: translation column prints "
                    f"({number}) where the Hebrew column opens verse {current}"
                )
        for _verse, chunk in _split_verses(line.text):
            if current is None or not chunk.strip():
                continue
            _append(records[current], "english", chunk)


def _title_page(page: Any, decoder: Any, profile: BookProfile) -> Passage:
    """The edition's own title block, above the manuscript text."""
    lines = [
        line.text
        for line in page_lines(
            page,
            decoder,
            column="english",
            footer_top=profile.footer_top,
            column_split=profile.column_split,
            source="rawdict",
        )
        if line.y < 400 and not any(is_hebrew(char) for char in line.text)
    ]
    return Passage(
        kind="titlePage",
        page=1,
        english=" | ".join(_clean(line) for line in lines if _clean(line)),
    )


def _collect_notes(
    pdf: Any, decoder: Any, profile: BookProfile
) -> dict[str, str]:
    notes: dict[str, str] = {}
    last: str | None = None
    for page in pdf:
        leading, page_notes = footnote_definitions(
            page, decoder, footer_top=profile.footer_top, source="rawdict"
        )
        if leading and last is not None:
            notes[last] = _clean(f"{notes[last]} {leading}")
        for number, text in page_notes.items():
            notes[number] = re.sub(r"\s+([.,;:?])", r"\1", _clean(text))
            last = number
    return notes


def _finalise(document: Ebr530Document, profile: BookProfile) -> None:
    defined = set(document.notes)
    for record in document.records:
        record.hebrew = _clean(record.hebrew)
        record.english = _clean(record.english)
        for markers in (record.hebrew_markers, record.english_markers):
            unknown = [m.number for m in markers if m.number not in defined]
            record.excluded_markers.extend(unknown)
            markers[:] = [m for m in markers if m.number in defined]
    for passage in document.passages:
        passage.markers[:] = [
            m for m in passage.markers if m.number in defined
        ]
    used = {
        marker.number
        for record in document.records
        for marker in (*record.hebrew_markers, *record.english_markers)
    } | {
        marker.number
        for passage in document.passages
        for marker in passage.markers
    }
    # The PDF numbers its 22 notes across both books, so each book keeps only
    # the ones its own text refers to rather than carrying the other's.
    document.notes = {
        number: text for number, text in document.notes.items() if number in used
    }
    missing = used - defined
    for number in sorted(missing, key=int):
        document.anomalies.append(
            f"footnote {number} is referenced but has no definition"
        )
