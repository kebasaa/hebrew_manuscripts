"""Tests for the Strong's root map generator.

The generator reads free English etymology prose with a regular expression, so
what it *refuses* matters more than what it accepts: a wrong parent puts two
unrelated words in the same alignment column.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "tools" / "python" / "tools")
)

from build_roots import build_roots, direct_parent, resolve_root  # noqa: E402


class TestDirectParent:
    def test_reads_a_single_derivation(self):
        assert direct_parent("from H4427 (מָלַךְ);") == "H4427"

    def test_normalises_leading_zeros(self):
        assert direct_parent("from H0430;") == "H430"

    def test_a_primitive_root_has_no_parent(self):
        assert direct_parent("a primitive root;") is None
        assert direct_parent("a primitive word;") is None

    def test_a_compound_has_no_single_root(self):
        # Picking either half would be inventing an etymology.
        assert direct_parent("from H430 and H1961;") is None

    def test_ignores_a_later_comparison(self):
        # "compare" is not the same claim as "from", and it lives in a later
        # clause, which is why only the first is read.
        assert direct_parent("from H4427; compare H4438 and H4410;") == "H4427"

    def test_no_number_means_no_parent(self):
        assert direct_parent("of foreign origin;") is None
        assert direct_parent("") is None


class TestResolveRoot:
    def test_walks_up_to_the_root(self):
        parents = {"H3": "H2", "H2": "H1"}
        assert resolve_root("H3", parents, max_hops=2) == "H1"

    def test_stops_at_the_hop_cap(self):
        # Not a fixed point: every extra step collapses more distant words.
        parents = {"H4": "H3", "H3": "H2", "H2": "H1"}
        assert resolve_root("H4", parents, max_hops=2) == "H2"

    def test_a_cycle_terminates(self):
        parents = {"H1": "H2", "H2": "H1"}
        assert resolve_root("H1", parents, max_hops=10) == "H2"

    def test_a_self_reference_terminates(self):
        assert resolve_root("H1", {"H1": "H1"}, max_hops=10) == "H1"


class TestBuildRoots:
    def test_maps_a_word_to_its_root(self):
        entries = {
            "H4427": {"d": "a primitive root;"},
            "H4428": {"d": "from H4427 (מָלַךְ);"},
        }
        assert build_roots(entries) == {"H4428": "H4427"}

    def test_a_root_is_not_mapped_to_itself(self):
        entries = {"H4427": {"d": "a primitive root;"}}
        assert build_roots(entries) == {}

    def test_drops_an_oversized_bucket(self):
        # A root gathering half the dictionary has stopped naming a shared
        # meaning and started naming a coincidence of etymology.
        entries = {"H1": {"d": "a primitive root;"}}
        for number in range(2, 8):
            entries[f"H{number}"] = {"d": "from H1;"}

        assert build_roots(entries, max_root_bucket=10)
        assert build_roots(entries, max_root_bucket=3) == {}

    def test_an_entry_without_a_derivation_is_skipped(self):
        assert build_roots({"H1": {"l": "אָב"}}) == {}


@pytest.mark.parametrize(
    "derivation",
    [
        "from H119 (אָדַם);",  # אדם "man" from אדם "to be red"
        "from H3034 (יָדָה);",  # יהודה from ידה "to praise"
    ],
)
def test_a_remote_etymology_is_still_only_one_hop(derivation):
    """These are why the walk is capped rather than run to a fixed point.

    The link is real etymology and useless collation: אדם and אדום are not the
    same word for the purpose of lining up two manuscripts. One hop keeps the
    damage bounded; the bucket cap catches the rest.
    """
    assert direct_parent(derivation) is not None
