"""Checks on the book table both manifest generators share.

Run from the repository root, with nothing to install::

    python -m unittest discover tests
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import osis_books  # noqa: E402


class CodesNameOneBookEach(unittest.TestCase):
    def test_the_repositorys_own_codes(self) -> None:
        for code, osis in {
            "JAS": "Jas",
            "JOH": "John",
            "LUK": "Luke",
            "MAT": "Matt",
            "REV": "Rev",
            "MRK": "Mark",
            "1CO": "1Cor",
            "PHP": "Phil",
            "PHM": "Phlm",
            "1JO": "1John",
            "JUD": "Jude",
            "GEN": "Gen",
            "PSA": "Ps",
            "JOL": "Joel",
            "JON": "Jonah",
        }.items():
            self.assertEqual(osis_books.book_id(code), osis, code)

    def test_an_osis_id_names_itself_in_any_case(self) -> None:
        for book in osis_books.BOOKS:
            self.assertEqual(osis_books.book_id(book.osis), book.osis)
            self.assertEqual(osis_books.book_id(book.osis.upper()), book.osis)

    def test_paratexts_john_is_accepted(self) -> None:
        self.assertEqual(osis_books.book_id("JHN"), "John")

    def test_a_testament_or_an_unknown_code_is_no_book(self) -> None:
        for code in ("NT", "OT", "", "XYZ", "Pirkei"):
            self.assertEqual(osis_books.book_id(code), "", code)

    def test_no_two_books_answer_to_one_code(self) -> None:
        # A code and an OSIS id of two different books folding to the same
        # upper-case string would file one book under the other, silently.
        seen: dict[str, str] = {}
        for book in osis_books.BOOKS:
            for code in {book.code, book.osis.upper()}:
                self.assertEqual(seen.setdefault(code, book.osis), book.osis, code)

    def test_every_book_is_in_a_testament(self) -> None:
        for book in osis_books.BOOKS:
            self.assertIn(book.category, ("ot", "nt"), book.osis)
        self.assertEqual(len(osis_books.PROTOCANON["ot"]), 39)
        self.assertEqual(len(osis_books.PROTOCANON["nt"]), 27)


class CoversCollapsesReferences(unittest.TestCase):
    def test_one_verse_stands_alone(self) -> None:
        self.assertEqual(osis_books.covers(["Jas.1.1"]), ["Jas.1.1"])

    def test_a_run_crosses_into_the_next_chapter(self) -> None:
        self.assertEqual(
            osis_books.covers(["Jas.1.26", "Jas.1.27", "Jas.2.1"]),
            ["Jas.1.26-Jas.2.1"],
        )

    def test_a_run_does_not_cross_a_skipped_chapter(self) -> None:
        self.assertEqual(
            osis_books.covers(["Jas.1.27", "Jas.3.1"]), ["Jas.1.27", "Jas.3.1"]
        )

    def test_a_run_does_not_cross_into_another_book(self) -> None:
        self.assertEqual(
            osis_books.covers(["Luke.1.1", "Luke.1.2", "John.1.1"]),
            ["Luke.1.1-Luke.1.2", "John.1.1"],
        )

    def test_books_are_in_canonical_order_whatever_the_file_order(self) -> None:
        self.assertEqual(
            osis_books.covers(["John.1.1", "Luke.1.1", "Gen.1.1"]),
            ["Gen.1.1", "Luke.1.1", "John.1.1"],
        )

    def test_a_repeated_verse_is_counted_once(self) -> None:
        self.assertEqual(
            osis_books.covers(["Rev.1.1", "Rev.1.1", "Rev.1.2"]), ["Rev.1.1-Rev.1.2"]
        )

    def test_what_is_not_a_verse_is_left_out(self) -> None:
        self.assertEqual(osis_books.covers(["Rev", "Rev.1", "Rev.1.1"]), ["Rev.1.1"])


class WhatCountsAsWhole(unittest.TestCase):
    def refs(self, *references: str) -> list[tuple[str, int, int]]:
        return [osis_books.parse(reference) for reference in references]

    def test_either_versifications_ending_is_whole(self) -> None:
        # Malachi ends at 4:6 in the KJV and 3:24 in a Hebrew Bible.
        hebrew = self.refs("Mal.1.1", "Mal.2.1", "Mal.3.24")
        english = self.refs("Mal.1.1", "Mal.2.1", "Mal.3.1", "Mal.4.6")
        self.assertTrue(osis_books.complete(hebrew, "Mal"))
        self.assertTrue(osis_books.complete(english, "Mal"))

    def test_stopping_short_of_the_ending_is_not(self) -> None:
        self.assertFalse(osis_books.complete(self.refs("Obad.1.1", "Obad.1.20"), "Obad"))

    def test_a_book_with_no_stated_ending_is_judged_on_its_chapters(self) -> None:
        self.assertTrue(osis_books.complete(self.refs("Tob.1.1", "Tob.2.1"), "Tob"))
        self.assertFalse(osis_books.complete(self.refs("Tob.1.1", "Tob.3.1"), "Tob"))

    def test_a_book_not_present_is_not_whole(self) -> None:
        self.assertFalse(osis_books.complete(self.refs("Gen.1.1"), "Exod"))


if __name__ == "__main__":
    unittest.main()
