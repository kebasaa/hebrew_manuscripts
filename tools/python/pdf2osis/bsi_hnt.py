"""Extraction for the Bible Society in Israel's modern Hebrew New Testament.

*HaBrit HaChadasha* (1995, revised 2010) has no digital edition, app, or API
the Bible Society in Israel publishes directly — the only place its actual
text is online is a third-party mirror, nocr.net, displaying it through a
plain chapter-by-chapter page. There is no bulk export, so this scrapes it a
chapter at a time and caches the result locally as JSON, matching the shape
:mod:`pdf2osis.sword` returns so both whole-NT sources share one downstream
path: :func:`fetch_bsi_nt` is the one-time "download" step (parallel to
fetching a SWORD module or saving a manuscript PDF), and
:func:`extract_bsi_nt` reads the cache back — conversion never touches the
network, and re-running it does not re-scrape the site.

**Licensing**: unlike Delitzsch's module, there is no license grant here at
all — the source states only "copyrighted (c) 1995, revised (c) 2010 by The
Bible Society in Israel", with no reuse permission. The generated OSIS is
therefore local-only by convention (see ``profiles.BSI_HNT.rights`` and
``tools/README.md``); nothing here enforces that on disk.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from .models import VerseDocument, VerseRecord
from .profiles import BookProfile

BASE_URL = "https://nocr.net/hbm/hebrew/hebmht/index.php"

# (osis_book, nocr.net's own book code), in canonical NT order — the same
# order pdf2osis.profiles.DELITZSCH uses, so the two whole-NT sources agree.
NT_BOOKS = (
    ("Matt", "Mt"), ("Mark", "Mr"), ("Luke", "Lu"), ("John", "Joh"),
    ("Acts", "Ac"), ("Rom", "Ro"), ("1Cor", "1Co"), ("2Cor", "2Co"),
    ("Gal", "Ga"), ("Eph", "Eph"), ("Phil", "Php"), ("Col", "Col"),
    ("1Thess", "1Th"), ("2Thess", "2Th"), ("1Tim", "1Ti"), ("2Tim", "2Ti"),
    ("Titus", "Tit"), ("Phlm", "Phm"), ("Heb", "Heb"), ("Jas", "Jas"),
    ("1Pet", "1Pe"), ("2Pet", "2Pe"), ("1John", "1Jo"), ("2John", "2Jo"),
    ("3John", "3Jo"), ("Jude", "Jude"), ("Rev", "Re"),
)

_HEBREW_RE = re.compile(r"[֑-״]")
# A chapter's whole text arrives in one blob with no delimiter between verses
# other than the printed "C:V " reference itself.
_VERSE_SPLIT_RE = re.compile(r"(\d+:\d+)\s+")


def _chapter_hebrew(
    nocr_code: str, chapter: int, *, session: requests.Session
) -> str | None:
    """The chapter's Hebrew cell text, or None past the book's last chapter.

    The site has no chapter count anywhere; requesting one past the end
    returns a normal page with no Hebrew cell, which is the only signal that
    the book has ended.
    """
    url = f"{BASE_URL}/{nocr_code}/{chapter}/"
    response = session.get(url, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for cell in soup.find_all("td"):
        text = cell.get_text(" ", strip=True)
        if text and _HEBREW_RE.search(text) and len(text) > 20:
            return text
    return None


def _split_verses(chapter: int, text: str) -> list[tuple[str, str]]:
    """Split one chapter's blob into ``(verse, text)`` pairs, in order.

    Verse numbers must come out strictly sequential from 1 — the one check
    available against a verse's own text accidentally containing something
    that looks like a "C:V" reference (a quoted time, an Old Testament
    citation) and being mistaken for a marker.
    """
    parts = _VERSE_SPLIT_RE.split(text)
    verses: list[tuple[str, str]] = []
    for index in range(1, len(parts), 2):
        ref = parts[index]
        # The page's own combining-mark order varies verse to verse even for
        # the same visual text; normalise so equal-looking Hebrew is equal.
        body = (
            unicodedata.normalize("NFC", parts[index + 1]).strip()
            if index + 1 < len(parts)
            else ""
        )
        ref_chapter, verse = ref.split(":")
        if int(ref_chapter) != chapter:
            raise ValueError(
                f"chapter {chapter}: verse marker {ref!r} names a different "
                "chapter"
            )
        verses.append((verse, body))
    numbers = [int(verse) for verse, _ in verses]
    if numbers != list(range(1, len(numbers) + 1)):
        raise ValueError(
            f"chapter {chapter}: verse numbers are not sequential: {numbers}"
        )
    return verses


def fetch_bsi_nt(cache_path: Path, *, delay: float = 0.4) -> None:
    """Scrape the whole NT from nocr.net once and write it to a local cache.

    A politeness delay is applied between requests — nocr.net is a small,
    non-commercial mirror, not an API meant for bulk access.
    """
    session = requests.Session()
    session.headers["User-Agent"] = "milah-pdf2osis/0.1 (personal research tool)"
    data: dict[str, dict[str, dict[str, str]]] = {}
    for osis_book, nocr_code in NT_BOOKS:
        book_data: dict[str, dict[str, str]] = {}
        chapter = 1
        while True:
            text = _chapter_hebrew(nocr_code, chapter, session=session)
            time.sleep(delay)
            if text is None:
                break
            book_data[str(chapter)] = dict(_split_verses(chapter, text))
            chapter += 1
        if not book_data:
            raise ValueError(f"{osis_book} ({nocr_code}): no chapters found")
        data[osis_book] = book_data

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def extract_bsi_nt(source: Path, profile: BookProfile) -> dict[str, VerseDocument]:
    """Read the local cache `fetch_bsi_nt` wrote, in canonical book order."""
    cached = json.loads(source.read_text(encoding="utf-8"))
    books: dict[str, VerseDocument] = {}
    for osis_book, _nocr_code in NT_BOOKS:
        chapters = cached.get(osis_book)
        if not chapters:
            raise ValueError(f"{source}: no cached data for {osis_book}")
        document = VerseDocument()
        for chapter in sorted(chapters, key=int):
            verses = chapters[chapter]
            for verse in sorted(verses, key=int):
                text = verses[verse]
                record = VerseRecord(
                    chapter=int(chapter), verse=verse, page=0, hebrew=text
                )
                if not text.strip():
                    # The site prints the reference with nothing after it —
                    # most of these are the well-known verses modern NT
                    # translations based on the earliest manuscripts omit or
                    # restructure (Matt 17:21, Mark 9:44, Acts 8:37, etc.);
                    # nocr.net gives no fuller explanation than the blank
                    # itself, so this states the fact rather than guessing
                    # a specific textual-critical reason per verse.
                    record.empty = True
                    record.absence = (
                        f"{osis_book} {chapter}:{verse} is printed with no "
                        "text in the source."
                    )
                document.records.append(record)
        books[osis_book] = document
    return books
