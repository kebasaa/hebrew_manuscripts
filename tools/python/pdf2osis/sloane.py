"""Extraction for British Library MS Sloane 273 (Revelation 1:1–2:13).

This PDF is laid out quite differently from the Cochin editions handled by
:mod:`pdf2osis.extract`: there are no ``Revelation N:V`` headers to drive a
state machine, only a two-column table whose right cell carries a continuous
pointed Hebrew transcription with bracketed verse numbers, and whose left cell
carries the running English translation.

Besides the verses it recovers the material that belongs to no verse at all —
the manuscript incipit, the gate heading dividing the two chapters, the folio
boundaries and the manuscript's own Hebrew letter-numerals.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz

from .glyphs import GlyphDecoder, is_hebrew
from .layout import Line, footnote_definitions, page_lines, superscripts
from .models import Folio, Marker, Passage, VerseRecord
from .profiles import BookProfile

# A verse number is bracketed. The brackets are mirrored glyphs whose drawn
# order is not always the logical one, so both forms are accepted, along with a
# sof pasuq that belongs to the end of the preceding verse.
VERSE_MARKER_RE = re.compile(r"[\[\]]\s*([:׃])?\s*(\d{1,3})\s*[\[\]]+")
# At most one closing bracket, so that an adjacent verse marker such as
# "[3r][14]" keeps its own opening bracket. The brackets are optional because a
# short line can interleave the label with the numeral beside it ("[ א1r]").
FOLIO_RE = re.compile(r"[\[\]]?\s*(\d{1,3}[rv])\s*[\[\]]?")
STRAY_BRACKET_RE = re.compile(r"\s*[\[\]]\s*")
CHAPTER_RE = re.compile(r"Revelation\s*-?\s*Chapter\s+(\d+)", re.I)
ENGLISH_MARKER_RE = re.compile(
    r"\(\s*(\d{1,3})\s*\)|(?<![\w.])(\d{1,3})\.\s+(?=[A-Z])"
)
NOTE_DIGIT_RE = re.compile(r"\d{1,3}")

GEMATRIA = {
    "א": 1, "ב": 2, "ג": 3, "ד": 4, "ה": 5, "ו": 6, "ז": 7, "ח": 8, "ט": 9,
    "י": 10, "כ": 20, "ל": 30, "מ": 40, "נ": 50, "ס": 60, "ע": 70, "פ": 80,
    "צ": 90, "ק": 100, "ר": 200, "ש": 300, "ת": 400,
}


@dataclass
class SloaneDocument:
    records: list[VerseRecord] = field(default_factory=list)
    passages: list[Passage] = field(default_factory=list)
    notes: dict[str, str] = field(default_factory=dict)
    anomalies: list[str] = field(default_factory=list)


def gematria(token: str) -> int | None:
    """Value of an unpointed Hebrew letter-numeral, or None if it is not one.

    The manuscript is fully pointed, so a token carrying no vowel marks at all
    is a numeral rather than a word. Note that it uses the non-standard ``יו``
    for 16 in place of ``טז``.
    """
    if not token or any(unicodedata.combining(char) for char in token):
        return None
    if not all(char in GEMATRIA for char in token):
        return None
    return sum(GEMATRIA[char] for char in token)


# The transcription repeats a word's first letter at a line break, so a line can
# begin with a bare unpointed letter that is a catchword, not a numeral. A real
# numeral tracks the verse it belongs to, so only values close to the printed
# verse number are accepted when the position alone is not decisive.
NUMERAL_TOLERANCE = 3


def _take_numeral(
    text: str, limit: int, near: int | None = None
) -> tuple[int | None, str]:
    """Strip a leading letter-numeral from ``text``."""
    parts = text.split(" ", 1)
    value = gematria(parts[0])
    if value is None or not 1 <= value <= limit:
        return None, text
    if near is not None and abs(value - near) > NUMERAL_TOLERANCE:
        return None, text
    return value, parts[1] if len(parts) > 1 else ""


def _base_letter(token: str) -> str:
    return next(
        (char for char in unicodedata.normalize("NFD", token)
         if not unicodedata.combining(char)),
        "",
    )


def _split_numerals(
    text: str, limit: int, verse: int
) -> tuple[str, list[tuple[int, int]]]:
    """Remove the manuscript's letter-numerals, returning them with offsets.

    A bare unpointed letter is either one of these numerals or a catchword —
    the repetition of the next word's first letter across a line break. A
    catchword is followed by a word starting with the same letter, and a
    numeral tracks the verse number, so the two are told apart on both counts.
    """
    tokens = text.split(" ")
    kept: list[str] = []
    found: list[tuple[int, int]] = []
    for index, token in enumerate(tokens):
        value = gematria(token)
        following = tokens[index + 1] if index + 1 < len(tokens) else ""
        catchword = bool(following) and _base_letter(following) == _base_letter(token)
        if (
            value is not None
            and 1 <= value <= limit
            and abs(value - verse) <= NUMERAL_TOLERANCE
            and not catchword
        ):
            found.append((len(" ".join(kept)), value))
            continue
        kept.append(token)
    return " ".join(kept), found


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


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", STRAY_BRACKET_RE.sub(" ", text)).strip()


@dataclass
class _Chunk:
    """One stretch of transcription between two verse markers."""

    verse: int | None
    text: str
    page: int
    folios: list[Folio] = field(default_factory=list)
    ms_number: int | None = None


def _split_line(line: Line, page: int) -> list[_Chunk]:
    """Break a printed line at its verse markers and folio labels."""
    text = line.text
    folios: list[Folio] = []

    def take_folio(match: re.Match[str]) -> str:
        folios.append(Folio(label=match.group(1)))
        return " "

    text = FOLIO_RE.sub(take_folio, text)

    chunks: list[_Chunk] = []
    cursor = 0
    leading = True
    for match in VERSE_MARKER_RE.finditer(text):
        before = text[cursor:match.start()]
        if match.group(1):
            # The sof pasuq printed before the bracket closes the prior verse.
            before += match.group(1)
        if _clean(before) or leading:
            chunks.append(_Chunk(verse=None, text=before, page=page))
        chunks.append(_Chunk(verse=int(match.group(2)), text="", page=page))
        cursor = match.end()
        leading = False
    tail = text[cursor:]
    if chunks:
        chunks[-1].text += tail
    else:
        chunks.append(_Chunk(verse=None, text=tail, page=page))
    if folios:
        chunks[0].folios.extend(folios)
    return chunks


def _english_segments(lines: list[Line]) -> list[tuple[int | None, float, str]]:
    """Split the translation column at its verse markers."""
    out: list[tuple[int | None, float, str]] = []
    for line in lines:
        text = line.text
        cursor = 0
        current: int | None = None
        for match in ENGLISH_MARKER_RE.finditer(text):
            before = text[cursor:match.start()]
            if _clean(before):
                out.append((current, line.y, before))
            current = int(match.group(1) or match.group(2))
            out.append((current, line.y, ""))
            cursor = match.end()
        tail = text[cursor:]
        if _clean(tail):
            out.append((current, line.y, tail))
    return out


def extract_sloane(pdf_path: Path, profile: BookProfile) -> SloaneDocument:
    document = SloaneDocument()
    records: dict[tuple[int, int], VerseRecord] = {}
    order: list[tuple[int, int]] = []

    with fitz.open(pdf_path) as pdf:
        decoder = GlyphDecoder(pdf)
        notes = _collect_notes(pdf, decoder)
        document.notes = notes

        chapter = 1
        current: VerseRecord | None = None
        pending_passage: Passage | None = None
        # Reference markers found geometrically, as a check on the ones read
        # out of the running text.
        printed_markers: set[str] = set()

        for index, page in enumerate(pdf):
            number = index + 1
            headings = _chapter_headings(page, decoder)
            hebrew_lines = page_lines(page, decoder, column="hebrew")
            english_lines = page_lines(page, decoder, column="english")

            # The gate heading and the chapter heading sit below the last verse
            # of the preceding chapter, so headings are applied after the page.
            heading_y = headings[0][0] if headings else None
            printed_markers.update(
                mark.number for mark in superscripts(page, decoder, number)
            )

            starts: list[tuple[float, tuple[int, int]]] = []
            for line in hebrew_lines:
                if heading_y is not None and line.y >= heading_y:
                    continue  # belongs to the gate passage, not to a verse
                for chunk in _split_line(line, number):
                    if chunk.verse is not None:
                        verse = chunk.verse
                        key = (chapter, verse)
                        if key not in records:
                            record = VerseRecord(
                                chapter=chapter, verse=str(verse), page=number
                            )
                            records[key] = record
                            order.append(key)
                        current = records[key]
                        starts.append((line.y, key))
                        value, rest = _take_numeral(
                            _clean(chunk.text), profile.expected_verses
                        )
                        if value is not None:
                            current.ms_number = value
                        chunk.text = rest
                    if current is None:
                        # Front matter above the first verse marker.
                        pending_passage = pending_passage or Passage(
                            kind="incipit", page=number
                        )
                        text, markers = _extract_markers(chunk.text)
                        shift = (
                            len(pending_passage.hebrew) + 1
                            if pending_passage.hebrew
                            else 0
                        )
                        pending_passage.hebrew = _clean(
                            f"{pending_passage.hebrew} {text}"
                        )
                        for marker in markers:
                            pending_passage.markers.append(
                                Marker(
                                    offset=min(
                                        shift + marker.offset,
                                        len(pending_passage.hebrew),
                                    ),
                                    number=marker.number,
                                )
                            )
                        pending_passage.folios.extend(chunk.folios)
                        continue
                    if chunk.text.strip() or chunk.folios:
                        _append_hebrew(
                            current, chunk, profile.expected_verses
                        )

            _attach_english(records, starts, english_lines, chapter, order)

            for y, value in headings:
                chapter = value
                if value > 1:
                    document.passages.append(
                        _gate_passage(hebrew_lines, english_lines, y, number, value)
                    )

        if pending_passage is not None:
            document.passages.insert(0, pending_passage)
        document.passages.insert(0, _title_page(pdf[0], decoder))

    document.records = [records[key] for key in order]
    _finalise(document, profile, printed_markers)
    return document


def _append_hebrew(record: VerseRecord, chunk: _Chunk, limit: int) -> None:
    text, markers = _extract_markers(chunk.text)
    text = _clean(text)
    text, numerals = _split_numerals(text, limit, int(record.verse))
    for offset, value in numerals:
        if not record.hebrew and offset == 0 and record.ms_number is None:
            # The manuscript's numeral for this verse, printed on the line
            # after the edition's bracketed number.
            record.ms_number = value
        else:
            # A numeral inside the text marks a division the edition left
            # unnumbered; keep it as a milestone rather than as text.
            base = len(record.hebrew) + (1 if record.hebrew else 0)
            record.ms_divisions.append(
                Marker(offset=base + offset, number=str(value))
            )
    if record.hebrew and text:
        shift = len(record.hebrew) + 1
        record.hebrew = f"{record.hebrew} {text}"
    elif text:
        shift = 0
        record.hebrew = text
    else:
        # A reference marker printed on a line of its own leaves no text.
        shift = len(record.hebrew)
    for marker in markers:
        record.hebrew_markers.append(
            Marker(offset=min(shift + marker.offset, len(record.hebrew)),
                   number=marker.number)
        )
    for folio in chunk.folios:
        record.folios.append(Folio(label=folio.label, offset=len(record.hebrew)))


def _attach_english(
    records: dict[tuple[int, int], VerseRecord],
    starts: list[tuple[float, tuple[int, int]]],
    lines: list[Line],
    chapter: int,
    order: list[tuple[int, int]],
) -> None:
    if not records:
        return
    for verse, y, text in _english_segments(lines):
        key: tuple[int, int] | None = None
        if verse is not None and (chapter, verse) in records:
            key = (chapter, verse)
        else:
            candidates = [item for item in starts if item[0] <= y + 12]
            if candidates:
                key = candidates[-1][1]
            elif order:
                key = order[-1]
        if key is None:
            continue
        record = records[key]
        cleaned, markers = _extract_markers(text)
        cleaned = _clean(cleaned)
        # A reference marker is often set on a line of its own, leaving no text
        # once it is removed. The marker still belongs to this verse.
        shift = len(record.english) + 1 if record.english else 0
        if cleaned:
            record.english = _clean(f"{record.english} {cleaned}")
        for marker in markers:
            record.english_markers.append(
                Marker(offset=min(shift + marker.offset, len(record.english)),
                       number=marker.number)
            )


def _chapter_headings(page: Any, decoder: GlyphDecoder) -> list[tuple[float, int]]:
    found: list[tuple[float, int]] = []
    for line in page_lines(page, decoder, column="all"):
        match = CHAPTER_RE.search(line.text)
        if match:
            found.append((line.y, int(match.group(1))))
    return found


def _gate_passage(
    hebrew_lines: list[Line],
    english_lines: list[Line],
    heading_y: float,
    page: int,
    chapter: int,
) -> Passage:
    """The Hebrew gate heading printed just below a chapter heading."""
    hebrew = next(
        (line.text for line in hebrew_lines if line.y > heading_y), ""
    )
    english = next(
        (line.text for line in english_lines if line.y > heading_y), ""
    )
    return Passage(
        kind="gate",
        page=page,
        hebrew=_clean(hebrew),
        english=_clean(english),
        chapter=chapter,
    )


def _title_page(page: Any, decoder: GlyphDecoder) -> Passage:
    """The edition's own title block, above the manuscript incipit."""
    lines = [
        line.text
        for line in page_lines(page, decoder, column="english")
        if line.y < 300 and not any(is_hebrew(char) for char in line.text)
    ]
    return Passage(
        kind="titlePage",
        page=1,
        english=" | ".join(_clean(line) for line in lines if _clean(line)),
    )


def _collect_notes(pdf: Any, decoder: GlyphDecoder) -> dict[str, str]:
    notes: dict[str, str] = {}
    last: str | None = None
    for page in pdf:
        leading, page_notes = footnote_definitions(page, decoder)
        if leading and last is not None:
            notes[last] = _clean(f"{notes[last]} {leading}")
        for number, text in page_notes.items():
            # A Hebrew quotation ending a note leaves a gap before the stop.
            notes[number] = re.sub(r"\s+([.,;:])", r"\1", _clean(text))
            last = number
    return notes


def _finalise(
    document: SloaneDocument,
    profile: BookProfile,
    printed_markers: set[str],
) -> None:
    defined = set(document.notes)
    for record in document.records:
        record.hebrew = _clean(record.hebrew)
        record.english = _clean(record.english)
        for markers in (record.hebrew_markers, record.english_markers):
            unknown = [m.number for m in markers if m.number not in defined]
            for number in unknown:
                record.excluded_markers.append(number)
            markers[:] = [m for m in markers if m.number in defined]
        if record.ms_number is not None and record.ms_number != int(record.verse):
            document.anomalies.append(
                f"{profile.osis_book}.{record.chapter}.{record.verse}: "
                f"manuscript numeral {record.ms_number} disagrees with the "
                f"printed verse number {record.verse}"
            )
    for passage in document.passages:
        passage.markers[:] = [m for m in passage.markers if m.number in defined]
    used = {
        marker.number
        for record in document.records
        for marker in (*record.hebrew_markers, *record.english_markers)
    } | {
        marker.number
        for passage in document.passages
        for marker in passage.markers
    }
    for number in sorted(defined - used, key=int):
        document.anomalies.append(f"footnote {number} is defined but unreferenced")
    # Every superscript printed in the body should have been recovered from the
    # running text; a gap means a marker was read as part of a word.
    for number in sorted(printed_markers - used, key=int):
        if number in defined:
            document.anomalies.append(
                f"footnote {number} is printed in the body but was not anchored"
            )
