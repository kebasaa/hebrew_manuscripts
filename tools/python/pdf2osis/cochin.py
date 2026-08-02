"""Extraction for the Project Truth Ministries Cochin editions.

Three PDFs, three layouts. They share a house style — a verse header, the Hebrew
transcription, an English translation, then comparison texts — but they do not
share a format, which is why one state machine could not hold them:

===========  =====  ======  =========================  ==========================
file         pages  verses  verse header               distinguishing feature
===========  =====  ======  =========================  ==========================
Revelation     380     406  ``Revelation N:V (…)``     interlinear gloss table
James           76     107  ``James N:V (KJV …)``      no interlinear table
Matthew        967     646  ``Chapter C:V``            Syriac Aramaic column
===========  =====  ======  =========================  ==========================

Each therefore gets its own extractor here, over shared line reading.

These editions are essentially unpointed — a few gershayim abbreviation marks
and almost no vowels — so the glyph repair the pointed manuscripts need does not
apply. What they do need is correct reading order: MuPDF ≥1.26 returns Hebrew in
logical order and merges the header, the Hebrew and the translation into one
block, which is what broke the previous extractor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import groupby
from pathlib import Path
from typing import Any, Callable, Iterable

import fitz

from .glyphs import glyph_line_text, is_hebrew, is_rtl_line, is_syriac
from .models import Marker, Passage, VerseRecord
from .profiles import BookProfile

NOTE_DIGIT_RE = re.compile(r"\d{1,3}")
FOOTNOTE_START_RE = re.compile(r"^\s*(\d{1,3})\s+(?=[A-Z“\"'(א-ת])")

# Labels that open a section. Everything from a comparison label up to the next
# verse header is other people's text and never enters the transcription.
# The edition sometimes offers alternatives, "Translation #1:" and
# "Translation #2:", so the label is matched rather than compared.
# The James edition prefixes its labels with the shelfmark.
TRANSLATION_LABEL_RE = re.compile(
    r"^\s*(?:Cochin\s+\S+\s+)?(?:English\s+|Hebrew\s+)?"
    r"Translation(?:\s*#\s*\d+)?\s*:",
    re.I,
)
# How an edition states that the manuscript lacks a verse. Anchored, because
# the phrase also occurs mid-sentence where it means nothing of the sort:
# Revelation 14:19's "verse 20 does not exist" is about the second half of a
# combined record, and Matthew 8:10 translates "there does not exist faith like
# this". Only a notice that *opens* the field is an assertion of absence.
ABSENCE_RE = re.compile(r"^\(?\s*(?:this verse\s+)?does not exist\b", re.I)
# A notice of a different kind: the verse is present, its position is not.
ORDER_NOTICE_RE = re.compile(r"changes the order", re.I)
# Labels after which the edition speaks about its own manuscript. The KJV and
# Aramaic columns also print "does not exist", but there it means the
# comparison text is missing, not the manuscript verse.
ABSENCE_LABEL_RE = re.compile(
    r"^\s*(?:Note|Transcription|Translation)\s*:\s*", re.I
)


def states_absent(text: str) -> str | None:
    """Return the notice where `text` asserts the manuscript lacks the verse."""
    label = ABSENCE_LABEL_RE.match(text)
    body = _clean(text[label.end():] if label else text)
    if not ABSENCE_RE.match(body):
        return None
    # The edition sets the notice in parentheses in some places and not others.
    return body[1:-1].strip() if body.startswith("(") and body.endswith(")") else body


def header_absence(text: str) -> str | None:
    """Same assertion, made inside a verse header's parenthetical.

    ``Revelation 2:6 (This verse does not exist in the Cochin Oo.1.16.2
    manuscript)``. The parenthetical otherwise holds the manuscript's own
    reference, which `parse_reference` reads.
    """
    for match in re.finditer(r"\(([^)]*)\)", text):
        if ABSENCE_RE.match(match.group(1).strip()):
            return _clean(match.group(1))
    return None
COMPARISON_LABELS = ("The Scriptures:", "Aramaic:", "Greek:", "KJV:")
TRANSCRIPTION_LABELS = (
    "Hebrew Transcription",
    "Transcription:",
    "Cochin Oo.1.32 Hebrew Transcription:",
)
INTERLINEAR_LABEL = "Interlinear"

# A superscript reference is set well below its line's dominant size.
DOMINANT_RATIO = 0.85


@dataclass
class CochinDocument:
    records: list[VerseRecord] = field(default_factory=list)
    notes: dict[str, str] = field(default_factory=dict)
    anomalies: list[str] = field(default_factory=list)
    # These editions print no material outside their verses, but the OSIS
    # builder is shared with the manuscripts that do.
    passages: list[Passage] = field(default_factory=list)


@dataclass(frozen=True)
class _Line:
    y: float
    x: float
    text: str
    size: float
    # The line with its smaller-set spans dropped. A verse header carries its
    # footnote marker glued to the verse number — "Revelation 1:117" is verse 1
    # with marker 17 — and only the type size tells them apart.
    dominant: str = ""

    @property
    def hebrew(self) -> bool:
        return any(is_hebrew(char) for char in self.text)

    @property
    def syriac(self) -> bool:
        return any(is_syriac(char) for char in self.text)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def page_lines(
    page: Any, top: float = 0.0, bottom: float = 1e9
) -> list[_Line]:
    """Every printed line on a page, in reading order, already decoded.

    ``top`` and ``bottom`` exclude the running header and footer. The footer
    reads "146 of 380", which is ordinary body-sized text, so leaving it in
    appends a page number to whatever verse the page ends on and turns its
    digits into footnote references.
    """
    lines: list[_Line] = []
    for block in page.get_text("rawdict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", ()):
            if not (top <= line["bbox"][1] < bottom):
                continue
            spans = [span for span in line["spans"] if span.get("chars")]
            if not spans:
                continue
            text = glyph_line_text(spans)
            if not text.strip():
                continue
            size = max(span["size"] for span in spans)
            larger = [
                span for span in spans if span["size"] >= size * DOMINANT_RATIO
            ]
            dominant = (
                glyph_line_text(larger) if len(larger) != len(spans) else text
            )
            # The largest span on a line is sometimes an empty one set for
            # leading, which would leave nothing behind to match a header on.
            if not dominant.strip():
                dominant = text
            lines.append(
                _Line(
                    y=line["bbox"][1],
                    x=line["bbox"][0],
                    text=text,
                    size=size,
                    dominant=dominant,
                )
            )
    # MuPDF now merges the header, the Hebrew and the translation into one
    # block, so blocks say nothing about order; sort by position instead. A
    # wide Hebrew line is often split into several pieces sharing a baseline,
    # and those read right to left, not left to right.
    ordered: list[_Line] = []
    for _key, group in groupby(
        sorted(lines, key=lambda item: round(item.y, 1)),
        key=lambda item: round(item.y, 1),
    ):
        row = list(group)
        rtl = is_rtl_line("".join(item.text for item in row))
        row.sort(key=lambda item: -item.x if rtl else item.x)
        ordered.extend(row)
    return ordered


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


def _append(record: VerseRecord, field_name: str, text: str) -> None:
    if record.empty:
        # The edition has said the manuscript lacks this verse. What follows is
        # its own notice about that, not the verse; it must not become text.
        return
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


def _starts_with(text: str, labels: Iterable[str]) -> str | None:
    for label in labels:
        if text.startswith(label):
            return label
    return None


def _translation_label(text: str) -> int | None:
    """Length of the translation label opening this line, if it has one."""
    match = TRANSLATION_LABEL_RE.match(text)
    return match.end() if match else None


def _collect_footnotes(lines: list[_Line], body_size: float) -> dict[str, str]:
    """Definitions are set below the body in a smaller face, numbered in order."""
    notes: dict[str, str] = {}
    current: str | None = None
    for line in lines:
        if line.size >= body_size:
            current = None
            continue
        match = FOOTNOTE_START_RE.match(line.text)
        if match:
            current = match.group(1)
            notes[current] = line.text[match.end():].strip()
        elif current is not None:
            notes[current] = _clean(f"{notes[current]} {line.text}")
    return notes


def _anchor_interlinear(record: VerseRecord, token: str, number: str) -> bool:
    """Place a marker taken from the interlinear table beside its own word.

    The gloss table repeats each transcription word, so a marker printed there
    can be put back where that word stands rather than dumped at the verse end.
    """
    token = token.strip()
    if not token:
        return False
    index = record.hebrew.find(token)
    if index < 0:
        return False
    record.hebrew_markers.append(Marker(offset=index + len(token), number=number))
    return True


def _canonical_key(record: VerseRecord) -> tuple[int, int, str]:
    match = re.match(r"(\d+)([a-z]*)", record.verse)
    return (record.chapter, int(match.group(1)), match.group(2))


def flag_reordered_verses(document: CochinDocument) -> None:
    """Mark verses the manuscript prints out of canonical sequence.

    These editions follow the manuscript's order, not the canonical one, so a
    transposition shows up as records whose position differs between the two.
    Revelation 2:21 and 2:22 are the only such pair in the corpus.
    """
    order = {id(record): index for index, record in enumerate(document.records)}
    for index, record in enumerate(sorted(document.records, key=_canonical_key)):
        if order[id(record)] != index:
            record.reordered = True
    moved = [r for r in document.records if r.reordered]
    if moved:
        document.anomalies.append(
            "printed out of canonical order: "
            + ", ".join(f"{r.chapter}:{r.verse}" for r in moved)
        )


def reconcile_with_interlinear(record: VerseRecord) -> int:
    """Correct single-glyph mis-decodings using the interlinear gloss table.

    The transcription and the gloss table are set in different subsets of the
    same face, and one of them sometimes resolves a letter the other gets
    wrong — he read as het, bet as kaf. Where a gloss repeats a transcription
    word at the same length and differs in exactly one letter, the gloss wins;
    anything less clear-cut is left alone, because the transcription is the
    authority on wording and order.
    """
    if not record.interlinear_hebrew or not record.hebrew:
        return 0
    glosses: dict[int, list[str]] = {}
    for token in record.interlinear_hebrew.split():
        glosses.setdefault(len(token), []).append(token)
    repaired = 0
    words = record.hebrew.split()
    for index, word in enumerate(words):
        if word in record.interlinear_hebrew:
            continue
        candidates = [
            gloss
            for gloss in glosses.get(len(word), ())
            if sum(a != b for a, b in zip(word, gloss)) == 1
        ]
        if len(candidates) == 1:
            words[index] = candidates[0]
            repaired += 1
    if repaired:
        record.hebrew = " ".join(words)
        record.extraction_disagreements.append(
            f"{repaired} letter(s) corrected against the interlinear table"
        )
    return repaired


def _finalise(
    document: CochinDocument, profile: BookProfile, notes: dict[str, str]
) -> None:
    flag_reordered_verses(document)
    for record in document.records:
        reconcile_with_interlinear(record)
    defined = set(notes)
    for record in document.records:
        record.hebrew = _clean(record.hebrew)
        record.english = _clean(record.english)
        for markers in (record.hebrew_markers, record.english_markers):
            unknown = sorted({m.number for m in markers if m.number not in defined})
            record.excluded_markers.extend(unknown)
            markers[:] = [m for m in markers if m.number in defined]
            markers.sort(key=lambda marker: marker.offset)
    used = {
        marker.number
        for record in document.records
        for marker in (*record.hebrew_markers, *record.english_markers)
    }
    # Every definition the source carries, referenced or not — the per-record
    # notes below are what actually reaches the OSIS, and an unreferenced
    # definition is reported rather than dropped silently.
    document.notes = dict(notes)
    for record in document.records:
        record.notes = {
            marker.number: notes[marker.number]
            for marker in (*record.hebrew_markers, *record.english_markers)
        }
    for number in sorted(defined - used, key=int):
        document.anomalies.append(f"footnote {number} is defined but unreferenced")


def _run(
    pdf_path: Path,
    profile: BookProfile,
    handle: Callable[..., None],
) -> CochinDocument:
    document = CochinDocument()
    notes: dict[str, str] = {}
    # A verse's translation routinely runs over a page break, so the section
    # state has to survive one; resetting it per page dropped the remainder.
    state = {"section": "idle"}
    with fitz.open(pdf_path) as pdf:
        first = max(profile.first_page, 0)
        last = min(profile.last_page, len(pdf) - 1)
        for index in range(first, last + 1):
            handle(
                document,
                page_lines(pdf[index], profile.header_y1, profile.footer_y0),
                index + 1,
                notes,
                state,
            )
    _finalise(document, profile, notes)
    return document


# --- Revelation ------------------------------------------------------------
#
# Type sizes carry the structure: the transcription is set larger than the
# translation, and the interlinear gloss table smaller again.
REV_TRANSCRIPTION_SIZE = 15.0
REV_INTERLINEAR_SIZE = (13.5, 14.5)
REV_BODY_SIZE = 10.5


def _rev_page(
    document: CochinDocument,
    lines: list[_Line],
    page: int,
    notes: dict[str, str],
    carried: dict[str, str],
) -> None:
    state = carried["section"]
    current = document.records[-1] if document.records else None
    body = [line for line in lines if line.size >= REV_BODY_SIZE]
    notes.update(_collect_footnotes(lines, REV_BODY_SIZE))

    for line in body:
        header = _rev_header(line)
        if header is not None:
            chapter, verse, source_verse, alt = header
            current = VerseRecord(
                chapter=chapter,
                verse=verse,
                page=page,
                source_verse=source_verse,
            )
            if alt is not None:
                current.alt_chapter, current.alt_verse = alt
            absence = header_absence(line.dominant)
            if absence is not None:
                current.empty = True
                current.absence = absence
            if carried.get("order_ref") == f"{chapter}:{verse}":
                current.order_note = carried.pop("order_note", None)
                carried.pop("order_ref", None)
            document.records.append(current)
            state = "transcription"
            continue
        if current is None:
            continue
        if ORDER_NOTICE_RE.search(line.text) and not current.hebrew:
            # The header above this notice is a signpost, not a verse: it marks
            # where the reference falls in canonical sequence and announces that
            # the manuscript prints the next few out of that order. The verse
            # itself is printed later, under the same reference.
            document.records.remove(current)
            carried["order_note"] = _clean(
                re.sub(r"^\s*Note\s*:\s*", "", line.text, flags=re.I)
            )
            carried["order_ref"] = f"{current.chapter}:{current.verse}"
            document.anomalies.append(
                f"{current.chapter}:{current.verse} heads an order notice rather "
                f"than a verse; the verse itself is printed later"
            )
            current = document.records[-1] if document.records else None
            state = "idle"
            continue

        absence = states_absent(line.text)
        if absence is not None:
            # The edition says in so many words that the manuscript has no such
            # verse; that is a fact about the source, not a gap in extraction.
            current.empty = True
            current.absence = absence

        label = _translation_label(line.text)
        if label is not None:
            state = "translation"
            _append(current, "english", line.text[label:])
            continue
        if _starts_with(line.text, COMPARISON_LABELS) is not None:
            state = "idle"
            continue
        if line.text.startswith(INTERLINEAR_LABEL) or _starts_with(
            line.text, TRANSCRIPTION_LABELS
        ) is not None:
            state = "idle" if line.text.startswith(INTERLINEAR_LABEL) else state
            continue

        if REV_INTERLINEAR_SIZE[0] <= line.size <= REV_INTERLINEAR_SIZE[1]:
            # A gloss cell repeats one transcription word; a marker printed
            # here belongs beside that word, and the word itself is a second
            # witness to glyphs the transcription's font decodes ambiguously.
            text, markers = _extract_markers(line.text)
            if line.hebrew:
                current.interlinear_hebrew = _clean(
                    f"{current.interlinear_hebrew} {text}"
                )
            for marker in markers:
                if not _anchor_interlinear(current, text, marker.number):
                    current.hebrew_markers.append(
                        Marker(offset=len(current.hebrew), number=marker.number)
                    )
            continue

        if line.size >= REV_TRANSCRIPTION_SIZE and line.hebrew:
            if state == "transcription":
                _append(current, "hebrew", line.text)
            continue
        if state == "translation" and not line.hebrew and not line.syriac:
            _append(current, "english", line.text)
    carried["section"] = state


def _rev_header(line: _Line) -> tuple[int, str, str | None, tuple[int, str] | None] | None:
    # Not filtered on type size: most headers are set at 12 pt but Revelation
    # 1:12 and 6:10 are not, and keying on size drops them. The anchored
    # pattern is enough — a cross-reference inside footnote prose never
    # occupies a whole line on its own.
    return parse_reference(line.dominant, "Revelation", "Cochin")


REFERENCE_RE_CACHE: dict[str, re.Pattern[str]] = {}


def parse_reference(
    text: str, book: str, alt_book: str | None
) -> tuple[int, str, str | None, tuple[int, str] | None] | None:
    """Parse a ``Book N:V (Alt N:V)`` header.

    A header may carry a footnote marker glued to it, and its verse may be a
    range that the edition treats as one record.
    """
    pattern = REFERENCE_RE_CACHE.get(book)
    if pattern is None:
        pattern = re.compile(
            rf"^{book}\s+(\d+):(\d+[a-z]?(?:-\d+[a-z]?)?)"
            r"(?:\s*\(([^)]*)\))?\s*\d{0,3}\s*$",
            re.I,
        )
        REFERENCE_RE_CACHE[book] = pattern
    match = pattern.match(text.strip())
    if match is None:
        return None
    chapter = int(match.group(1))
    # The edition sets some suffixes in capitals ("2:27A"); normalise so that
    # they sort and compare with the ones it sets in lower case.
    source_verse = match.group(2).lower()
    verse = source_verse.split("-")[0]
    alt: tuple[int, str] | None = None
    if alt_book and match.group(3):
        alt_match = re.search(
            rf"(?:{alt_book}|KJV)\s+(\d+):(\d+[a-z]?(?:-\d+[a-z]?)?)",
            match.group(3),
            re.I,
        )
        if alt_match:
            alt = (int(alt_match.group(1)), alt_match.group(2))
    return chapter, verse, source_verse if source_verse != verse else None, alt


def extract_cochin_rev(pdf_path: Path, profile: BookProfile) -> CochinDocument:
    return _run(pdf_path, profile, _rev_page)


# --- James -----------------------------------------------------------------
#
# No interlinear table, and the labels sit on their own lines above the text
# they introduce rather than inline with it.
JAS_HEADER_SIZE = 15.0
JAS_TRANSCRIPTION_SIZE = 13.0
JAS_BODY_SIZE = 11.5


def _jas_page(
    document: CochinDocument,
    lines: list[_Line],
    page: int,
    notes: dict[str, str],
    carried: dict[str, str],
) -> None:
    current = document.records[-1] if document.records else None
    state = carried["section"]
    notes.update(_collect_footnotes(lines, JAS_BODY_SIZE))

    for line in lines:
        if line.size < JAS_BODY_SIZE:
            continue
        if line.size >= JAS_HEADER_SIZE:
            header = parse_reference(line.dominant, "James", "KJV")
            if header is not None:
                chapter, verse, source_verse, alt = header
                current = VerseRecord(
                    chapter=chapter,
                    verse=verse,
                    page=page,
                    source_verse=source_verse,
                )
                if alt is not None:
                    current.alt_chapter, current.alt_verse = alt
                absence = header_absence(line.dominant)
                if absence is not None:
                    current.empty = True
                    current.absence = absence
                document.records.append(current)
                state = "idle"
                continue
        if current is None:
            continue
        absence = states_absent(line.text)
        if absence is not None:
            current.empty = True
            current.absence = absence
        if _starts_with(line.text, TRANSCRIPTION_LABELS) is not None:
            state = "transcription"
            continue
        label = _translation_label(line.text)
        if label is not None:
            state = "translation"
            _append(current, "english", line.text[label:])
            continue
        if _starts_with(line.text, COMPARISON_LABELS) is not None:
            state = "idle"
            continue
        if line.text.startswith("Image from Cochin"):
            continue
        if line.hebrew and line.size >= JAS_TRANSCRIPTION_SIZE:
            if state in {"transcription", "idle"}:
                _append(current, "hebrew", line.text)
            continue
        if state == "translation" and not line.hebrew:
            _append(current, "english", line.text.strip("“”"))
    carried["section"] = state


def extract_cochin_jas(pdf_path: Path, profile: BookProfile) -> CochinDocument:
    return _run(pdf_path, profile, _jas_page)


# --- Matthew ---------------------------------------------------------------
#
# Headed "Chapter C:V" rather than by book name, and printing a Syriac Aramaic
# column at the same type size as its English, so script rather than size
# separates them.
MAT_HEADER_RE = re.compile(r"^Chapter\s+(\d+):(\d+)\s*$")
MAT_TRANSCRIPTION_SIZE = 13.5
MAT_BODY_SIZE = 10.5


def _mat_page(
    document: CochinDocument,
    lines: list[_Line],
    page: int,
    notes: dict[str, str],
    carried: dict[str, str],
) -> None:
    current = document.records[-1] if document.records else None
    state = carried["section"]
    notes.update(_collect_footnotes(lines, MAT_BODY_SIZE))

    for line in lines:
        if line.size < MAT_BODY_SIZE:
            continue
        # As in Revelation, not every header is set at the same size, so the
        # anchored pattern rather than the type size decides.
        if True:
            match = MAT_HEADER_RE.match(line.dominant.strip())
            if match:
                current = VerseRecord(
                    chapter=int(match.group(1)),
                    verse=match.group(2),
                    page=page,
                )
                document.records.append(current)
                state = "transcription"
                continue
        if current is None or line.syriac:
            continue
        if (
            _starts_with(line.text, TRANSCRIPTION_LABELS) is not None
            or line.text.startswith(INTERLINEAR_LABEL)
        ):
            state = "idle"
            continue
        label = _translation_label(line.text)
        if label is not None:
            state = "translation"
            _append(current, "english", line.text[label:])
            continue
        if _starts_with(line.text, COMPARISON_LABELS) is not None:
            state = "idle"
            continue
        if line.hebrew and line.size >= MAT_TRANSCRIPTION_SIZE:
            if state == "transcription":
                _append(current, "hebrew", line.text)
            continue
        if state == "translation" and not line.hebrew:
            _append(current, "english", line.text)
    carried["section"] = state


def extract_cochin_mat(pdf_path: Path, profile: BookProfile) -> CochinDocument:
    return _run(pdf_path, profile, _mat_page)


EXTRACTORS = {
    "rev": extract_cochin_rev,
    "jas": extract_cochin_jas,
    "mat": extract_cochin_mat,
}


def extract_cochin(pdf_path: Path, profile: BookProfile) -> CochinDocument:
    """Dispatch to the extractor for this edition."""
    try:
        extractor = EXTRACTORS[profile.cochin_book]
    except KeyError as exc:
        raise ValueError(
            f"No Cochin extractor for {profile.cochin_book!r}"
        ) from exc
    return extractor(pdf_path, profile)
