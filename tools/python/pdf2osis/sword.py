"""Extraction from CrossWire SWORD Bible modules.

Every other extractor in this package reads a PDF's text layer, needing glyph
decoding (:mod:`pdf2osis.glyphs`) and page-layout detection
(:mod:`pdf2osis.layout`) to recover verses in the first place. A SWORD module
is not a PDF — it is a compressed, already verse-segmented database — so none
of that applies. :mod:`pysword` reads the module directly and returns clean
per-verse text, with any inline OSIS/GBF/ThML markup already stripped.

These modules are whole-Testament sources: one translation spanning 27 books,
not a fragment of one. `extract_sword_nt` returns all of them, keyed by OSIS
book abbreviation in canonical order, for :func:`pdf2osis.osis.build_multibook_osis`
to write as one file rather than 27 unrelated ones.

The module's own ``Versification`` declaration is the source of truth for how
many chapters and verses each book has; nothing here guesses it. A handful of
verses across the whole NT come back empty under that scheme (2 Cor 13:14,
3 John 1:15, Rev 12:18 in the Delitzsch module) — a known versification slot
the module's own text does not fill, not an extraction failure.
"""

from __future__ import annotations

from pathlib import Path

from pysword.canons import canons
from pysword.modules import SwordModules

from .models import VerseDocument, VerseRecord
from .profiles import BookProfile


def extract_sword_nt(source: Path, profile: BookProfile) -> dict[str, VerseDocument]:
    """Read every NT book in the module, keyed by OSIS book abbreviation."""
    modules = SwordModules(str(source))
    parsed = modules.parse_modules()
    bible = modules.get_bible_from_module(profile.sword_module)

    versification = parsed[profile.sword_module].get("versification", "kjv")
    testament = canons[versification.lower()]["nt"]

    books: dict[str, VerseDocument] = {}
    for name, osis_name, _abbr, chapter_lengths in testament:
        document = VerseDocument()
        for chapter, verse_count in enumerate(chapter_lengths, start=1):
            for verse in range(1, verse_count + 1):
                # The zText compression pads the last verse of most chapters
                # with trailing whitespace at the block boundary; strip it as
                # every other extractor in this package already does.
                hebrew = bible.get(
                    books=[name], chapters=[chapter], verses=[verse]
                ).strip()
                record = VerseRecord(
                    chapter=chapter, verse=str(verse), page=0, hebrew=hebrew
                )
                if not hebrew.strip():
                    record.empty = True
                    record.absence = (
                        f"{osis_name} {chapter}:{verse} is a versification "
                        f"slot ({versification}) the module's own text does "
                        "not fill."
                    )
                document.records.append(record)
        books[osis_name] = document
    return books
