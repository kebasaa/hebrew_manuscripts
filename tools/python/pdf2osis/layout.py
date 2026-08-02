"""Page geometry for two-column manuscript PDFs.

The Sloane 273 PDF is a Word table: the Hebrew transcription sits in the right
cell and its English translation in the left one, with footnotes below a drawn
separator rule. The rule moves between y=518 and y=621 depending on the page, so
its position is detected rather than hardcoded — a fixed band both swallowed
Revelation 1:18 and double-counted six body blocks as footnotes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .glyphs import GlyphDecoder, glyph_line_text, line_text, text_spans

# The gutter between the two table cells runs from x=304 to x=307.
COLUMN_SPLIT = 305.0

# The running footer (`© 2017 by Nehemia Gordon`, `ver. 2.0`) starts here.
FOOTER_TOP = 660.0

# A footnote separator is a short rule at the left margin, drawn 144 pt wide and
# well under a point thick. The table's own cell borders start at the same x and
# are almost as short — 233 pt in ebr. 530 — so the width band has to be tight
# or three of its pages report a separator that is really a cell edge.
_RULE_MAX_X0 = 80.0
_RULE_MIN_WIDTH = 100.0
_RULE_MAX_WIDTH = 200.0
_RULE_MIN_HEIGHT = 0.5
_RULE_MAX_HEIGHT = 3.0

# A definition number and the line it opens can round to different y values.
_NUMBER_LINE_TOLERANCE = 3.0

# Spans whose box tops differ by less than this belong to the same printed line.
LINE_TOLERANCE = 4.0


@dataclass(frozen=True)
class Line:
    y: float
    x0: float
    x1: float
    text: str
    spans: tuple[dict[str, Any], ...] = field(repr=False, default=())


@dataclass(frozen=True)
class Superscript:
    number: str
    page: int
    x: float
    y: float
    column: str


def footnote_rule_y(page: Any, footer_top: float = FOOTER_TOP) -> float:
    """The y of the footnote separator, or the footer top when there is none."""
    candidates = [
        drawing["rect"].y0
        for drawing in page.get_drawings()
        if drawing["rect"].x0 < _RULE_MAX_X0
        and _RULE_MIN_WIDTH < drawing["rect"].width < _RULE_MAX_WIDTH
        and _RULE_MIN_HEIGHT < drawing["rect"].height < _RULE_MAX_HEIGHT
    ]
    return max(candidates) if candidates else footer_top


def _spans_for(page: Any, source: str) -> list[dict[str, Any]]:
    if source == "texttrace":
        return text_spans(page)
    if source != "rawdict":
        raise ValueError(f"Unknown text source: {source}")
    return [
        span
        for block in page.get_text("rawdict")["blocks"]
        if block.get("type") == 0
        for line in block.get("lines", ())
        for span in line.get("spans", ())
        if span.get("chars")
    ]


def _group_by_baseline(
    spans: list[dict[str, Any]],
) -> list[tuple[float, list[dict[str, Any]]]]:
    """Group spans into printed lines, tolerating differing box tops.

    A superscript reference or a small definition number is set above its
    line's baseline, so its bounding box starts a point or two away from the
    body text beside it. Rounding the top to an integer therefore splits one
    printed line in two, which strands markers on lines of their own.
    """
    groups: list[tuple[float, list[dict[str, Any]]]] = []
    for span in sorted(spans, key=lambda item: item["bbox"][1]):
        top = span["bbox"][1]
        if groups and top - groups[-1][0] <= LINE_TOLERANCE:
            groups[-1][1].append(span)
            continue
        groups.append((top, [span]))
    return groups


def column_of(span: dict[str, Any], split: float = COLUMN_SPLIT) -> str:
    return "hebrew" if span["bbox"][0] >= split else "english"


# A footnote reference is set at roughly two-thirds of its column's body size
# (David 12.96 against 20.04, Times 10.56 against 16.0). texttrace does not
# expose rawdict's superscript flag, so the size ratio is the usable signal.
MARKER_SIZE_RATIO = 0.8


def is_superscript(span: dict[str, Any], text: str, body_size: float) -> bool:
    """Footnote references are set superscript, one size down from their run."""
    if not text.strip().isdigit():
        return False
    return span["size"] < body_size * MARKER_SIZE_RATIO


def body_size(page: Any, column: str) -> float:
    """The dominant type size of a column, used to spot superscripts."""
    sizes = [
        span["size"]
        for span in text_spans(page)
        if column_of(span) == column and span["bbox"][1] < footnote_rule_y(page)
    ]
    return max(sizes) if sizes else 0.0


def page_lines(
    page: Any,
    decoder: GlyphDecoder,
    *,
    column: str,
    region: str = "body",
    footer_top: float = FOOTER_TOP,
    column_split: float = COLUMN_SPLIT,
    source: str = "texttrace",
) -> list[Line]:
    """Group a page's spans into printed lines of decoded text.

    ``region`` is ``body`` (above the footnote rule), ``footnotes`` (below it and
    above the running footer) or ``all``.

    ``source`` selects the primitive. ``texttrace`` exposes glyph IDs, which is
    the only way to repair a broken ToUnicode CMap. ``rawdict`` exposes per-glyph
    geometry, which is what a font with no cmap at all needs; see
    :mod:`pdf2osis.glyphs`.
    """
    rule = footnote_rule_y(page, footer_top)
    fonts = decoder.page_fonts(page)
    selected: list[dict[str, Any]] = []
    for span in _spans_for(page, source):
        top = span["bbox"][1]
        if region == "body" and top >= rule:
            continue
        if region == "footnotes" and not (rule <= top < footer_top):
            continue
        if region == "all" and top >= footer_top:
            continue
        if column != "all" and column_of(span, column_split) != column:
            continue
        selected.append(span)

    lines: list[Line] = []
    for top, spans in _group_by_baseline(selected):
        text = (
            glyph_line_text(spans)
            if source == "rawdict"
            else line_text(spans, decoder, fonts)
        )
        if not text:
            continue
        lines.append(
            Line(
                y=round(float(top)),
                x0=min(span["bbox"][0] for span in spans),
                x1=max(span["bbox"][2] for span in spans),
                text=text,
                spans=tuple(spans),
            )
        )
    return lines


def superscripts(
    page: Any,
    decoder: GlyphDecoder,
    page_number: int,
    *,
    footer_top: float = FOOTER_TOP,
) -> list[Superscript]:
    """Footnote reference markers printed in the body text."""
    rule = footnote_rule_y(page, footer_top)
    fonts = decoder.page_fonts(page)
    sizes = {column: body_size(page, column) for column in ("hebrew", "english")}
    found: list[Superscript] = []
    for span in text_spans(page):
        if span["bbox"][1] >= rule:
            continue
        text = decoder.span_text(
            span, decoder.choose_cmap(span, fonts.get(span["font"], []))
        )
        if not is_superscript(span, text, sizes[column_of(span)]):
            continue
        found.append(
            Superscript(
                number=text.strip(),
                page=page_number,
                x=span["bbox"][0],
                y=span["bbox"][1],
                column=column_of(span),
            )
        )
    return found


def footnote_definitions(
    page: Any,
    decoder: GlyphDecoder,
    *,
    footer_top: float = FOOTER_TOP,
    source: str = "texttrace",
) -> tuple[str, dict[str, str]]:
    """Split the footnote area into ``{number: text}``.

    Returns the text preceding the first number as well: a note wrapping across
    a page boundary continues at the top of the next page's footnote area.
    """
    fonts = decoder.page_fonts(page)
    rule = footnote_rule_y(page, footer_top)
    starts: list[tuple[float, float, str]] = []
    for span in _spans_for(page, source):
        top = span["bbox"][1]
        if not (rule <= top < footer_top):
            continue
        if source == "rawdict":
            text = glyph_line_text([span])
        else:
            text = decoder.span_text(
                span, decoder.choose_cmap(span, fonts.get(span["font"], []))
            )
        # A definition opens with its number set alone at the left margin.
        if text.strip().isdigit() and span["bbox"][0] < _RULE_MAX_X0:
            starts.append((top, span["bbox"][0], text.strip()))

    lines = page_lines(
        page,
        decoder,
        column="all",
        region="footnotes",
        footer_top=footer_top,
        source=source,
    )
    # The number's own span and the line it opens do not always round to the
    # same y, so each number is matched to its nearest line rather than keyed
    # on an exact bucket.
    numbers: dict[int, str] = {}
    for top, _, number in sorted(starts, key=lambda item: item[0]):
        nearest = min(lines, key=lambda line: abs(line.y - top), default=None)
        if nearest is not None and abs(nearest.y - top) <= _NUMBER_LINE_TOLERANCE:
            numbers.setdefault(round(nearest.y), number)

    leading: list[str] = []
    notes: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        number = numbers.get(round(line.y))
        text = line.text
        if number is not None:
            current = number
            notes.setdefault(current, [])
            if text.startswith(number):
                text = text[len(number):].lstrip()
        if current is None:
            leading.append(text)
        else:
            notes[current].append(text)
    return (
        " ".join(leading).strip(),
        {number: " ".join(parts).strip() for number, parts in notes.items()},
    )
