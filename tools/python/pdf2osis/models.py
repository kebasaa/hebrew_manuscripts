from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Marker:
    offset: int
    number: str


@dataclass
class Folio:
    """A manuscript leaf boundary printed inside the transcription."""

    label: str
    offset: int = 0


@dataclass
class Passage:
    """Manuscript text that belongs to no numbered verse.

    Covers the incipit, the gate headings that divide the manuscript, and the
    edition's own title page. ``chapter`` is set when the passage introduces
    one, so it can be emitted as that chapter's title.
    """

    kind: str
    page: int
    hebrew: str = ""
    english: str = ""
    chapter: int | None = None
    markers: list[Marker] = field(default_factory=list)
    folios: list[Folio] = field(default_factory=list)


@dataclass
class VerseRecord:
    chapter: int
    verse: str
    page: int
    source_verse: str | None = None
    alt_chapter: int | None = None
    alt_verse: str | None = None
    empty: bool = False
    # The edition's own wording where it states the manuscript lacks this verse,
    # as printed. Its presence is what distinguishes a verse that is absent by
    # design from one this code failed to extract.
    absence: str | None = None
    # A notice printed against this verse about the manuscript's verse order.
    order_note: str | None = None
    # Set where the manuscript's sequence puts this verse out of canonical
    # order, so the transposition is readable without comparing neighbours.
    reordered: bool = False
    hebrew: str = ""
    english: str = ""
    hebrew_markers: list[Marker] = field(default_factory=list)
    english_markers: list[Marker] = field(default_factory=list)
    notes: dict[str, str] = field(default_factory=dict)
    interlinear_hebrew: str = ""
    extraction_disagreements: list[str] = field(default_factory=list)
    excluded_markers: list[str] = field(default_factory=list)
    # The manuscript's own verse number, written as a Hebrew letter-numeral.
    # It does not always agree with the printed edition's numbering.
    ms_number: int | None = None
    # Divisions the manuscript numbers but the edition leaves unnumbered.
    ms_divisions: list[Marker] = field(default_factory=list)
    folios: list[Folio] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.chapter}:{self.source_verse or self.verse}"


@dataclass
class VerseDocument:
    """A source read as plain, already-segmented verse text rather than a PDF.

    Same shape as ``cochin.CochinDocument`` — ``build_structured_osis`` only
    needs ``records``/``notes``/``anomalies``/``passages`` — kept as its own
    type here because a SWORD module has nothing else in common with a Cochin
    PDF extraction.
    """

    records: list[VerseRecord] = field(default_factory=list)
    notes: dict[str, str] = field(default_factory=dict)
    anomalies: list[str] = field(default_factory=list)
    passages: list[Passage] = field(default_factory=list)
