from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from lxml import etree

from .models import Marker, Passage, VerseRecord
from .profiles import BookProfile

# `footnote` is not one of the OSIS 2.1.1 note types; `explanation` is the
# closest standard value for an editor's remarks on the manuscript.
NOTE_TYPE = "explanation"

# Passage kinds that open a book: Sloane's manuscript incipit, ebr. 530's
# gospel heading. Both become a <title type="main"> inside an introduction div.
BOOK_TITLE_KINDS = {"incipit", "book-title"}
# Kinds that introduce a chapter: Sloane's gate heading, ebr. 530's פרק ראשון.
CHAPTER_TITLE_KINDS = {"gate", "chapter-title"}

#: Every variant this module can build, in increasing order of apparatus. Not
#: the same as what a profile publishes — `BookProfile.output_names()` decides
#: that, and drops the bare `hebrew` wherever a translation covers the same
#: transcription. The apparatus-free variant stays buildable regardless: it is
#: what shows that the notes really are confined to the annotated variants.
VARIANTS = ("hebrew", "hebrew_commented", "translation")

OSIS_NS = "http://www.bibletechnologies.net/2003/OSIS/namespace"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
SCHEMA_LOCATION = (
    f"{OSIS_NS} http://www.bibletechnologies.net/osisCore.2.1.1.xsd"
)


def _tag(name: str) -> str:
    return f"{{{OSIS_NS}}}{name}"


def _work(
    header: etree._Element,
    work_id: str,
    title: str,
    language: str,
    profile: BookProfile,
    *,
    translation: bool = False,
    commented: bool = False,
) -> None:
    # OSIS fixes the order of a work's children: title, contributor, creator,
    # subject, date, description, publisher, type, format, identifier, source,
    # language, relation, coverage, rights, scope, castList, teiHeader,
    # refSystem. Emitting them out of order fails schema validation. `rights`
    # is written twice — copyright, then license — which the schema allows
    # (rightsCT permits repetition), and both still land in this one slot.
    work = etree.SubElement(header, _tag("work"), osisWork=work_id)
    etree.SubElement(work, _tag("title")).text = title

    def add_translator_credit() -> None:
        etree.SubElement(
            work,
            _tag("contributor"),
            role="ctb",
            **{"file-as": profile.contributor_file_as},
        ).text = profile.contributor
        etree.SubElement(work, _tag("creator"), role="trl").text = (
            profile.translator
        )

    def add_original_date() -> None:
        etree.SubElement(
            work,
            _tag("date"),
            event="original",
            type=profile.date_calendar,
        ).text = profile.original_date

    def add_edition_date() -> None:
        etree.SubElement(work, _tag("date"), event="eversion", type="ISO").text = (
            profile.edition_date
        )

    if not profile.has_translation:
        # There is no separate translation variant to carry these, because the
        # Hebrew text here is itself the translation (Delitzsch, from Greek) —
        # unlike a manuscript, which just exists with no translator to credit.
        add_translator_credit()
        add_original_date()
        add_edition_date()
    elif translation:
        add_translator_credit()
        add_edition_date()
    else:
        add_original_date()
    etree.SubElement(work, _tag("description")).text = profile.description
    for kind, text in profile.descriptions:
        etree.SubElement(work, _tag("description"), type=kind).text = text
    # The five cataloguing fields, always all five, in this order. They are the
    # vocabulary Milah's transcription tab writes and src/build_manifest.py
    # reads into a column apiece. An unanswered one is written empty rather than
    # left out: to a reader looking for the folios of a manuscript, a missing
    # element and an empty one say the same nothing, and the empty one at least
    # records that the question was asked and has no published answer.
    for kind, text in (
        ("x-folios", profile.folios),
        ("x-material", profile.material),
        ("x-provenance", profile.provenance),
        ("x-translated-from", profile.translated_from),
        ("x-exemplar", profile.exemplar),
    ):
        # `or None` so an unanswered field serialises self-closing.
        etree.SubElement(work, _tag("description"), type=kind).text = text or None
    etree.SubElement(work, _tag("publisher")).text = profile.publisher
    is_edition = translation or not profile.has_translation
    etree.SubElement(
        work,
        _tag("type"),
        type="x-bible" if is_edition else "x-manuscript",
    ).text = "Edition" if is_edition else "Manuscript"
    etree.SubElement(work, _tag("identifier"), type="OSIS").text = work_id
    etree.SubElement(work, _tag("identifier"), type="x-shelfmark").text = (
        profile.manuscript
    )
    etree.SubElement(work, _tag("identifier"), type="URI").text = (
        profile.alt_namespace
    )
    for source in profile.sources:
        etree.SubElement(work, _tag("source")).text = source
    etree.SubElement(work, _tag("language")).text = language
    if profile.relation:
        etree.SubElement(work, _tag("relation")).text = profile.relation
    if profile.coverage:
        etree.SubElement(work, _tag("coverage")).text = profile.coverage
    # Two <rights>, always both present — the schema allows more than one
    # (rightsCT permits `type` and maxOccurs="unbounded") — because copyright
    # and license are different questions with different answers.
    #
    # Copyright: who holds it, stated on the translation (or the sole variant,
    # when there is none) and on the commented Hebrew transcription too, where
    # a named person or publisher did that commenting — Gordon's annotations,
    # PTM's interlinear apparatus. The bare, uncommented Hebrew variant of a
    # source that also has a translation carries none: nobody in particular is
    # credited with producing it. Empty rather than absent, so a reader sees
    # that this was considered and answered "nobody", not skipped.
    if translation or not profile.has_translation or commented:
        copyright_text = profile.rights
    else:
        copyright_text = ""
    etree.SubElement(work, _tag("rights"), type="x-copyright").text = copyright_text

    # License: what a reader may do with it. Never empty, unlike copyright
    # above: what the source itself states about reuse, verbatim, or this
    # repository's own stated default when the source said nothing at all —
    # never invented, and never silently loosened past a stricter term
    # (Gordon's "All rights reserved.", the Bible Society in Israel's outright
    # refusal) the source did state.
    etree.SubElement(work, _tag("rights"), type="x-license").text = profile.license
    etree.SubElement(work, _tag("scope")).text = profile.scope


def _header(
    osis_text: etree._Element,
    profile: BookProfile,
    work_id: str,
    language: str,
    *,
    translation: bool,
    commented: bool = False,
) -> None:
    header = etree.SubElement(osis_text, _tag("header"))
    title = profile.translation_title if translation else profile.title
    _work(
        header,
        work_id,
        title,
        language,
        profile,
        translation=translation,
        commented=commented,
    )
    bible = etree.SubElement(header, _tag("work"), osisWork="bible")
    etree.SubElement(bible, _tag("title")).text = (
        "Referenced versification (standard)"
    )
    etree.SubElement(bible, _tag("identifier"), type="OSIS").text = "bible"
    etree.SubElement(bible, _tag("language")).text = language
    etree.SubElement(bible, _tag("refSystem")).text = "StandardV11N"


class _Flow:
    """Appends text and elements to a parent, keeping mixed content in order."""

    def __init__(self, parent: etree._Element) -> None:
        self.parent = parent
        self.last: etree._Element | None = None

    def add_text(self, text: str) -> None:
        if not text:
            return
        if self.last is None:
            self.parent.text = (self.parent.text or "") + text
        else:
            self.last.tail = (self.last.tail or "") + text

    def add(self, name: str, **attributes: str) -> etree._Element:
        element = etree.SubElement(self.parent, _tag(name), **attributes)
        self.last = element
        return element


def _anchored(
    flow: _Flow,
    text: str,
    anchors: list[tuple[int, Callable[[_Flow], None]]],
) -> None:
    """Write ``text`` into ``flow``, emitting each anchor at its offset."""
    cursor = 0
    for offset, emit in sorted(anchors, key=lambda item: item[0]):
        offset = max(cursor, min(offset, len(text)))
        flow.add_text(text[cursor:offset])
        emit(flow)
        cursor = offset
    flow.add_text(text[cursor:])


def _note_anchors(
    markers: Iterable[Marker],
    notes: dict[str, str],
    osis_id: str,
) -> list[tuple[int, Callable[[_Flow], None]]]:
    anchors: list[tuple[int, Callable[[_Flow], None]]] = []
    seen: set[tuple[int, str]] = set()
    for marker in sorted(markers, key=lambda item: item.offset):
        key = (marker.offset, marker.number)
        if key in seen or marker.number not in notes:
            continue
        seen.add(key)

        def emit(flow: _Flow, marker: Marker = marker) -> None:
            note = flow.add(
                "note",
                type=NOTE_TYPE,
                placement="foot",
                n=marker.number,
                osisRef=osis_id,
                osisID=f"{osis_id}!note.{marker.number}",
            )
            note.text = notes[marker.number]

        anchors.append((marker.offset, emit))
    return anchors


def _editorial_anchors(
    record: VerseRecord, osis_id: str
) -> list[tuple[int, Callable[[_Flow], None]]]:
    """Notes the edition makes about a verse without printing a marker for it.

    An absence notice ("This verse does not exist in the Cochin manuscript") and
    an order notice have no superscript to anchor to, so they open the verse.
    Without them an empty verse is indistinguishable from a failed extraction.
    """
    anchors: list[tuple[int, Callable[[_Flow], None]]] = []
    for suffix, text in (("absent", record.absence), ("order", record.order_note)):
        if not text:
            continue

        def emit(flow: _Flow, suffix: str = suffix, text: str = text) -> None:
            note = flow.add(
                "note",
                type=NOTE_TYPE,
                placement="foot",
                osisRef=osis_id,
                osisID=f"{osis_id}!note.{suffix}",
            )
            note.text = text

        anchors.append((0, emit))
    return anchors


def _source_reference(record: VerseRecord) -> str | None:
    """The source's own reference for a verse, if it states one."""
    if record.ms_number is not None:
        return str(record.ms_number)
    if record.alt_chapter is not None and record.alt_verse is not None:
        return f"{record.alt_chapter}.{record.alt_verse}"
    return None


def indent_body(book: etree._Element, depth: int = 3) -> None:
    """Lay the book div out one verse per line.

    lxml's ``pretty_print`` refuses to reformat any element holding mixed
    content, and milestone form makes the whole book div exactly that — so
    without this the entire book arrives as a single line thousands of
    characters long. Tails are set by hand instead, on the elements that end a
    line: a verse's closing milestone, a chapter milestone, and the titles and
    divs between them. ``verse[@sID]`` never gets one, because its text follows
    immediately.

    The whitespace lands outside every verse, so it cannot enter verse text.
    """
    inner = "\n" + "  " * (depth + 1)
    closing = "\n" + "  " * depth
    children = list(book)
    if not children:
        return
    book.text = inner
    for child in children:
        name = etree.QName(child).localname
        ends_line = (
            name in {"chapter", "title", "div"}
            or (name == "verse" and child.get("eID"))
        )
        if ends_line:
            child.tail = (child.tail or "") + inner
    last = children[-1]
    last.tail = (last.tail or "").rstrip() + closing


def _passage_text(passage: Passage, *, translation: bool) -> str:
    return passage.english if translation else passage.hebrew


def _write_book(
    osis_text: etree._Element,
    osis_book: str,
    document: Any,
    *,
    translation: bool,
    with_notes: bool,
) -> None:
    """Write one book's div — verses, chapters, titles, folios, notes.

    Shared by `build_structured_osis` (one book per file) and
    `build_multibook_osis` (many books, one `osis_text` per file): the body of
    a book div does not care how many siblings it has.
    """
    book = etree.SubElement(
        osis_text,
        _tag("div"),
        type="book",
        osisID=osis_book,
        canonical="true",
    )
    flow = _Flow(book)
    notes = document.notes if with_notes else {}

    for passage in document.passages:
        if passage.kind not in BOOK_TITLE_KINDS:
            continue
        text = _passage_text(passage, translation=translation)
        if not text:
            continue
        div = flow.add("div", type="introduction", canonical="true")
        for folio in passage.folios:
            etree.SubElement(div, _tag("milestone"), type="pb", n=folio.label)
        title = etree.SubElement(
            div, _tag("title"), type="main", canonical="true"
        )
        inner = _Flow(title)
        _anchored(
            inner,
            text,
            _note_anchors(passage.markers, notes, osis_book),
        )

    titles = {
        passage.chapter: passage
        for passage in document.passages
        if passage.kind in CHAPTER_TITLE_KINDS and passage.chapter is not None
    }

    chapter: int | None = None
    for record in document.records:
        if record.chapter != chapter:
            if chapter is not None:
                flow.add("chapter", eID=f"{osis_book}.{chapter}")
            chapter = record.chapter
            passage = titles.get(chapter)
            if passage is not None:
                text = _passage_text(passage, translation=translation)
                if text:
                    element = flow.add(
                        "title", type="chapter", canonical="true"
                    )
                    element.text = text
            flow.add(
                "chapter",
                sID=f"{osis_book}.{chapter}",
                osisID=f"{osis_book}.{chapter}",
                n=str(chapter),
            )

        osis_id = f"{osis_book}.{record.chapter}.{record.verse}"
        attributes = {
            "sID": osis_id,
            "osisID": osis_id,
            # The printed label, which for a combined record is a range.
            "n": record.source_verse or record.verse,
        }
        # How the source itself refers to this verse, where that differs from
        # the canonical reference: Sloane's Hebrew letter-numerals, Cochin's own
        # chapter and verse. OSIS has no second numbering attribute, so this
        # rides on subType, whose values must begin with `x-`.
        alt = _source_reference(record)
        if alt is not None:
            attributes["subType"] = f"x-alt-{alt}"
        # These editions follow the manuscript's verse order, not the canonical
        # one. `type` is a separate attributeExtension from `subType`, so the
        # transposition is flagged without displacing the source reference, and
        # unlike a note it survives into the variants that carry no apparatus.
        if record.reordered:
            attributes["type"] = "x-reordered"
        flow.add("verse", **attributes)

        raw = record.english if translation else record.hebrew
        markers = record.english_markers if translation else record.hebrew_markers
        anchors = _note_anchors(markers, notes, osis_id)
        if with_notes:
            anchors = _editorial_anchors(record, osis_id) + anchors
        if not translation:
            for folio in record.folios:
                def emit_folio(inner: _Flow, folio: Any = folio) -> None:
                    inner.add("milestone", type="pb", n=folio.label)

                anchors.append((folio.offset, emit_folio))
            for division in record.ms_divisions:
                def emit_division(inner: _Flow, division: Any = division) -> None:
                    inner.add("milestone", type="x-ms-verse", n=division.number)

                anchors.append((division.offset, emit_division))
        _anchored(flow, raw, anchors)
        flow.add("verse", eID=osis_id)

    if chapter is not None:
        flow.add("chapter", eID=f"{osis_book}.{chapter}")

    indent_body(book)


def _start_document(
    profile: BookProfile, variant: str, variants: set[str]
) -> tuple[etree._Element, etree._Element, bool, bool]:
    if variant not in variants:
        raise ValueError(f"Unknown OSIS variant: {variant}")
    translation = variant == "translation"
    commented = variant == "hebrew_commented"
    with_notes = variant in {"hebrew_commented", "translation"}
    suffix = {
        "hebrew": "",
        "hebrew_commented": "_Commented",
    }
    work_id = (
        profile.translation_work
        if translation
        else profile.hebrew_work + suffix[variant]
    )
    language = "en" if translation else "he"

    root = etree.Element(_tag("osis"), nsmap={None: OSIS_NS, "xsi": XSI_NS})
    root.set(f"{{{XSI_NS}}}schemaLocation", SCHEMA_LOCATION)
    osis_text = etree.SubElement(
        root,
        _tag("osisText"),
        osisIDWork=work_id,
        osisRefWork="bible",
    )
    osis_text.set(XML_LANG, language)
    _header(
        osis_text, profile, work_id, language,
        translation=translation, commented=commented,
    )
    return root, osis_text, translation, with_notes


def build_structured_osis(
    document: Any, profile: BookProfile, variant: str
) -> bytes:
    """Build OSIS for a pointed manuscript, using milestoned verses.

    Milestone form is required here because the manuscript carries material
    that belongs to no verse — an incipit, a gate heading dividing the two
    chapters, and folio boundaries that fall in mid-verse — which cannot be
    represented while every verse is a container.
    """
    root, osis_text, translation, with_notes = _start_document(
        profile, variant, set(VARIANTS)
    )

    for passage in document.passages:
        if passage.kind != "titlePage":
            continue
        text = _passage_text(passage, translation=True)
        if not text:
            continue
        div = etree.SubElement(
            osis_text, _tag("div"), type="titlePage", canonical="false"
        )
        for index, part in enumerate(text.split(" | ")):
            etree.SubElement(
                div, _tag("title"), type="main" if index == 0 else "sub"
            ).text = part

    _write_book(
        osis_text, profile.osis_book, document,
        translation=translation, with_notes=with_notes,
    )
    return etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", pretty_print=True
    )


def build_multibook_osis(
    books: dict[str, Any], profile: BookProfile, variant: str
) -> bytes:
    """Build OSIS for a source spanning many books in one file.

    For a whole-Bible or whole-Testament source — a SWORD module, say — 27
    separate one-book files would scatter a single translation across 27
    unrelated documents for no reason a reader of that translation would
    recognise; one `osisText` holding one `div type="book"` per book, in
    canonical order, is what the source actually is.
    """
    root, osis_text, translation, with_notes = _start_document(
        profile, variant, {"hebrew", "hebrew_commented"}
    )
    for osis_book, document in books.items():
        _write_book(
            osis_text, osis_book, document,
            translation=translation, with_notes=with_notes,
        )
    return etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", pretty_print=True
    )

