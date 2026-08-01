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
            # instance is a shelfmark reading "Sloane MS 237" in one place and
            # "MS Sloane 273" in another.
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

    def test_the_published_manifest_is_current(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        published = repository / "manifest.json"
        if not published.is_file():
            self.skipTest("no manifest.json to compare against")

        import json

        entries = build_manifest.build(repository / "data")
        self.assertTrue(entries, "no .osis files found in data/")

        held = json.loads(published.read_text(encoding="utf-8"))
        # Compared as data rather than as bytes: this is asserting that the
        # manifest is not stale, not that json.dumps formats identically.
        self.assertEqual(
            held["manuscripts"],
            entries,
            "manifest.json does not match data/ — re-run src/build_manifest.py",
        )

    def test_two_builds_agree(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        source = repository / "data"
        if not source.is_dir():
            self.skipTest("no data/ folder")
        self.assertEqual(build_manifest.build(source), build_manifest.build(source))


if __name__ == "__main__":
    unittest.main()
