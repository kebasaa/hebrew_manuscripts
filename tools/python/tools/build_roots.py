"""Derives a Strong's-number-to-root map from the shipped Hebrew lexicon.

Reads ``app/data/hebrew_lexicon.json`` -- the file Milah already ships -- and
writes ``app/data/hebrew_roots.json``. Nothing is downloaded, so this runs in
under a second and can be iterated on freely, unlike build_lexicon.py, which
needs three external corpora the repository does not carry.

The source is each entry's ``d`` (derivation) field, Strong's own etymology
prose::

    "H4428": {"l": "מֶלֶךְ", "d": "from H4427 (מָלַךְ);", ...}

so מלך "king" is recorded as coming from מלך "to reign". The alignment uses this
to recognise that two differently spelt words belong to one root.

Why this is deliberately timid
------------------------------

Relatedness shades off fast, and every extra step collapses more distant words
into one bucket -- where the aligner will happily put them in the same column.
אָדָם H120 "man" derives from H119 "to be red"; יְהוּדָה from ידה "to praise".
Following those to a fixed point would be *worse* than not following them at
all. So:

* only the first clause of the derivation is read, and only when it names
  exactly one number -- "from H430 and H1961" is a compound with no single root;
* "a primitive root" means the entry *is* a root and has no parent;
* chains are walked at most ``--max-hops`` steps, not to a fixed point;
* a root that ends up with more than ``--max-root-bucket`` members is dropped
  entirely, on the grounds that it has stopped naming anything useful;
* an entry that is its own root is omitted, since it tells the scorer nothing
  the Strong's number did not already.

Usage, run from a milah checkout with this repository beside it::

    python ../hebrew_manuscripts/tools/python/tools/build_roots.py \\
        --lexicon app/data/hebrew_lexicon.json --output app/data/hebrew_roots.json
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

#: "from H4427 (מָלַךְ);" -- the letter names the language, the digits the entry.
#: Leading zeros appear in some editions, so they are normalised away.
_STRONGS = re.compile(r"\bH0*(\d+)\b")

#: Phrases that mark an entry as a root in its own right.
_PRIMITIVE = ("primitive root", "primitive word")

DEFAULT_MAX_HOPS = 2
DEFAULT_MAX_ROOT_BUCKET = 40


def direct_parent(derivation: str) -> str | None:
    """The single Strong's number `derivation` says this word comes from.

    Returns None when the entry is a root itself, when the derivation names no
    number, or when it names more than one -- a compound has no single root,
    and picking either half would be inventing an etymology.
    """
    if not derivation:
        return None

    lowered = derivation.lower()
    if any(phrase in lowered for phrase in _PRIMITIVE):
        return None

    # The first clause only. Later ones compare the word to others rather than
    # deriving it from them ("compare H1234"), which is not the same claim.
    head = derivation.split(";")[0]
    found = _STRONGS.findall(head)
    if len(found) != 1:
        return None
    return "H" + str(int(found[0]))


def resolve_root(start: str, parents: dict[str, str], max_hops: int) -> str:
    """Walks up from `start` at most `max_hops` steps, stopping on a cycle."""
    current = start
    seen = {current}
    for _ in range(max_hops):
        parent = parents.get(current)
        # No parent means this entry has no derivation of its own: a root, and
        # where the walk is meant to stop.
        if parent is None or parent in seen:
            break
        current = parent
        seen.add(current)
    return current


def build_roots(
    entries: dict[str, dict],
    max_hops: int = DEFAULT_MAX_HOPS,
    max_root_bucket: int = DEFAULT_MAX_ROOT_BUCKET,
) -> dict[str, str]:
    """Maps each Strong's number to the root it derives from."""
    parents: dict[str, str] = {}
    for number, entry in entries.items():
        parent = direct_parent(entry.get("d", ""))
        if parent is not None and parent != number:
            parents[number] = parent

    roots = {
        number: resolve_root(number, parents, max_hops) for number in parents
    }
    # An entry that resolves to itself adds nothing the number did not.
    roots = {k: v for k, v in roots.items() if k != v}

    # A root gathering too many members has stopped naming a shared meaning and
    # started naming a coincidence of etymology.
    oversized = {
        root
        for root, count in Counter(roots.values()).items()
        if count > max_root_bucket
    }
    if oversized:
        roots = {k: v for k, v in roots.items() if v not in oversized}

    return dict(sorted(roots.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # No default: the lexicon and the app that reads it live in a different
    # repository from this generator, so there is no relative path to it that
    # would be correct for every checkout.
    parser.add_argument("--lexicon", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-hops", type=int, default=DEFAULT_MAX_HOPS)
    parser.add_argument(
        "--max-root-bucket", type=int, default=DEFAULT_MAX_ROOT_BUCKET
    )
    args = parser.parse_args()

    lexicon = json.loads(args.lexicon.read_text(encoding="utf-8"))
    entries = lexicon.get("entries", {})
    roots = build_roots(entries, args.max_hops, args.max_root_bucket)

    document = {
        "version": 1,
        "about": (
            "Strong's numbers to the root they derive from, read out of the "
            "derivation field of hebrew_lexicon.json by "
            "tools/python/tools/build_roots.py. Chains are walked at most "
            f"{args.max_hops} steps and roots with more than "
            f"{args.max_root_bucket} members are dropped, because relatedness "
            "shades off faster than the etymology admits."
        ),
        "roots": roots,
    }
    args.output.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
        encoding="utf-8",
    )

    print(f"{len(roots)} of {len(entries)} entries mapped -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
