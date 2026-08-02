"""Glyph-accurate text decoding for Hebrew manuscript PDFs.

The corpus has two opposite font failure modes, so there are two primitives:

*Sloane 237* embeds ``David`` as a Type0/Identity-H subset whose ToUnicode CMap
covers only 30 of the ~170 glyph IDs in use, several of them wrongly — the sheva
glyph decodes as dagesh, hiriq and qubuts as a shin dot, hataf segol as a space.
That is ~12% of the Hebrew, and it is why naive extraction produced more shin
dots than shins. Its embedded ``cmap`` table *is* correct, so :func:`line_text`
reads glyph IDs from :meth:`~fitz.Page.get_texttrace` and resolves them there.

*Vatican ebr. 530* is the mirror image: its ToUnicode is sound but its embedded
subsets carry **no ``cmap`` table at all**, and ``get_texttrace`` merges adjacent
runs — and sometimes two printed lines — into one span, so reversing a span
swaps its runs. For that PDF :func:`dict_lines` uses ``get_text("dict")``, whose
runs already arrive in logical order (16–26% character error drops to 3–8%).

Both paths share the mark-attachment, ordering and joining helpers below.
"""

from __future__ import annotations

import io
import re
import unicodedata
from typing import Any

from fontTools.ttLib import TTFont

# Glyphs carrying no cmap entry at all, keyed by base font name. The same three
# ligatures appear in both pointed manuscripts at different glyph IDs; without
# them, 24 of Sloane's 25 final kafs are lost.
MANUAL_GLYPHS: dict[str, dict[int, str]] = {
    "David": {
        89: "v",
        205: "ךְ",  # kaf sofit + sheva
        206: "ךָ",  # kaf sofit + qamats
        207: "לֹ",  # lamed + holam
    },
    "TimesNewRomanPSMT": {
        706: "ךְ",
        707: "ךָ",
        708: "לֹ",
    },
    "TimesNewRomanPS-BoldMT": {
        706: "ךְ",
        707: "ךָ",
        708: "לֹ",
    },
}

# ebr. 530's unmapped Identity-H CIDs surface in `dict` output as these, which
# is more informative than texttrace's U+FFFD.
UNMAPPED_CIDS = {
    "˂": "ךְ",
    "˃": "ךָ",
    "˄": "לֹ",
    "�": "",
}

# Paired punctuation is stored as the glyph that was drawn, so an RTL run needs
# the usual bidi mirroring applied to it.
MIRRORED = str.maketrans("[](){}<>", "][)(}{><")

PRESENTATION_FIRST = 0xFB1D
PRESENTATION_LAST = 0xFB4F
PUA_FIRST = 0xE000
PUA_LAST = 0xF8FF

_CMAP_SUBTABLES = ((3, 1), (0, 3), (3, 0))

# Letters within a word touch; a word gap is a fraction of the type size.
WORD_GAP_RATIO = 0.10


class GlyphDecoder:
    """Decodes a document's glyphs using each embedded font's own cmap."""

    def __init__(self, document: Any) -> None:
        self._document = document
        self._cmaps: dict[int, dict[int, str]] = {}
        self._fonts: dict[int, dict[str, int]] = {}

    def cmap(self, xref: int) -> dict[int, str]:
        if xref not in self._cmaps:
            self._cmaps[xref] = self._load(xref)
        return self._cmaps[xref]

    def _load(self, xref: int) -> dict[int, str]:
        if not xref:
            return {}
        table: dict[int, str] = {}
        try:
            buffer = self._document.extract_font(xref, info_only=False)[3]
            font = TTFont(io.BytesIO(buffer))
            order = {name: gid for gid, name in enumerate(font.getGlyphOrder())}
            # Subset fonts are sometimes stripped of their cmap entirely — ebr.
            # 530's Hebrew has glyf but no cmap — so this lookup must be guarded
            # too, not just the font parse.
            for subtable in font["cmap"].tables:
                if (subtable.platformID, subtable.platEncID) not in _CMAP_SUBTABLES:
                    continue
                for codepoint, name in subtable.cmap.items():
                    gid = order.get(name)
                    if gid is None:
                        continue
                    if gid in table and PUA_FIRST <= codepoint <= PUA_LAST:
                        continue
                    table[gid] = chr(codepoint)
        except Exception:
            # Non-embedded fonts (Times, Arial) use a standard encoding that
            # MuPDF already decodes correctly, and cmap-less subsets have
            # nothing to offer; fall back to MuPDF's own Unicode.
            return {}
        return table

    def page_fonts(self, page: Any) -> dict[str, list[int]]:
        """Map the font names used in texttrace spans to their xrefs.

        A page can embed several subsets under one base name — Sloane 273 uses
        ``David`` for both the pointed Hebrew and a digits-only subset — and
        texttrace reports only the name, so all candidates are kept and the
        right one is chosen per span by :meth:`span_text`.
        """
        key = page.number
        if key not in self._fonts:
            mapping: dict[str, list[int]] = {}
            for entry in page.get_fonts():
                xref, base = entry[0], entry[3]
                if self.cmap(xref):
                    mapping.setdefault(base.split("+")[-1], []).append(xref)
            self._fonts[key] = mapping
        return self._fonts[key]

    def choose_cmap(
        self, span: dict[str, Any], xrefs: list[int]
    ) -> dict[int, str]:
        """Pick the subset that best explains this span's glyphs.

        Every glyph is scored on whether the subset's own cmap agrees with
        MuPDF about the character's general category. The correct subset agrees
        almost everywhere; a wrong one turns digits into vowel points.
        """
        if not xrefs:
            return {}
        if len(xrefs) == 1:
            return self.cmap(xrefs[0])
        best: dict[int, str] = {}
        best_score = float("-inf")
        for xref in xrefs:
            table = self.cmap(xref)
            score = 0
            for ucs, gid, _origin, _bbox in span["chars"]:
                if gid == -1:
                    continue
                char = table.get(gid)
                if char is None:
                    score -= 1
                    continue
                expected = unicodedata.category(chr(ucs))[0]
                score += 1 if unicodedata.category(char[0])[0] == expected else 0
            if score > best_score:
                best_score, best = score, table
        return best

    def span_text(
        self,
        span: dict[str, Any],
        cmap: dict[int, str],
        *,
        reverse_neutral: bool = False,
    ) -> str:
        """Decode one texttrace span into logical order.

        ``reverse_neutral`` says the span sits in an RTL line. Spans of purely
        neutral characters — brackets, punctuation, a stray combining mark —
        carry no bidi level of their own but are still laid out right to left,
        whereas an embedded digit run keeps its left-to-right order.
        """
        manual = MANUAL_GLYPHS.get(span.get("font", ""), {})
        pieces: list[str] = []
        for ucs, gid, _origin, _bbox in span["chars"]:
            if gid == -1:
                # MuPDF's own expansion of a glyph it could not map cleanly.
                # The glyph itself is decoded below, so this would duplicate it.
                continue
            char = cmap.get(gid) if cmap else None
            if char is None:
                char = manual.get(gid)
            if char is None:
                char = chr(ucs)
            pieces.append(decompose(char))
        reverse = bool(span.get("bidi_lvl", 0) % 2)
        if reverse_neutral and not reverse:
            strong = any(
                char.isascii() and char.isalnum()
                for piece in pieces
                for char in piece
            )
            reverse = not strong
        if reverse:
            pieces.reverse()
        return "".join(pieces)


def decompose(char: str) -> str:
    """Expand a Hebrew presentation form into its base and marks.

    NFD is not enough: ``U+FB20`` HEBREW LETTER ALTERNATIVE AYIN has a
    *compatibility* decomposition, so canonical decomposition leaves it standing.
    It occurs 48 times in ebr. 530 and is the sole reason 42 raw ``U+FB20``
    survive into the committed output.
    """
    if len(char) == 1 and PRESENTATION_FIRST <= ord(char) <= PRESENTATION_LAST:
        return unicodedata.normalize("NFKD", char)
    return UNMAPPED_CIDS.get(char, char)


def is_syriac(char: str) -> bool:
    """Cochin Matthew prints a Syriac Aramaic column beside its Hebrew."""
    return "܀" <= char <= "ݏ"


def is_hebrew(char: str) -> bool:
    return "֐" <= char <= "׿" or "יִ" <= char <= "ﭏ"


def is_rtl_line(text: str) -> bool:
    """A line is RTL when Hebrew outweighs Latin among its strong characters.

    Vowel points are not counted: a footnote quoting one pointed Hebrew word
    inside an English sentence has more Hebrew codepoints than Latin ones, but
    is still a left-to-right line.
    """
    rtl = sum(
        1
        for char in text
        if (is_hebrew(char) or is_syriac(char))
        and not unicodedata.combining(char)
    )
    latin = sum(1 for char in text if char.isascii() and char.isalpha())
    return rtl > latin


def is_mark_only(text: str) -> bool:
    """True for a span that carries nothing but combining marks.

    Such spans are emitted with a leading space when the writer could not place
    the mark inside its base letter's run, so spaces are ignored here.
    """
    stripped = text.replace(" ", "")
    return bool(stripped) and all(
        unicodedata.combining(char) for char in stripped
    )


def order_marks(text: str) -> str:
    """Put each base's combining marks into canonical order, then compose."""
    out: list[str] = []
    index = 0
    while index < len(text):
        base = text[index]
        index += 1
        marks: list[str] = []
        while index < len(text) and unicodedata.combining(text[index]):
            marks.append(text[index])
            index += 1
        marks.sort(key=unicodedata.combining)
        out.append(base + "".join(marks))
    return unicodedata.normalize("NFC", "".join(out))


def join_pieces(entries: list[tuple[dict[str, Any], str]], *, rtl: bool) -> str:
    """Concatenate ordered span texts.

    Word gaps are carried by real space glyphs, sometimes in a span of their
    own. Those are authoritative; the geometric gap is only a fallback for spans
    that are set apart without one. A space is never kept before a combining
    mark, which is how a word split across spans loses its false gap.
    """
    out = ""
    previous: dict[str, Any] | None = None
    pending = False
    for span, text in entries:
        if not text.strip():
            pending = pending or bool(out)
            continue
        if previous is None or not out:
            out = text.lstrip(" ")
            previous = span
            pending = False
            continue
        if rtl:
            gap = previous["bbox"][0] - span["bbox"][2]
        else:
            gap = span["bbox"][0] - previous["bbox"][2]
        width = max(span.get("spacewidth") or 0.0, 1.0)
        spaced = (
            pending
            or out.endswith(" ")
            or text.startswith(" ")
            or gap > width * 0.5
        )
        out = out.rstrip(" ")
        text = text.lstrip(" ")
        if spaced and not unicodedata.combining(text[0]):
            out += " "
        out += text
        previous = span
        pending = False
    return out


def _attach_marks(
    entries: list[tuple[dict[str, Any], str]],
) -> list[tuple[dict[str, Any], str]]:
    """Fold mark-only spans into the span carrying their base letter.

    A combining mark is drawn with zero advance width at its base letter's pen
    position, which in an RTL run is the base's left edge — that is, the x0 of
    the span whose final logical character is that base. The writer emits these
    strays sharing both the sequence number and the x0 of that span.
    """
    marks = [item for item in entries if is_mark_only(item[1])]
    if not marks:
        return entries
    hosts = [item for item in entries if not is_mark_only(item[1])]
    if not hosts:
        return entries
    merged = {id(span): text for span, text in hosts}
    for span, text in marks:
        x = span["bbox"][0]
        seqno = span["seqno"]
        host = min(
            hosts,
            key=lambda item: (
                item[0]["seqno"] != seqno,
                abs(item[0]["bbox"][0] - x),
            ),
        )
        merged[id(host[0])] += text.replace(" ", "")
    return [(span, merged[id(span)]) for span, _ in hosts]


def _order_rtl_runs(
    entries: list[tuple[dict[str, Any], str]],
) -> list[tuple[dict[str, Any], str]]:
    """Reverse each stretch of RTL spans inside a left-to-right line.

    An English footnote quoting Hebrew lays its runs out left to right, but the
    spans making up one Hebrew quotation still read right to left among
    themselves.
    """
    out: list[tuple[dict[str, Any], str]] = []
    run: list[tuple[dict[str, Any], str]] = []
    for entry in entries:
        if entry[0].get("bidi_lvl", 0) % 2:
            run.append(entry)
            continue
        if run:
            out.extend(reversed(run))
            run = []
        out.append(entry)
    out.extend(reversed(run))
    return out


def _rehome_leading_marks(
    entries: list[tuple[dict[str, Any], str]],
) -> list[tuple[dict[str, Any], str]]:
    """Move a span's leading combining marks onto the preceding span.

    A mark drawn at the very start of a run has its base at the end of the run
    before it — the writer emits these when a vowel point falls next to the
    punctuation that closes a verse.
    """
    out: list[tuple[dict[str, Any], str]] = []
    for span, text in entries:
        prefix_len = 0
        while prefix_len < len(text) and unicodedata.combining(text[prefix_len]):
            prefix_len += 1
        if prefix_len and out and out[-1][1].strip():
            previous_span, previous_text = out[-1]
            out[-1] = (previous_span, previous_text + text[:prefix_len])
            text = text[prefix_len:]
        out.append((span, text))
    return out


def line_text(
    spans: list[dict[str, Any]],
    decoder: GlyphDecoder,
    fonts: dict[str, list[int]],
) -> str:
    """Assemble one printed line of spans into logical-order text."""
    cmaps = {
        id(span): decoder.choose_cmap(span, fonts.get(span["font"], []))
        for span in spans
    }
    # Direction is decided from the characters present, which does not depend on
    # their order, so a first pass without the neutral rule is enough.
    rtl = is_rtl_line(
        "".join(decoder.span_text(span, cmaps[id(span)]) for span in spans)
    )
    entries = [
        (span, decoder.span_text(span, cmaps[id(span)], reverse_neutral=rtl))
        for span in spans
    ]
    entries = _attach_marks(entries)
    # Runs are laid out along the page in the paragraph's direction; the glyphs
    # inside each RTL run were already reversed above.
    entries.sort(key=lambda item: -item[0]["bbox"][0] if rtl else item[0]["bbox"][0])
    if not rtl:
        entries = _order_rtl_runs(entries)
    entries = _rehome_leading_marks(entries)
    text = join_pieces(entries, rtl=rtl)
    if rtl:
        text = text.translate(MIRRORED)
    return order_marks(re.sub(r"\s+", " ", text).strip())


class _Cluster:
    """One drawn glyph: a base letter plus any marks it decomposed into."""

    __slots__ = ("base", "marks", "x0", "x1", "size")

    def __init__(
        self, base: str, marks: list[str], x0: float, x1: float, size: float
    ) -> None:
        self.base, self.marks = base, marks
        self.x0, self.x1, self.size = x0, x1, size

    def text(self) -> str:
        return self.base + "".join(
            sorted(self.marks, key=unicodedata.combining)
        )


def _is_ltr_base(char: str) -> bool:
    return char.isascii() and char.isalnum()


# A mark's pen position usually coincides with its base's left edge, but a
# narrow vowel under a wide letter can be centred instead, landing several
# points inside it.
_MARK_EDGE_TOLERANCE = 0.5


def _mark_distance(cluster: _Cluster, x: float) -> tuple[int, float]:
    """Rank a candidate base for a floating mark drawn at ``x``.

    Containment comes first: a mark drawn inside a letter's own span belongs to
    that letter even when a neighbour's left edge is nearer. Among the letters
    that contain it, the one whose left edge is closest wins, which resolves the
    ties that arise where two letters touch.
    """
    contains = cluster.x0 - _MARK_EDGE_TOLERANCE <= x <= cluster.x1
    return (0 if contains else 1, abs(cluster.x0 - x))


def glyph_line_text(spans: list[dict[str, Any]]) -> str:
    """Rebuild a printed line from ``rawdict`` glyph geometry.

    ``get_texttrace`` merges adjacent runs — and in ebr. 530 sometimes two
    printed lines — into a single span, so reversing a span swaps its runs. Here
    every glyph is placed by its own coordinates instead.

    Combining marks are emitted with zero advance width at their base letter's
    left edge, so a mark's ``x0`` matches its base's ``x0`` to within a fraction
    of a point. That makes attachment exact rather than a nearest-neighbour
    guess.
    """
    clusters: list[_Cluster] = []
    floating: list[tuple[str, float]] = []
    for span in spans:
        font = span.get("font", "")
        manual = MANUAL_GLYPHS.get(font, {})
        size = float(span.get("size") or 0.0)
        for char in span.get("chars", ()):
            raw = char["c"]
            x0, x1 = char["bbox"][0], char["bbox"][2]
            expanded = decompose(manual.get(char.get("gid", -1), raw))
            if not expanded:
                continue
            if unicodedata.combining(expanded[0]):
                for mark in expanded:
                    floating.append((mark, x0))
                continue
            clusters.append(
                _Cluster(expanded[0], list(expanded[1:]), x0, x1, size)
            )
    if not clusters:
        return ""

    # A mark can only belong to a letter. Space glyphs sit between words at
    # coordinates that would otherwise win the contest and swallow the vowel of
    # the following word.
    hosts = [c for c in clusters if not c.base.isspace()] or clusters
    # Rightmost first, so that where two marks fall in the overlap between
    # neighbouring letters the logically earlier one gets first choice.
    for mark, x in sorted(floating, key=lambda item: -item[1]):
        # A letter never carries the same point twice, so a letter that already
        # has this mark cannot be the host — which is what separates the two
        # qamatsin of הָיָה, whose glyphs overlap by half a point.
        free = [c for c in hosts if mark not in c.marks] or hosts
        host = min(free, key=lambda c: _mark_distance(c, x))
        host.marks.append(mark)

    # Word gaps are re-derived from the glyph positions below, so the space
    # glyphs themselves — which the writer also emits mid-word when it splits a
    # word across spans — are dropped.
    clusters = [c for c in clusters if not c.base.isspace()]
    if not clusters:
        return ""

    rtl = is_rtl_line("".join(c.base for c in clusters))
    clusters.sort(key=lambda c: -c.x0 if rtl else c.x0)
    # Runs of the opposite direction — digits inside Hebrew, a Hebrew quotation
    # inside an English footnote — read the other way among themselves.
    ordered: list[_Cluster] = []
    run: list[_Cluster] = []
    for cluster in clusters:
        opposed = _is_ltr_base(cluster.base) if rtl else is_hebrew(cluster.base)
        if opposed:
            run.append(cluster)
            continue
        if run:
            ordered.extend(reversed(run))
            run = []
        ordered.append(cluster)
    ordered.extend(reversed(run))

    pieces: list[str] = []
    previous: _Cluster | None = None
    for cluster in ordered:
        if previous is not None:
            gap = min(
                abs(previous.x0 - cluster.x1), abs(cluster.x0 - previous.x1)
            )
            # A word gap is most of a space glyph's width, which scales with the
            # type size: 24 pt Hebrew body against 10 pt footnote text.
            size = max(cluster.size, previous.size, 1.0)
            if gap > size * WORD_GAP_RATIO:
                pieces.append(" ")
        pieces.append(cluster.text())
        previous = cluster
    text = "".join(pieces)
    if rtl:
        text = text.translate(MIRRORED)
    return order_marks(re.sub(r"\s+", " ", text).strip())


def text_spans(page: Any) -> list[dict[str, Any]]:
    return [
        span
        for span in page.get_texttrace()
        if span.get("type") == 0 and span.get("chars")
    ]
