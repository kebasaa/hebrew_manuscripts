"""Checks on the manifest generator.

Run from the repository root, with nothing to install::

    python -m unittest discover tests

Only two properties are tested, but they are the two the whole download feature
rests on. If either breaks, Milah tells every reader that every manuscript needs
updating, and taking the update does not settle it — a failure that looks like
the feature working rather than like a bug.
"""

from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import build_manifest  # noqa: E402
import osis_books  # noqa: E402


#: Small but real: a header the generator actually reads, so a change to how it
#: reads one is caught here rather than only against the published texts.
OSIS = """<?xml version="1.0" encoding="UTF-8"?>
<osis xmlns="http://www.bibletechnologies.net/2003/OSIS/namespace">
 <osisText osisIDWork="Test" xml:lang="he">
  <header>
   <work osisWork="Test">
    <title>Revelation (British Library, Sloane MS 237)</title>
    <date>ca. 1730</date>
    <description type="x-contents">1:1-2:13</description>
    <rights type="x-copyright">© 2017 by Nehemia Gordon</rights>
    <rights type="x-license">CC BY-NC-SA 4.0</rights>
   </work>
  </header>
  <div type="book" osisID="Rev"><verse osisID="Rev.1.1">TEXT</verse></div>
 </osisText>
</osis>
"""


class TheHashIsStableAcrossLineEndings(unittest.TestCase):
    """The same text checked out two ways must measure the same.

    ``.gitattributes`` sets ``* text=auto``, so a clone made with
    ``core.autocrlf=true`` holds CRLF where GitHub serves LF. Milah downloads
    and keeps the LF form, so if the generator measured whatever happened to be
    on disk, a manifest built on such a clone would disagree with the app about
    every file at once.
    """

    def test_crlf_and_lf_agree(self) -> None:
        with TemporaryDirectory() as folder:
            unix = Path(folder) / "REV_unix.osis"
            dos = Path(folder) / "REV_dos.osis"
            unix.write_bytes(OSIS.encode("utf-8"))
            dos.write_bytes(OSIS.replace("\n", "\r\n").encode("utf-8"))

            lf = build_manifest.describe(unix)
            crlf = build_manifest.describe(dos)

        self.assertIsNotNone(lf)
        self.assertIsNotNone(crlf)
        self.assertEqual(lf["sha256"], crlf["sha256"])
        # And the size the download window quotes has to agree too, or a reader
        # would be told a figure the transfer then contradicts.
        self.assertEqual(lf["bytes"], crlf["bytes"])

    def test_a_real_change_still_moves_the_hash(self) -> None:
        """Guards against the normalisation being so eager it flattens content.

        A test that only asserts two things are equal passes just as happily
        when everything hashes alike.
        """
        with TemporaryDirectory() as folder:
            before = Path(folder) / "REV_before.osis"
            after = Path(folder) / "REV_after.osis"
            before.write_bytes(OSIS.encode("utf-8"))
            # Same length, one character different — the case a size cannot see,
            # and the reason the manifest carries a checksum at all. The real
            # instance was a shelfmark reading "Sloane MS 237" in one place and
            # "MS Sloane 273" in another; 237 is the British Library's own
            # reading, and the files now say so throughout. The mutation here
            # runs the other way only because it is the shorter thing to write.
            after.write_bytes(OSIS.replace("237", "273").encode("utf-8"))

            first = build_manifest.describe(before)
            second = build_manifest.describe(after)

        self.assertEqual(first["bytes"], second["bytes"])
        self.assertNotEqual(first["sha256"], second["sha256"])


class CopyrightAndLicenceAreReadApart(unittest.TestCase):
    """Two different `<rights>` elements, told apart by `type`.

    Conflating them was the actual bug this split fixes: a translation marked
    "all rights reserved" and one with no stated terms at all could not both
    be described by one field.
    """

    def test_the_typed_elements_are_read_separately(self) -> None:
        with TemporaryDirectory() as folder:
            path = Path(folder) / "REV_typed.osis"
            path.write_bytes(OSIS.encode("utf-8"))
            entry = build_manifest.describe(path)

        self.assertEqual(entry["rights"], "© 2017 by Nehemia Gordon")
        self.assertEqual(entry["license"], "CC BY-NC-SA 4.0")

    def test_an_untyped_rights_element_is_read_as_copyright(self) -> None:
        """Every file in this repository carried a bare `<rights>` before the
        split existed. An unretrofitted header must degrade to answering one
        question, not raise or answer neither."""
        untyped = OSIS.replace(
            '<rights type="x-copyright">© 2017 by Nehemia Gordon</rights>\n'
            '    <rights type="x-license">CC BY-NC-SA 4.0</rights>',
            "<rights>CC BY-NC-SA 4.0</rights>",
        )
        with TemporaryDirectory() as folder:
            path = Path(folder) / "REV_untyped.osis"
            path.write_bytes(untyped.encode("utf-8"))
            entry = build_manifest.describe(path)

        self.assertEqual(entry["rights"], "CC BY-NC-SA 4.0")
        self.assertEqual(entry["license"], "")

    def test_copyright_may_be_empty(self) -> None:
        """A bare, uncommented transcription may credit nobody in particular —
        empty, not fabricated."""
        no_copyright = OSIS.replace(
            '<rights type="x-copyright">© 2017 by Nehemia Gordon</rights>', ""
        )
        with TemporaryDirectory() as folder:
            path = Path(folder) / "REV_nocopy.osis"
            path.write_bytes(no_copyright.encode("utf-8"))
            entry = build_manifest.describe(path)

        self.assertEqual(entry["rights"], "")
        self.assertEqual(entry["license"], "CC BY-NC-SA 4.0")


class TheCataloguingFieldsAreRead(unittest.TestCase):
    """What the download window shows beside a manuscript's title.

    All four describe the manuscript rather than the file, which is why a
    translation carries the same answers as the witness it renders: it is a
    rendering of the same physical object.
    """

    HEADER = """<?xml version="1.0" encoding="UTF-8"?>
<osis xmlns="http://www.bibletechnologies.net/2003/OSIS/namespace">
 <osisText osisIDWork="Test" xml:lang="he">
  <header>
   <work osisWork="Test">
    <title>Revelation</title>
    <description type="x-contents">1:1-2:13</description>
    <description type="x-folios">1r-4v</description>
    <description type="x-translated-from">Translated from the Greek</description>
    <description type="x-exemplar">Copied from Cambridge MS Oo.1.32</description>
    <identifier type="OSIS">Test</identifier>
    <identifier type="x-shelfmark">British Library, Sloane MS 237</identifier>
   </work>
  </header>
  <div type="book" osisID="Rev"><verse osisID="Rev.1.1">TEXT</verse></div>
 </osisText>
</osis>
"""

    def describe(self, header: str) -> dict:
        with TemporaryDirectory() as folder:
            path = Path(folder) / "REV_test.osis"
            path.write_bytes(header.encode("utf-8"))
            return build_manifest.describe(path)

    def test_each_field_reaches_the_manifest(self) -> None:
        entry = self.describe(self.HEADER)
        self.assertEqual(entry["shelfmark"], "British Library, Sloane MS 237")
        self.assertEqual(entry["folios"], "1r-4v")
        self.assertEqual(entry["translatedFrom"], "Translated from the Greek")
        self.assertEqual(entry["exemplar"], "Copied from Cambridge MS Oo.1.32")

    def test_the_shelfmark_is_not_confused_with_the_osis_identifier(self) -> None:
        # Both are <identifier>; only the type tells them apart, and reading the
        # first one would file every manuscript under its work id.
        self.assertNotEqual(self.describe(self.HEADER)["shelfmark"], "Test")

    def test_x_contents_is_still_its_own_field(self) -> None:
        # Four descriptions now sit side by side, told apart only by type. The
        # sentence is "contents"; "covers" is the list computed from the verses.
        entry = self.describe(self.HEADER)
        self.assertEqual(entry["contents"], "1:1-2:13")
        self.assertEqual(entry["covers"], ["Rev.1.1"])

    def test_absent_fields_are_empty_rather_than_missing(self) -> None:
        # Most manuscripts answer none of these. Absent has to be ordinary: a
        # catalogue that demanded them is one nobody could add to.
        entry = self.describe(OSIS)
        for field in ("shelfmark", "folios", "translatedFrom", "exemplar"):
            self.assertEqual(entry[field], "", field)

    def test_the_certainty_is_read_off_the_subtype(self) -> None:
        # What a text renders and whether that is settled are two questions.
        entry = self.describe(
            self.HEADER.replace(
                '<description type="x-translated-from">',
                '<description type="x-translated-from" subType="x-certain">',
            )
        )
        self.assertEqual(entry["translationCertainty"], "certain")
        # The prose is untouched by the verdict beside it.
        self.assertEqual(entry["translatedFrom"], "Translated from the Greek")

    def test_a_description_with_no_subtype_records_no_verdict(self) -> None:
        # The state every header in this repository is in: the field is there
        # to be filled, and until it is, nothing has been claimed.
        self.assertEqual(self.describe(self.HEADER)["translationCertainty"], "")

    def test_a_subtype_without_the_x_prefix_is_not_taken(self) -> None:
        # The schema's rule for a value it does not define is the x- prefix, and
        # something else in that attribute is not this vocabulary.
        entry = self.describe(
            self.HEADER.replace(
                '<description type="x-translated-from">',
                '<description type="x-translated-from" subType="certain">',
            )
        )
        self.assertEqual(entry["translationCertainty"], "")

    def test_an_original_composition_can_say_so(self) -> None:
        # The other half of the silence problem: an empty field used to mean
        # both "an original Hebrew text" and "nobody knows".
        entry = self.describe(
            self.HEADER.replace(
                '<description type="x-translated-from">Translated from the Greek'
                "</description>",
                '<description type="x-translated-from" subType="x-original">'
                "An original Hebrew composition.</description>",
            )
        )
        self.assertEqual(entry["translationCertainty"], "original")

    def test_an_empty_element_reads_as_no_answer(self) -> None:
        # The shape left in the published headers for the owner to fill in.
        entry = self.describe(
            self.HEADER.replace(
                '<description type="x-exemplar">Copied from Cambridge MS Oo.1.32'
                "</description>",
                '<description type="x-exemplar"/>',
            )
        )
        self.assertEqual(entry["exemplar"], "")


def text(name: str, verses: list[str], header: str = "") -> dict:
    """The entry for a file called ``name`` holding ``verses``, as milestones."""
    body = "".join(
        f'<verse sID="{ref}" osisID="{ref}"/>TEXT<verse eID="{ref}"/>' for ref in verses
    )
    # A translation declares English, or the generator rightly warns about it.
    language = "en" if name.endswith("_translation.osis") else "he"
    document = f"""<?xml version="1.0" encoding="UTF-8"?>
<osis xmlns="http://www.bibletechnologies.net/2003/OSIS/namespace">
 <osisText osisIDWork="Test" xml:lang="{language}">
  <header><work osisWork="Test"><title>Test</title>{header}</work></header>
  <div type="book">{body}</div>
 </osisText>
</osis>
"""
    with TemporaryDirectory() as folder:
        path = Path(folder) / name
        path.write_bytes(document.encode("utf-8"))
        return build_manifest.describe(path)


def chapter(book: str, number: int, verses: int) -> list[str]:
    return [f"{book}.{number}.{verse}" for verse in range(1, verses + 1)]


#: The whole of James, 108 verses, as the KJV numbers it.
JAMES = (
    chapter("Jas", 1, 27)
    + chapter("Jas", 2, 26)
    + chapter("Jas", 3, 18)
    + chapter("Jas", 4, 17)
    + chapter("Jas", 5, 20)
)


class AnEntrySaysWhereItSitsInTheCanon(unittest.TestCase):
    """``book``, ``category``, ``fragment`` and ``covers``.

    What lets Milah group its library by testament and tell a fragment from a
    complete witness, without keeping a canon of its own that could disagree
    with this one.
    """

    def test_the_book_is_the_osis_id_not_the_filename_prefix(self) -> None:
        self.assertEqual(text("JAS_x_hebrew_commented.osis", JAMES)["book"], "Jas")
        self.assertEqual(text("JOH_x_hebrew_commented.osis", ["John.1.1"])["book"], "John")
        self.assertEqual(text("MAT_x_hebrew_commented.osis", ["Matt.1.1"])["book"], "Matt")
        self.assertEqual(text("GEN_x_hebrew_commented.osis", ["Gen.1.1"])["book"], "Gen")

    def test_a_whole_testament_names_no_book_but_still_a_category(self) -> None:
        entry = text("NT_x_hebrew.osis", ["Matt.1.1", "Rev.22.21"])
        self.assertEqual(entry["book"], "")
        self.assertEqual(entry["category"], "nt")

    def test_the_category_follows_the_testament(self) -> None:
        self.assertEqual(text("GEN_x_hebrew.osis", ["Gen.1.1"])["category"], "ot")
        self.assertEqual(text("SIR_x_hebrew.osis", ["Sir.1.1"])["category"], "ot")
        self.assertEqual(text("REV_x_hebrew.osis", ["Rev.1.1"])["category"], "nt")

    def test_a_text_with_no_biblical_verse_is_other(self) -> None:
        entry = text("Pirkei_x_hebrew.osis", [])
        self.assertEqual(entry["book"], "")
        self.assertEqual(entry["category"], "other")
        self.assertFalse(entry["fragment"])
        self.assertEqual(entry["covers"], [])

    def test_the_header_may_state_the_category(self) -> None:
        # The same mechanism every other hand-written fact uses: a typed
        # <description> inside <work>.
        entry = text(
            "REV_x_hebrew.osis",
            ["Rev.1.1"],
            '<description type="x-category">other</description>',
        )
        self.assertEqual(entry["category"], "other")

    def test_a_category_outside_the_vocabulary_is_not_taken(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            entry = text(
                "REV_x_hebrew.osis",
                ["Rev.1.1"],
                '<description type="x-category">apocrypha</description>',
            )
        self.assertEqual(entry["category"], "nt")
        self.assertIn("apocrypha", printed.getvalue())

    def test_covers_collapses_the_verses_into_ranges(self) -> None:
        entry = text(
            "REV_x_hebrew.osis", chapter("Rev", 1, 20) + chapter("Rev", 2, 13)
        )
        self.assertEqual(entry["covers"], ["Rev.1.1-Rev.2.13"])

    def test_a_missing_verse_splits_the_range(self) -> None:
        verses = [ref for ref in chapter("Rev", 1, 10) if ref != "Rev.1.5"]
        self.assertEqual(
            text("REV_x_hebrew.osis", verses)["covers"],
            ["Rev.1.1-Rev.1.4", "Rev.1.6-Rev.1.10"],
        )

    def test_verses_out_of_order_are_put_in_order(self) -> None:
        # Revelation in MS Oo.1.16 has 2:22 before 2:21: the manuscript's order,
        # kept in the text, but not what a reference list should say.
        verses = ["Rev.2.20", "Rev.2.22", "Rev.2.21", "Rev.2.23"]
        self.assertEqual(text("REV_x_hebrew.osis", verses)["covers"], ["Rev.2.20-Rev.2.23"])

    def test_a_whole_book_is_not_a_fragment(self) -> None:
        self.assertFalse(text("JAS_x_hebrew.osis", JAMES)["fragment"])

    def test_a_book_that_stops_short_is_a_fragment(self) -> None:
        self.assertTrue(text("JAS_x_hebrew.osis", JAMES[:-1])["fragment"])

    def test_a_book_that_starts_late_is_a_fragment(self) -> None:
        self.assertTrue(text("JAS_x_hebrew.osis", JAMES[1:])["fragment"])

    def test_a_book_that_skips_a_chapter_is_a_fragment(self) -> None:
        verses = [ref for ref in JAMES if not ref.startswith("Jas.3.")]
        self.assertTrue(text("JAS_x_hebrew.osis", verses)["fragment"])

    def test_a_verse_missing_inside_a_chapter_is_not_a_fragment(self) -> None:
        # MS Oo.1.32's James has no independent 2:26: its 2:15 spans two KJV
        # verses. That is a numbering difference, not a missing leaf.
        verses = [ref for ref in JAMES if ref != "Jas.2.26"]
        self.assertFalse(text("JAS_x_hebrew.osis", verses)["fragment"])

    def test_a_testament_missing_a_book_is_a_fragment(self) -> None:
        entry = text("NT_x_hebrew.osis", JAMES)
        self.assertTrue(entry["fragment"])
        self.assertEqual(entry["covers"], ["Jas.1.1-Jas.5.20"])

    def test_the_translation_carries_the_same_placement(self) -> None:
        # A rendering of the same witness covers the same verses.
        witness = text("JAS_x_hebrew_commented.osis", JAMES)
        rendering = text("JAS_x_translation.osis", JAMES)
        for field in ("book", "category", "fragment", "covers"):
            self.assertEqual(witness[field], rendering[field], field)


class LocalOnlyTextsAreNotCatalogued(unittest.TestCase):
    """Some texts are generated but must not be offered for download.

    The Bible Society in Israel grants no reuse permission for HaBrit
    HaChadasha, so `pdf2osis convert-all` writes it into manuscripts/ for local
    use while .gitignore keeps it out of the repository. Cataloguing it anyway
    would advertise a download that is not there to fetch.
    """

    def build(self, *names: str) -> list[dict]:
        with TemporaryDirectory() as folder:
            for name in names:
                (Path(folder) / name).write_bytes(OSIS.encode("utf-8"))
            return build_manifest.build(Path(folder))

    def test_the_local_only_text_is_left_out(self) -> None:
        entries = self.build(
            "REV_Sloane237_hebrew_commented.osis",
            "NT_BSI_HaBritHaChadasha_hebrew.osis",
            "NT_BSI_HaBritHaChadasha_hebrew_commented.osis",
        )
        self.assertEqual(
            [entry["file"] for entry in entries],
            ["REV_Sloane237_hebrew_commented.osis"],
        )

    def test_it_is_excluded_by_name_not_by_being_unreadable(self) -> None:
        # The file parses perfectly well; it is withheld on licence grounds,
        # so the exclusion must be deliberate rather than a happy accident.
        self.assertEqual(self.build("NT_BSI_HaBritHaChadasha_hebrew.osis"), [])
        self.assertTrue(
            "NT_BSI_".startswith(build_manifest.LOCAL_ONLY_PREFIXES[0][:7])
        )

    def test_everything_else_still_reaches_the_catalogue(self) -> None:
        # Both named `_hebrew`, matching what the fixture header declares, so
        # the run stays quiet: a warning here would be about the fixture.
        entries = self.build(
            "NT_Delitzsch_hebrew.osis", "REV_Sloane237_hebrew.osis"
        )
        self.assertEqual(len(entries), 2)


class RegeneratingReproducesTheManifest(unittest.TestCase):
    """Building twice over unchanged files must give the same answer.

    Otherwise a routine rebuild would land in the repository looking exactly
    like a correction, and every reader would be offered an update that changes
    nothing.
    """

    #: Where the texts and their catalogue live. Spelled out here rather than
    #: read back from the generator, which would only assert the module against
    #: itself. These are also asserted rather than skipped around: they are
    #: fixed parts of the repository, and a suite that goes quietly green when
    #: they move is worse than no suite — which is exactly what happened when
    #: the texts went from `data/` to `manuscripts/`.
    REPOSITORY = Path(__file__).resolve().parents[1]
    MANUSCRIPTS = REPOSITORY / "manuscripts"
    MANIFEST = REPOSITORY / "manifest_manuscripts.json"

    def test_the_published_manifest_is_current(self) -> None:
        import json

        self.assertTrue(self.MANIFEST.is_file(), f"no manifest at {self.MANIFEST}")

        entries = build_manifest.build(self.MANUSCRIPTS)
        self.assertTrue(entries, f"no .osis files in {self.MANUSCRIPTS}")

        held = json.loads(self.MANIFEST.read_text(encoding="utf-8"))
        # Compared as data rather than as bytes: this is asserting that the
        # manifest is not stale, not that json.dumps formats identically.
        self.assertEqual(
            held["manuscripts"],
            entries,
            f"{self.MANIFEST.name} is out of date — re-run src/build_manifest.py",
        )

    def test_entries_name_a_file_not_a_path(self) -> None:
        """The manifest must stay indifferent to where the texts are kept.

        Now that the catalogue sits at the root and the texts do not, an entry
        carrying `manuscripts/NAME.osis` would be a path stated twice — once
        here and once in Milah — and moving the folder would mean rewriting
        every entry rather than one constant.
        """
        for entry in build_manifest.build(self.MANUSCRIPTS):
            self.assertNotIn("/", entry["file"])
            self.assertEqual(entry["file"], Path(entry["file"]).name)

    def test_the_generator_defaults_here(self) -> None:
        """The no-argument run must read and write where Milah looks.

        The defaults are the whole interface: nobody passes --source in
        practice, so one pointing at a folder that has since been renamed is a
        generator that quietly does nothing.
        """
        defaults = build_manifest.parser().parse_args([])
        self.assertEqual(defaults.source, self.MANUSCRIPTS)
        self.assertEqual(defaults.out, self.MANIFEST)
        self.assertTrue(defaults.source.is_dir(), f"no {defaults.source}")

    def test_every_entry_is_placed_in_the_canon(self) -> None:
        # Asked of the published file, which is what Milah reads.
        import json

        held = json.loads(self.MANIFEST.read_text(encoding="utf-8"))
        for entry in held["manuscripts"]:
            name = entry["file"]
            self.assertIn(entry["category"], osis_books.CATEGORIES, name)
            if entry["book"]:
                self.assertEqual(osis_books.book_id(entry["book"]), entry["book"], name)
                self.assertEqual(osis_books.category_of(entry["book"]), entry["category"], name)
            self.assertIsInstance(entry["fragment"], bool, name)
            self.assertIsInstance(entry["covers"], list, name)
            for reference in entry["covers"]:
                for end in reference.split("-"):
                    self.assertIsNotNone(osis_books.parse(end), f"{name}: {reference}")
            self.assertIsInstance(entry["contents"], str, name)

    def test_two_builds_agree(self) -> None:
        self.assertEqual(
            build_manifest.build(self.MANUSCRIPTS),
            build_manifest.build(self.MANUSCRIPTS),
        )


if __name__ == "__main__":
    unittest.main()
