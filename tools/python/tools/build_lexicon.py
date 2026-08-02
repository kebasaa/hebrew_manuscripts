"""Build the Hebrew lexicon index Milah ships with.

Three openly licensed sources are folded into one compact JSON file:

* Strong's Hebrew Dictionary (public domain, 1890), as published by the
  OpenScriptures project, for the entry text of each number.
* The Westminster Leningrad Codex with morphology (OpenScriptures morphhb,
  CC BY 4.0), for the inflected forms each number actually appears as.
* TBESH, the Translators Brief lexicon of Extended Strongs for Hebrew
  (STEPBible.org, CC BY 4.0) — an abridged Brown-Driver-Briggs — for the gloss
  a reader actually wants, Strong's 1890 wording being both dated and slanted
  towards KJV renderings.

The result is committed as ``app/data/hebrew_lexicon.json`` and compiled into
the binary as a Qt resource; the raw downloads are not kept. Run it again only
when the upstream data changes.

Usage::

    python tools/python/tools/build_lexicon.py \\
        --strongs  <dir>/strongs-hebrew-dictionary.js \\
        --wlc      <dir>/wlc \\
        --tbesh    <dir>/tbesh.txt \\
        --out      app/data/hebrew_lexicon.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

# Hebrew points and accents, matching hebrewMarks() in app/src/core/tokenize.cpp.
# 05BE (maqaf) is left out there because it is punctuation, and the punctuation
# pass below removes it anyway.
_MARKS = [(0x0591, 0x05BD), (0x05BF, 0x05C7)]
# Cantillation only, so a pointed form keeps its niqqud but loses the accents
# that manuscript text almost never carries.
_ACCENTS = [(0x0591, 0x05AF)]

_WHITESPACE = re.compile(r"\s+")
_OSIS_NS = "{http://www.bibletechnologies.net/2003/OSIS/namespace}"


def _in_ranges(code: int, ranges: list[tuple[int, int]]) -> bool:
    return any(low <= code <= high for low, high in ranges)


def comparison_key(text: str) -> str:
    """The consonantal skeleton, character for character what
    ``comparisonKey()`` in app/src/core/tokenize.cpp produces. The two must
    agree or nothing the app looks up will be found."""
    decomposed = unicodedata.normalize("NFD", text)
    kept = [
        ch
        for ch in decomposed
        if not _in_ranges(ord(ch), _MARKS)
        and not unicodedata.category(ch).startswith(("P", "S"))
    ]
    recomposed = unicodedata.normalize("NFC", "".join(kept))
    return _WHITESPACE.sub(" ", recomposed).strip().lower()


def pointed_key(text: str) -> str:
    """The form with its niqqud but without cantillation."""
    decomposed = unicodedata.normalize("NFD", text)
    kept = [
        ch
        for ch in decomposed
        if not _in_ranges(ord(ch), _ACCENTS)
        and not unicodedata.category(ch).startswith(("P", "S"))
    ]
    return unicodedata.normalize("NFC", "".join(kept)).strip()


def tidy(value: str) -> str:
    """Strong's brackets uncertain glosses and marks idioms; neither belongs in
    something a reader hovers."""
    cleaned = (value or "").replace("{", "").replace("}", "").replace("[idiom]", "")
    return _WHITESPACE.sub(" ", cleaned).strip()


def load_strongs(path: Path) -> dict[str, dict[str, str]]:
    """Reads the dictionary out of its JavaScript wrapper."""
    text = path.read_text(encoding="utf-8")
    start = text.index("{")
    end = text.rindex("}")
    raw = json.loads(text[start : end + 1])

    entries: dict[str, dict[str, str]] = {}
    for number, record in raw.items():
        entries[number] = {
            "l": record.get("lemma", ""),
            "x": record.get("xlit", ""),
            "p": record.get("pron", ""),
            "d": tidy(record.get("derivation", "")),
            "g": tidy(record.get("strongs_def", "")),
            "k": tidy(record.get("kjv_def", "")),
        }
    return entries


def load_tbesh(path: Path, sense_limit: int, meaning_limit: int) -> dict[str, dict[str, str]]:
    """Reads the STEPBible lexicon, keyed by the plain Strong's number.

    Its ``eStrong#`` column is zero-padded and often carries a homonym letter,
    and several extended entries can share one base number — H0001 covers both
    "father" and a proper name. They are merged in file order, because that is
    the order the lexicon itself considers primary.
    """
    glosses: dict[str, list[str]] = defaultdict(list)
    meanings: dict[str, str] = {}
    morphs: dict[str, str] = {}

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("H") or "\t" not in line:
            continue
        fields = line.split("\t")
        if len(fields) < 7:
            continue

        digits = re.match(r"H(\d+)", fields[0])
        if not digits:
            continue
        number = "H" + str(int(digits.group(1)))

        gloss = _WHITESPACE.sub(" ", fields[6]).strip()
        if gloss and gloss not in glosses[number] and len(glosses[number]) < sense_limit:
            glosses[number].append(gloss)

        if number not in meanings and len(fields) > 7:
            # BDB's senses are separated by <br>; anything else angle-bracketed
            # is markup that would show through as literal text in a tooltip.
            meaning = re.sub(r"<[Bb][Rr]\s*/?>", "\n", fields[7])
            meaning = re.sub(r"<[^>]+>", "", meaning)
            meaning = "\n".join(
                _WHITESPACE.sub(" ", part).strip() for part in meaning.split("\n")
            ).strip()
            if len(meaning) > meaning_limit:
                meaning = meaning[: meaning_limit - 1].rstrip(" ,;\n") + "…"
            if meaning:
                meanings[number] = meaning

        if number not in morphs and fields[5].strip():
            morphs[number] = fields[5].strip()

    merged: dict[str, dict[str, str]] = {}
    for number in set(glosses) | set(meanings) | set(morphs):
        merged[number] = {
            "bg": "; ".join(glosses.get(number, [])),
            "bd": meanings.get(number, ""),
            "m": morphs.get(number, ""),
        }
    return merged


def strongs_numbers(lemma: str) -> list[str]:
    """Pulls the Strong's numbers out of a morphhb lemma attribute.

    ``c/1961`` is a conjunction prefixed to H1961; ``l/1481 a`` is a preposition
    on homonym *a* of H1481; ``1035+`` marks a compound name. Only the numeric
    parts name a dictionary entry, so the single-letter prefix codes are
    dropped.
    """
    numbers: list[str] = []
    for part in lemma.split("/"):
        digits = re.match(r"\d+", part.strip())
        if digits:
            numbers.append("H" + str(int(digits.group())))
    return numbers


def word_segments(word: str) -> list[str]:
    """morphhb separates prefixes from the stem with a slash."""
    return [segment for segment in word.split("/") if segment]


def index_wlc(directory: Path) -> tuple[dict[str, Counter], dict[str, Counter]]:
    forms: dict[str, Counter] = defaultdict(Counter)
    pointed: dict[str, Counter] = defaultdict(Counter)

    files = sorted(directory.glob("*.xml"))
    if not files:
        raise SystemExit(f"No WLC XML files under {directory}")

    for path in files:
        if path.name == "VerseMap.xml":
            continue
        tree = ET.parse(path)
        for element in tree.iter(f"{_OSIS_NS}w"):
            surface = "".join(element.itertext())
            lemma = element.get("lemma") or ""
            numbers = strongs_numbers(lemma)
            if not surface or not numbers:
                continue

            # The whole word as written, prefixes and all.
            whole = surface.replace("/", "")
            for number in numbers:
                key = comparison_key(whole)
                if key:
                    forms[key][number] += 1
                point = pointed_key(whole)
                if point:
                    pointed[point][number] += 1

            # And each morpheme on its own, so a stem written without the
            # prefix the Masoretic text happens to carry is still found.
            segments = word_segments(surface)
            if len(segments) == len(numbers) and len(segments) > 1:
                for segment, number in zip(segments, numbers):
                    key = comparison_key(segment)
                    if key:
                        forms[key][number] += 1
                    point = pointed_key(segment)
                    if point:
                        pointed[point][number] += 1

        print(f"  indexed {path.name}", file=sys.stderr)

    return forms, pointed


def ranked(counters: dict[str, Counter], limit: int) -> dict[str, list[str]]:
    """Most frequent reading first, so the interlinear cell shows the likeliest
    number and the rest stay available as candidates."""
    result: dict[str, list[str]] = {}
    for key in sorted(counters):
        counter = counters[key]
        ordered = [number for number, _ in counter.most_common(limit)]
        result[key] = ordered
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strongs", required=True, type=Path)
    parser.add_argument("--wlc", required=True, type=Path)
    parser.add_argument("--tbesh", type=Path, help="STEPBible TBESH lexicon")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=4,
        help="how many Strong's numbers to keep per form",
    )
    parser.add_argument(
        "--max-senses",
        type=int,
        default=3,
        help="how many TBESH glosses to keep per Strong's number",
    )
    parser.add_argument(
        "--max-meaning",
        type=int,
        default=420,
        help="characters of BDB to keep; it feeds a tooltip, not a reference work",
    )
    arguments = parser.parse_args()

    print("Reading Strong's dictionary…", file=sys.stderr)
    entries = load_strongs(arguments.strongs)
    print(f"  {len(entries)} entries", file=sys.stderr)

    if arguments.tbesh:
        print("Reading the STEPBible lexicon…", file=sys.stderr)
        tbesh = load_tbesh(arguments.tbesh, arguments.max_senses, arguments.max_meaning)
        print(f"  {len(tbesh)} entries", file=sys.stderr)
        matched = 0
        for number, extra in tbesh.items():
            if number in entries:
                entries[number].update(extra)
                matched += 1
        print(f"  {matched} matched a Strong's entry", file=sys.stderr)

    print("Indexing the Westminster Leningrad Codex…", file=sys.stderr)
    forms, pointed = index_wlc(arguments.wlc)
    print(
        f"  {len(forms)} consonantal forms, {len(pointed)} pointed forms",
        file=sys.stderr,
    )

    # Only entries some form actually points at are worth shipping.
    referenced = {number for numbers in forms.values() for number in numbers}
    kept = {number: entries[number] for number in sorted(referenced) if number in entries}
    print(f"  {len(kept)} entries reachable from a form", file=sys.stderr)

    document = {
        "version": 1,
        "about": (
            "Strong's Hebrew Dictionary (public domain); Westminster Leningrad "
            "Codex morphology from OpenScriptures morphhb (CC BY 4.0); abridged "
            "Brown-Driver-Briggs from STEP Bible, www.STEPBible.org (CC BY 4.0). "
            "See app/data/README.md."
        ),
        "entries": kept,
        "forms": ranked(forms, arguments.max_candidates),
        "pointed": ranked(pointed, arguments.max_candidates),
    }

    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    # Sorted and compact, so the committed file diffs sanely between runs.
    arguments.out.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    print(
        f"Wrote {arguments.out} "
        f"({arguments.out.stat().st_size / 1_048_576:.1f} MB)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
