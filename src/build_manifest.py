"""Builds the manifest Milah reads to offer manuscripts for download.

Reads the OSIS files in ``manuscripts/`` and writes ``manifest_manuscripts.json``
at the root of this repository, so Milah can list what is available without
downloading anything first. Each entry names a file, not a path: the folder the
texts live in is Milah's to know, so moving them does not rewrite every entry.
The defaults are relative to this file, so it needs no arguments::

    python src/build_manifest.py

Re-run it whenever a text is added or an OSIS header changes, and commit the
result: the manifest is what the application reads, so a stale one hides a
manuscript sitting right beside it.

Why a manifest at all
---------------------

Filenames carry almost nothing: ``REV_Sloane237_hebrew_commented.osis`` does not
say that it is *Revelation (British Library, Sloane MS 237)*, covering
1:1–2:13, from a manuscript written between 1500 and 1699. All of that is inside
the file — which is exactly what a download list cannot read, because the point
of the list is to choose what to download.

The title trap
--------------

**Do not take the first ``<title>`` in the file.** These OSIS files carry nine
of them: the work's title, a versification note, the manuscript's own running
headings, an attribution, a copyright line, and one that is an entire pointed
Hebrew verse with a footnote nested inside it. Only the ``<title>`` inside
``<work>`` names the edition; anything looser puts a verse of Hebrew in the
download window. The app's own parser scopes the same way — see the header
handling in ``app/src/core/osis.cpp``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

OSIS_NS = "http://www.bibletechnologies.net/2003/OSIS/namespace"
XML_NS = "http://www.w3.org/XML/1998/namespace"

#: Milah loads a manuscript and a translation through different roles, so the
#: manifest has to say which a file is. The name is the only honest signal: a
#: translation is not merely "the one that is not Hebrew".
TRANSLATION_SUFFIX = "_translation"


def normalised_bytes(path: Path) -> bytes:
    """The file's content with line endings settled to LF.

    Everything measured about a file — its length and its checksum — is measured
    over this rather than over what happens to be on disk.

    ``.gitattributes`` sets ``* text=auto``, so the working copy is LF on one
    clone and CRLF on another depending on ``core.autocrlf``, while GitHub always
    serves the LF form and that is what Milah downloads and keeps. Measuring the
    raw file would make the manifest disagree with the app on any Windows clone
    that converts on checkout — every manuscript would report an update
    available, for ever, and taking the update would not settle it.
    """
    return path.read_bytes().replace(b"\r\n", b"\n")


def work_element(root: ET.Element) -> ET.Element | None:
    """The ``<work>`` inside ``<header>``, which is where the edition is named."""
    return root.find(f".//{{{OSIS_NS}}}header/{{{OSIS_NS}}}work")


def element_text(parent: ET.Element | None, tag: str) -> str:
    """The plain text of a child element, notes and markup flattened away."""
    if parent is None:
        return ""
    child = parent.find(f"{{{OSIS_NS}}}{tag}")
    if child is None:
        return ""
    # itertext() rather than .text: a title can carry nested markup, and half a
    # title is worse than none.
    return re.sub(r"\s+", " ", "".join(child.itertext())).strip()


def rights_text(work: ET.Element | None, kind: str) -> str:
    """The ``<rights type="x-{kind}">`` text, or "" when there is none.

    Copyright and license are different questions with different answers, so
    a header carries two ``<rights>`` elements distinguished by ``type`` — the
    schema allows the repetition. ``kind`` is ``"copyright"`` or
    ``"license"``. A bare, untyped ``<rights>`` — the shape every file in this
    repository used before the split — is read as copyright, so a header that
    has not been retrofitted degrades to answering one question rather than
    neither.
    """
    if work is None:
        return ""
    typed = work.find(f"{{{OSIS_NS}}}rights[@type='x-{kind}']")
    if typed is not None:
        return re.sub(r"\s+", " ", "".join(typed.itertext())).strip()
    if kind == "copyright":
        untyped = work.find(f"{{{OSIS_NS}}}rights")
        if untyped is not None and not untyped.get("type"):
            return re.sub(r"\s+", " ", "".join(untyped.itertext())).strip()
    return ""


def description_text(work: ET.Element | None, kind: str) -> str:
    """The ``<description type="x-{kind}">`` text, or "" where there is none.

    The header's open-ended half. A description carries what no other element
    has a place for, told apart by its type — what the edition covers, which
    folios it sits on, what the Hebrew was translated out of, which older
    manuscript it copies. Absent is ordinary: most of these are known for some
    manuscripts and not for others, and a catalogue that demanded them would be
    a catalogue nobody could add to.
    """
    if work is None:
        return ""
    for description in work.findall(f"{{{OSIS_NS}}}description"):
        if description.get("type") == f"x-{kind}":
            return re.sub(r"\s+", " ", "".join(description.itertext())).strip()
    return ""


def identifier_text(work: ET.Element | None, kind: str) -> str:
    """The ``<identifier type="x-{kind}">`` text, or "" where there is none."""
    if work is None:
        return ""
    for identifier in work.findall(f"{{{OSIS_NS}}}identifier"):
        if identifier.get("type") == f"x-{kind}":
            return re.sub(r"\s+", " ", "".join(identifier.itertext())).strip()
    return ""


def describe(path: Path) -> dict | None:
    """One manifest entry, or None when the file is not usable OSIS."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return None

    work = work_element(root)
    title = element_text(work, "title")
    if not title:
        # No title is not a reason to hide a manuscript; the work id at least
        # identifies it, and a human can read it.
        title = (work.get("osisWork") if work is not None else "") or path.stem

    text = root.find(f".//{{{OSIS_NS}}}osisText")
    language = (text.get(f"{{{XML_NS}}}lang") if text is not None else "") or ""

    content = normalised_bytes(path)
    is_translation = path.stem.endswith(TRANSLATION_SUFFIX)
    if is_translation and language == "he":
        # Worth knowing about rather than silently trusting either signal.
        print(f"  warning: {path.name} is named a translation but declares Hebrew")

    return {
        "file": path.name,
        "title": title,
        # The OSIS book code the file is named for, used only to group the
        # download list; the title is what a reader actually reads.
        "book": path.name.split("_", 1)[0],
        "role": "translation" if is_translation else "manuscript",
        "language": language,
        "date": element_text(work, "date"),
        "covers": description_text(work, "contents"),
        # What a cataloguer looks a manuscript up by, and the four columns the
        # download window shows beside it. All four describe the manuscript
        # rather than the file, so a translation carries its witness's answers
        # — it is a rendering of the same physical object.
        "shelfmark": identifier_text(work, "shelfmark"),
        # Which leaves it occupies: "1r-4v". Empty where the edition never said.
        "folios": description_text(work, "folios"),
        # What the Hebrew was rendered out of, where it is a rendering at all —
        # "Translated from the Greek". Empty means an independent Hebrew text or
        # a question nobody has settled, which are different and both honest to
        # leave unanswered.
        "translatedFrom": description_text(work, "translated-from"),
        # The older manuscript this one copies, where it is known to copy one —
        # "Copied from Cambridge MS Oo.1.32".
        "exemplar": description_text(work, "exemplar"),
        # Two different questions, never assumed. `rights` is who holds
        # copyright — may legitimately be empty, when nobody in particular is
        # credited with a bare transcription. `license` is what a reader may
        # do with it, and is never empty: the source's own stated term, or
        # this repository's CC BY-NC-SA default when the source stated none —
        # never invented past that, and never loosened past a stricter term
        # ("All Rights Reserved.") a source did state.
        "rights": rights_text(work, "copyright"),
        "license": rights_text(work, "license"),
        "bytes": len(content),
        # What tells Milah that a text it already holds has been corrected.
        # Length cannot: correcting "MS Sloane 273" to "Sloane MS 237" moves not
        # one byte, and that particular correction has been made in this very
        # repository — the edition this transcribes misnames the manuscript on
        # its own title page.
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def build(source: Path) -> list[dict]:
    entries = []
    for path in sorted(source.glob("*.osis")):
        entry = describe(path)
        if entry is None:
            print(f"  skipped (not parseable): {path.name}")
            continue
        entries.append(entry)
    return entries


#: src/ sits at the repository root, so the texts are one level up, not two.
#: Named rather than inlined so a test can assert the no-argument run still
#: points somewhere real — the defaults are the whole interface, since nobody
#: passes --source in practice, and one pointing at a folder that has been
#: renamed is a generator that quietly does nothing.
REPOSITORY = Path(__file__).resolve().parents[1]
MANUSCRIPTS = REPOSITORY / "manuscripts"
#: At the root rather than among the texts, and named for what it catalogues
#: rather than just "manifest", so it reads as a repository-level index and
#: leaves room for a second one later.
MANIFEST = REPOSITORY / "manifest_manuscripts.json"


def parser() -> argparse.ArgumentParser:
    parsed = argparse.ArgumentParser(description=__doc__)
    parsed.add_argument(
        "--source",
        type=Path,
        default=MANUSCRIPTS,
        help="Folder of published .osis files.",
    )
    parsed.add_argument(
        "--out",
        type=Path,
        default=MANIFEST,
        help="Where to write the catalogue.",
    )
    return parsed


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)

    if not args.source.is_dir():
        print(f"No such folder: {args.source}")
        return 1

    entries = build(args.source)
    if not entries:
        print(f"No .osis files in {args.source}")
        return 1

    document = {
        "version": 1,
        "about": (
            "Manuscripts Milah offers for download, generated from the OSIS "
            "headers by src/build_manifest.py in this repository. Do not edit "
            "by hand: regenerate it whenever a text is added or changes. Sizes "
            "and checksums are taken over the LF form of each file, which is "
            "what GitHub serves, so they do not depend on how a clone was "
            "checked out."
        ),
        "manuscripts": entries,
    }
    args.out.write_text(
        json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )

    total = sum(entry["bytes"] for entry in entries)
    print(f"{len(entries)} manuscripts, {total / 1024:.0f} KB -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
