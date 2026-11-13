"""The books of the Bible as OSIS knows them, shared by both manifest generators.

Milah groups its library by testament and by book, and it does so by OSIS book
id — ``Jas``, ``John``, ``Matt`` — because that is what every verse inside every
text is already keyed by. The filenames in ``manuscripts/`` and the ``book``
column of ``src/scan_links.tsv`` use short upper-case codes instead (``JAS``,
``JOH``, ``MAT``), which read well in a folder listing but match nothing inside
a file. This module is the one place the two are reconciled, so a code added to
one generator cannot be missing from the other.

What is here
------------

``BOOKS``
    Every book in canonical order: its OSIS id, its testament (``ot`` or
    ``nt``), and — where it is settled enough to state — the references its last
    verse can carry. Deuterocanonical books are ``ot``; their chapter structure
    differs between traditions (Greek Esther, Daniel's additions), so no ending
    is stated for them and a witness to one is judged only on starting at 1:1
    and skipping no chapter.

``book_id(code)``
    The OSIS id a filename prefix or link-list code names, or ``""``.

``category_of(book)``
    ``"ot"``, ``"nt"``, or ``""`` for an id this table does not know.

``covers(refs)``
    A list of verse references collapsed into ranges.

``complete(refs, book)``
    Whether a set of verse references is the whole of a book.

Endings, and why more than one
------------------------------

Whether a witness is a fragment is decided by asking whether it reaches from
the book's first verse to its last, through every chapter. The last verse is
not the same in every versification: Hebrew Bibles end Malachi at 3:24 where
the KJV has 4:6, and the NRSV versification Delitzsch's New Testament follows
ends 2 Corinthians at 13:13 where the KJV has 13:14. A witness ending at either
is whole, so both are listed. A gap *inside* a book is deliberately not looked
for: James in MS Oo.1.32 has no independent 2:26 because the edition's 2:15
spans two KJV verses, and calling that a fragment would be wrong about the
manuscript in order to be right about a numbering scheme.
"""

from __future__ import annotations

import re
from typing import Iterable, NamedTuple

CATEGORIES = ("ot", "nt", "other")


class Book(NamedTuple):
    osis: str
    #: The code a filename or the scan link list uses: Paratext's, except where
    #: this repository settled on another before this table existed (JOH).
    code: str
    category: str
    #: Every "chapter.verse" the book's last verse is numbered as somewhere.
    #: Empty where no single answer is honest to give.
    endings: tuple[str, ...] = ()


BOOKS: tuple[Book, ...] = (
    Book("Gen", "GEN", "ot", ("50.26",)),
    Book("Exod", "EXO", "ot", ("40.38",)),
    Book("Lev", "LEV", "ot", ("27.34",)),
    Book("Num", "NUM", "ot", ("36.13",)),
    Book("Deut", "DEU", "ot", ("34.12",)),
    Book("Josh", "JOS", "ot", ("24.33",)),
    Book("Judg", "JDG", "ot", ("21.25",)),
    Book("Ruth", "RUT", "ot", ("4.22",)),
    Book("1Sam", "1SA", "ot", ("31.13",)),
    Book("2Sam", "2SA", "ot", ("24.25",)),
    Book("1Kgs", "1KI", "ot", ("22.53", "22.54")),
    Book("2Kgs", "2KI", "ot", ("25.30",)),
    Book("1Chr", "1CH", "ot", ("29.30",)),
    Book("2Chr", "2CH", "ot", ("36.23",)),
    Book("Ezra", "EZR", "ot", ("10.44",)),
    Book("Neh", "NEH", "ot", ("13.31",)),
    Book("Esth", "EST", "ot", ("10.3",)),
    Book("Job", "JOB", "ot", ("42.17",)),
    Book("Ps", "PSA", "ot", ("150.6",)),
    Book("Prov", "PRO", "ot", ("31.31",)),
    Book("Eccl", "ECC", "ot", ("12.14",)),
    Book("Song", "SNG", "ot", ("8.14",)),
    Book("Isa", "ISA", "ot", ("66.24",)),
    Book("Jer", "JER", "ot", ("52.34",)),
    Book("Lam", "LAM", "ot", ("5.22",)),
    Book("Ezek", "EZK", "ot", ("48.35",)),
    Book("Dan", "DAN", "ot", ("12.13",)),
    Book("Hos", "HOS", "ot", ("14.9", "14.10")),
    Book("Joel", "JOL", "ot", ("3.21", "4.21")),
    Book("Amos", "AMO", "ot", ("9.15",)),
    Book("Obad", "OBA", "ot", ("1.21",)),
    Book("Jonah", "JON", "ot", ("4.11",)),
    Book("Mic", "MIC", "ot", ("7.20",)),
    Book("Nah", "NAM", "ot", ("3.19",)),
    Book("Hab", "HAB", "ot", ("3.19",)),
    Book("Zeph", "ZEP", "ot", ("3.20",)),
    Book("Hag", "HAG", "ot", ("2.23",)),
    Book("Zech", "ZEC", "ot", ("14.21",)),
    Book("Mal", "MAL", "ot", ("4.6", "3.24")),
    # Deuterocanonical and other books some canons hold. Testament only.
    Book("Tob", "TOB", "ot"),
    Book("Jdt", "JDT", "ot"),
    Book("EsthGr", "ESG", "ot"),
    Book("AddEsth", "ADE", "ot"),
    Book("Wis", "WIS", "ot"),
    Book("Sir", "SIR", "ot"),
    Book("Bar", "BAR", "ot"),
    Book("EpJer", "LJE", "ot"),
    Book("PrAzar", "S3Y", "ot"),
    Book("Sus", "SUS", "ot"),
    Book("Bel", "BEL", "ot"),
    Book("1Macc", "1MA", "ot"),
    Book("2Macc", "2MA", "ot"),
    Book("3Macc", "3MA", "ot"),
    Book("4Macc", "4MA", "ot"),
    Book("1Esd", "1ES", "ot"),
    Book("2Esd", "2ES", "ot"),
    Book("PrMan", "MAN", "ot"),
    Book("AddPs", "PS2", "ot"),
    Book("Matt", "MAT", "nt", ("28.20",)),
    Book("Mark", "MRK", "nt", ("16.20",)),
    Book("Luke", "LUK", "nt", ("24.53",)),
    Book("John", "JOH", "nt", ("21.25",)),
    Book("Acts", "ACT", "nt", ("28.31",)),
    Book("Rom", "ROM", "nt", ("16.27",)),
    Book("1Cor", "1CO", "nt", ("16.24",)),
    Book("2Cor", "2CO", "nt", ("13.14", "13.13")),
    Book("Gal", "GAL", "nt", ("6.18",)),
    Book("Eph", "EPH", "nt", ("6.24",)),
    Book("Phil", "PHP", "nt", ("4.23",)),
    Book("Col", "COL", "nt", ("4.18",)),
    Book("1Thess", "1TH", "nt", ("5.28",)),
    Book("2Thess", "2TH", "nt", ("3.18",)),
    Book("1Tim", "1TI", "nt", ("6.21",)),
    Book("2Tim", "2TI", "nt", ("4.22",)),
    Book("Titus", "TIT", "nt", ("3.15",)),
    Book("Phlm", "PHM", "nt", ("1.25",)),
    Book("Heb", "HEB", "nt", ("13.25",)),
    Book("Jas", "JAS", "nt", ("5.20",)),
    Book("1Pet", "1PE", "nt", ("5.14",)),
    Book("2Pet", "2PE", "nt", ("3.18",)),
    Book("1John", "1JO", "nt", ("5.21",)),
    Book("2John", "2JO", "nt", ("1.13",)),
    Book("3John", "3JO", "nt", ("1.14", "1.15")),
    Book("Jude", "JUD", "nt", ("1.25",)),
    Book("Rev", "REV", "nt", ("22.21",)),
)

#: Prefixes that name a whole testament rather than a book. A file named for
#: one has no single book to group under, so its ``book`` is left empty and
#: its ``category`` says where it belongs.
TESTAMENTS = {"OT": "ot", "NT": "nt"}

#: The canon of each testament, for asking whether a whole-testament file is
#: missing a book. Deuterocanonical books are not demanded of an Old Testament:
#: most Hebrew Bibles hold none of them.
#: Every protocanonical book states an ending and no deuterocanonical one does,
#: so the endings are what tell them apart.
PROTOCANON = {
    category: tuple(book.osis for book in BOOKS if book.category == category and book.endings)
    for category in ("ot", "nt")
}

_BY_OSIS = {book.osis: book for book in BOOKS}
_ORDER = {book.osis: index for index, book in enumerate(BOOKS)}

#: Every way a code may be written, folded to upper case. Each book answers to
#: its own code and to its OSIS id, so a file named ``Gen_…`` or ``GEN_…`` lands
#: in the same place. JHN is Paratext's John, accepted alongside this
#: repository's JOH. No two of these collide — the test suite holds that.
_BY_CODE: dict[str, str] = {}
for _book in BOOKS:
    _BY_CODE[_book.code] = _book.osis
    _BY_CODE[_book.osis.upper()] = _book.osis
_BY_CODE["JHN"] = "John"

_REFERENCE = re.compile(r"^([1-4]?[A-Za-z]+)\.(\d+)\.(\d+)$")


def book_id(code: str) -> str:
    """The OSIS id ``code`` names, or ``""`` when it names no single book.

    ``code`` is a filename prefix or a link-list cell: ``JAS``, ``JOH``,
    ``Matt``. A testament prefix (``NT``) and an unknown code are both ``""``.
    """
    return _BY_CODE.get(code.strip().upper(), "")


def category_of(book: str) -> str:
    """``"ot"`` or ``"nt"`` for an OSIS book id, ``""`` for one not known here."""
    known = _BY_OSIS.get(book)
    return known.category if known else ""


def parse(reference: str) -> tuple[str, int, int] | None:
    """``"Jas.1.1"`` as ``("Jas", 1, 1)``; None for anything else."""
    match = _REFERENCE.match(reference.strip())
    if not match:
        return None
    return match.group(1), int(match.group(2)), int(match.group(3))


def _sorted(refs: Iterable[tuple[str, int, int]]) -> list[tuple[str, int, int]]:
    """Canonical order, duplicates gone. Books this table does not know sort
    after those it does, in the order they were first met."""
    unique = list(dict.fromkeys(refs))
    first_seen: dict[str, int] = {}
    for book, _, _ in unique:
        first_seen.setdefault(book, len(first_seen))
    return sorted(
        unique,
        key=lambda ref: (
            _ORDER.get(ref[0], len(_ORDER) + first_seen[ref[0]]),
            ref[1],
            ref[2],
        ),
    )


def _follows(previous: tuple[str, int, int], current: tuple[str, int, int]) -> bool:
    """Whether ``current`` is the verse after ``previous``.

    The next verse of the same chapter, or the first verse of the next chapter.
    The second is taken on trust: without a verse count for every chapter,
    a chapter whose last few verses are missing cannot be told from one that
    is whole, so a range may run across a gap at a chapter's end. A range never
    runs across a skipped chapter or into another book.
    """
    if previous[0] != current[0]:
        return False
    if previous[1] == current[1]:
        return current[2] == previous[2] + 1
    return current[1] == previous[1] + 1 and current[2] == 1


def covers(refs: Iterable[str]) -> list[str]:
    """Verse references collapsed into ranges, in canonical order.

    ``["Jas.1.1", "Jas.1.2", "Jas.1.3", "Jas.2.5"]`` becomes
    ``["Jas.1.1-Jas.1.3", "Jas.2.5"]``. Anything that is not a plain
    ``Book.chapter.verse`` is left out — an OSIS id may name a whole book or
    chapter, or something that is not a verse at all.
    """
    parsed = _sorted(ref for ref in map(parse, refs) if ref is not None)
    ranges: list[str] = []
    start = previous = None
    for ref in parsed:
        if previous is not None and _follows(previous, ref):
            previous = ref
            continue
        if start is not None:
            ranges.append(_range(start, previous))
        start = previous = ref
    if start is not None:
        ranges.append(_range(start, previous))
    return ranges


def _range(start: tuple[str, int, int], end: tuple[str, int, int]) -> str:
    first = f"{start[0]}.{start[1]}.{start[2]}"
    if start == end:
        return first
    return f"{first}-{end[0]}.{end[1]}.{end[2]}"


def complete(refs: Iterable[tuple[str, int, int]], book: str) -> bool:
    """Whether the verses of ``book`` among ``refs`` are the whole book.

    Whole means: it opens at 1:1, no chapter is skipped, and — where this
    table states the book's ending — it reaches one of them. See the module
    notes for why a gap inside a chapter does not count against it.
    """
    verses = [(chapter, verse) for name, chapter, verse in refs if name == book]
    if not verses:
        return False
    if (1, 1) not in verses:
        return False
    chapters = {chapter for chapter, _ in verses}
    last = max(chapters)
    if chapters != set(range(1, last + 1)):
        return False
    known = _BY_OSIS.get(book)
    if known is None or not known.endings:
        return True
    final = max(verse for chapter, verse in verses if chapter == last)
    return f"{last}.{final}" in known.endings
