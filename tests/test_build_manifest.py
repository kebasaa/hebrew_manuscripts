"""Checks on the manifest generator.

Run from the repository root, with nothing to install::

    python -m unittest discover tests

Only two properties are tested, but they are the two the whole download feature
rests on. If either breaks, Milah tells every reader that every manuscript needs
updating, and taking the update does not settle it — a failure that looks like
the feature working rather than like a bug.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import build_manifest  # noqa: E402


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
    <rights>CC BY-NC-SA 4.0</rights>
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

    def test_two_builds_agree(self) -> None:
        self.assertEqual(
            build_manifest.build(self.MANUSCRIPTS),
            build_manifest.build(self.MANUSCRIPTS),
        )


if __name__ == "__main__":
    unittest.main()
