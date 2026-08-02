"""Build the rabbinic Hebrew word list Milah ships with.

The unknown-word check reads its vocabulary from the Hebrew Bible, so it fires
on the post-biblical words a Hebrew New Testament is full of. The Mishnah and
Tosefta are the 1st-3rd century register those manuscripts inhabit; the forms
they attest are collected here so that legitimate vocabulary stops being
flagged.

This produces a **word list, not rules**. Mining attested phrases from the
corpus and proposing them would reproduce the very failure being fixed: most
New Testament phrasing is absent from the Mishnah, so it would flag correct
text as unattested. Mishnaic phrasing is not normative for a New Testament
translation.

Sefaria licenses per text *version*, and the values include CC-BY-NC — its
plain-text API serves such a version by default. So this reads the export
bucket, where the version is a path segment and every file carries its own
``license`` field, and it **refuses** any version that is not clearly free.

Usage::

    python tools/python/tools/build_wordlist.py --out app/data/rabbinic.words.txt
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Shared rather than reimplemented: if this drifts from the app's
# comparisonKey(), every word in the list silently stops matching.
from build_lexicon import comparison_key  # noqa: E402

BUCKET = "sefaria-export"
LIST_URL = f"https://storage.googleapis.com/storage/v1/b/{BUCKET}/o"
OBJECT_URL = f"https://storage.googleapis.com/{BUCKET}/"

DEFAULT_CORPORA = ["Mishnah", "Tosefta"]

# Only licences that permit redistribution by anyone, for any purpose. CC-BY-SA
# and CC-BY-NC are deliberately absent: the first would impose its own terms on
# what Milah ships, the second forbids commercial use, which a GPLv3 program
# cannot accept.
ALLOWED_LICENCES = {"public domain", "pd", "cc0", "cc-by", "cc by"}

_TAGS = re.compile(r"<[^>]+>")
# Hebrew letters, plus the points and marks that sit on them. Everything else
# is a separator.
_WORDS = re.compile(r"[א-ת][א-ת֑-ׇ]*")


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "milah-build"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def list_objects(prefix: str) -> list[str]:
    """Every object name under `prefix`, following the bucket's paging."""
    names: list[str] = []
    token: str | None = None
    while True:
        query = {"prefix": prefix, "maxResults": "1000"}
        if token:
            query["pageToken"] = token
        payload = json.loads(fetch(f"{LIST_URL}?{urllib.parse.urlencode(query)}"))
        names.extend(item["name"] for item in payload.get("items", []))
        token = payload.get("nextPageToken")
        if not token:
            return names


def hebrew_versions(corpus: str) -> list[str]:
    """The Hebrew version files for a corpus's own text.

    Sefaria files commentaries under the category they comment on, so
    ``json/Mishnah/`` holds five times more Bartenura and Tosafot Yom Tov than
    Mishnah. Those are medieval and later Hebrew, often with Aramaic — a
    different register, and letting them in would make the word list so
    permissive that it stopped catching anything.

    The book segment tells them apart: the base text is ``Mishnah Berakhot``,
    a commentary on it is ``Bartenura on Mishnah Berakhot``.

    ``merged.json`` is skipped too: a merge of several versions has no single
    licence to check or to credit.
    """
    return [
        name
        for name in list_objects(f"json/{corpus}/")
        if "/Hebrew/" in name
        and name.endswith(".json")
        and not name.endswith("/merged.json")
        and name.split("/")[-3].startswith(corpus + " ")
    ]


def strings_in(node: object) -> list[str]:
    """Sefaria nests its text arbitrarily deep; only the leaves matter."""
    if isinstance(node, str):
        return [node]
    if isinstance(node, list):
        return [text for child in node for text in strings_in(child)]
    return []


def words_in(text: str) -> list[str]:
    return _WORDS.findall(_TAGS.sub(" ", text))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--corpus",
        action="append",
        dest="corpora",
        help="repeatable; defaults to Mishnah and Tosefta",
    )
    arguments = parser.parse_args()
    corpora = arguments.corpora or DEFAULT_CORPORA

    forms: set[str] = set()
    used: list[tuple[str, str, str]] = []
    refused: list[tuple[str, str]] = []
    occurrences = 0

    for corpus in corpora:
        print(f"Listing {corpus}…", file=sys.stderr)
        names = hebrew_versions(corpus)
        print(f"  {len(names)} Hebrew version files", file=sys.stderr)

        for name in names:
            document = json.loads(fetch(OBJECT_URL + urllib.parse.quote(name)))
            licence = (document.get("license") or "").strip()
            version = document.get("versionTitle") or name

            if licence.lower() not in ALLOWED_LICENCES:
                refused.append((f"{corpus}: {version}", licence or "unstated"))
                continue

            words = [
                word
                for text in strings_in(document.get("text"))
                for word in words_in(text)
            ]
            occurrences += len(words)
            for word in words:
                key = comparison_key(word)
                if key:
                    forms.add(key)

            title = document.get("title") or corpus
            used.append((title, version, licence))

    print(f"\n{len(used)} versions used, {len(refused)} refused", file=sys.stderr)
    for entry, licence in refused:
        print(f"  refused [{licence}] {entry}", file=sys.stderr)
    print(f"{occurrences} word occurrences, {len(forms)} distinct forms", file=sys.stderr)

    if not forms:
        print("Nothing was collected; refusing to write an empty list.", file=sys.stderr)
        return 1

    # One version line per source, so the credit and the licence travel with
    # the data rather than living only in a README.
    credits = sorted({f"{version} [{licence}]" for _, version, licence in used})

    header = [
        "# Rabbinic Hebrew word list for Milah's unknown-word check.",
        "#",
        "# Generated by tools/python/tools/build_wordlist.py — do not edit by machine,",
        "# but words may be appended by hand; blank lines and # comments are",
        "# ignored, and any other *.words.txt in the data directory is read too.",
        "#",
        "# One consonantal form per line, produced by the same reduction the",
        "# application applies before looking a word up, so pointing need not",
        f"# match. {len(forms)} forms from {occurrences} word occurrences.",
        "#",
        "# Sources — all Public Domain or CC-BY, from the Sefaria export",
        "# (https://github.com/Sefaria/Sefaria-Export). Versions under any other",
        "# licence are refused by the generator.",
    ]
    header.extend(f"#   {credit}" for credit in credits)
    if refused:
        header.append("#")
        header.append("# Refused:")
        header.extend(f"#   [{licence}] {entry}" for entry, licence in refused)

    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        "\n".join(header) + "\n" + "\n".join(sorted(forms)) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {arguments.out} "
        f"({arguments.out.stat().st_size / 1024:.0f} KB)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
