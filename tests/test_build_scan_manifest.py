"""Checks on the scan manifest generator.

Run from the repository root, with nothing to install::

    python -m unittest discover tests

Nothing here touches the network. Its sibling ``test_build_manifest.py`` can
rebuild its manifest and compare, because that generator reads files in this
repository; this one reads the holding libraries, and a test that needs the
internet is a test that fails on a train — and that quietly starts testing
Cambridge's uptime rather than this code.

So the split is: the transforms are pinned against recorded fixtures of each
shape the generator meets, and the committed manifest is checked for shape
rather than regenerated.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import build_scan_manifest  # noqa: E402


#: Cut down from the real answer for MS-OO-00001-00032, keeping every shape the
#: generator reaches into: a field that is an object with displayForm, one that
#: is a bare list, and two that bury their value one or two lists deep.
CUDL_RECORD = {
    "numberOfPages": 3,
    "descriptiveMetadata": [
        {
            "title": {"displayForm": "Hebrew translation of the New Testament"},
            "shelfLocator": {"displayForm": "MS Oo.1.32"},
            "physicalLocation": {"displayForm": "Cambridge University Library"},
            "material": {"displayForm": "Paper"},
            "languages": ["Hebrew"],
            "creations": {
                "value": [
                    {
                        "places": {"value": [{"displayForm": "Kochi"}]},
                        "dateDisplay": {"displayForm": "Eighteenth century"},
                    }
                ]
            },
            "provenances": {"value": [{"displayForm": "Presented in 1809"}]},
            "displayImageRights": "Zooming image © CUL, All rights reserved.",
            "downloadImageRights": "… (CC BY-NC 3.0)",
        }
    ],
    "pages": [
        {"sequence": 1, "label": "front cover", "IIIFImageURL": "MS-OO-00001-00032-000-00001"},
        {"sequence": 2, "label": "1r", "IIIFImageURL": "MS-OO-00001-00032-000-00002"},
        # Released pages only carry an image; one that is not has nothing to
        # point at, and must be left out rather than pointed at anyway.
        {"sequence": 3, "label": "1v"},
    ],
}

#: Cut from the real TEI for Sloane MS 237, keeping every shape that has caught
#: a parser out: a title element that describes the record rather than the
#: manuscript, an origin date carrying only attributes, no origin place at all,
#: a master that is a TIFF, a web derivative that is not the first graphic, and
#: an endleaf label repeated at both ends of the codex.
OPENN_TEI = """<?xml version='1.0' encoding='UTF-8'?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
 <teiHeader>
  <fileDesc>
   <titleStmt>
    <title>Description of British Library, Sloane MS 237: The Revelation of St John.</title>
   </titleStmt>
   <publicationStmt>
    <availability>
     <licence target="http://creativecommons.org/publicdomain/mark/1.0/">These images
      are free of known copyright restrictions and in the public domain.</licence>
     <licence target="https://creativecommons.org/publicdomain/zero/1.0/legalcode">
      British Library has waived all copyright to this metadata.</licence>
    </availability>
   </publicationStmt>
   <sourceDesc>
    <msDesc>
     <msIdentifier>
      <settlement>London</settlement>
      <repository>British Library</repository>
      <idno type="call-number">Sloane MS 237</idno>
     </msIdentifier>
     <msContents>
      <textLang mainLang="he">Hebrew</textLang>
      <msItem><title>The Revelation of St John in Hebrew translation.</title></msItem>
     </msContents>
     <physDesc>
      <objectDesc><supportDesc material="paper"><support><p>Paper</p></support></supportDesc></objectDesc>
     </physDesc>
     <history>
      <origin>
       <origDate notBefore="1500" notAfter="1699"/>
       <p>Between 1500 and 1699</p>
      </origin>
      <provenance>Part of the Sloane bequest.</provenance>
     </history>
    </msDesc>
   </sourceDesc>
  </fileDesc>
 </teiHeader>
 <facsimile>
  <surface n="front">
   <graphic height="6011px" url="master/13561_0000.tif" width="4548px"/>
   <graphic height="190px" url="thumb/13561_0000_thumb.jpg" width="143px"/>
   <graphic height="1800px" url="web/13561_0000_web.jpg" width="1361px"/>
  </surface>
  <surface n="i-r">
   <graphic height="190px" url="thumb/13561_0002_thumb.jpg" width="143px"/>
   <graphic height="1800px" url="web/13561_0002_web.jpg" width="1270px"/>
  </surface>
  <surface n="1r">
   <graphic height="1800px" url="web/13561_0006_web.jpg" width="1270px"/>
  </surface>
  <surface n="i-r">
   <graphic height="1800px" url="web/13561_0014_web.jpg" width="1270px"/>
  </surface>
  <surface n="unreleased"/>
 </facsimile>
</TEI>
"""

IIIF_V2 = {
    "@context": "http://iiif.io/api/presentation/2/context.json",
    "label": "A codex somewhere else",
    "attribution": "Provided by Somewhere",
    "sequences": [
        {
            "canvases": [
                {
                    "label": "1r",
                    "images": [
                        {
                            "resource": {
                                # Deliberately the same string as the service:
                                # this is how Cambridge writes it, and taking it
                                # would give a JP2 nobody can fetch.
                                "@id": "https://img.example/iiif/one.jp2",
                                "service": {"@id": "https://img.example/iiif/one.jp2"},
                            }
                        }
                    ],
                }
            ]
        }
    ],
}

IIIF_V3 = {
    "@context": "http://iiif.io/api/presentation/3/context.json",
    "type": "Manifest",
    "label": {"en": ["A codex in the new shape"]},
    "items": [
        {
            "label": {"en": ["1r"]},
            "items": [
                {
                    "items": [
                        {
                            "body": {
                                # A list in v3, and `id` without the @.
                                "service": [{"id": "https://img.example/iiif/one"}]
                            }
                        }
                    ]
                }
            ],
        }
    ],
}


class ALinkIsRecognisedOrRefused(unittest.TestCase):
    """An address nothing can read must be reported, never guessed at.

    A guess produces a manifest entry that looks perfectly well formed and
    fetches nothing — which surfaces as a blank folio in front of somebody
    trying to transcribe, a long way from here.
    """

    def test_the_cambridge_viewer_address(self) -> None:
        source, item = build_scan_manifest.parse_link(
            "https://cudl.lib.cam.ac.uk/view/MS-OO-00001-00032/1"
        )
        self.assertEqual(source, "cudl")
        self.assertEqual(item, "MS-OO-00001-00032")

    def test_the_page_number_is_not_part_of_the_item(self) -> None:
        # A reader copies the address of whichever folio they were looking at.
        for address in (
            "https://cudl.lib.cam.ac.uk/view/MS-OO-00001-00032",
            "https://cudl.lib.cam.ac.uk/view/MS-OO-00001-00032/",
            "https://cudl.lib.cam.ac.uk/view/MS-OO-00001-00032/265",
            "https://cudl.lib.cam.ac.uk/view/MS-OO-00001-00032/12?x=1",
        ):
            self.assertEqual(
                build_scan_manifest.parse_link(address),
                ("cudl", "MS-OO-00001-00032"),
                address,
            )

    def test_every_openn_address_a_reader_might_copy(self) -> None:
        # OPenn has no viewer, so a reader arrives at whichever of these Apache
        # happened to show them.
        for address in (
            "https://openn.library.upenn.edu/Data/0047/html/sloane_ms_237.html",
            "https://openn.library.upenn.edu/Data/0047/sloane_ms_237/",
            "https://openn.library.upenn.edu/Data/0047/sloane_ms_237",
            "https://openn.library.upenn.edu/Data/0047/sloane_ms_237/data/"
            "sloane_ms_237_TEI.xml",
            "https://openn.library.upenn.edu/Data/0047/sloane_ms_237/data/"
            "web/13561_0006_web.jpg",
        ):
            self.assertEqual(
                build_scan_manifest.parse_link(address),
                ("openn", "0047/sloane_ms_237"),
                address,
            )

    def test_a_collection_listing_is_not_a_manuscript(self) -> None:
        # The browse pages live under html/ beside the manuscripts, so a reader
        # who copied a listing must not come back with one called "html".
        for address in (
            "https://openn.library.upenn.edu/Data/0047/",
            "https://openn.library.upenn.edu/Data/0047/html/",
        ):
            self.assertEqual(build_scan_manifest.parse_link(address)[0], "", address)

    def test_a_plain_iiif_manifest_is_taken_as_itself(self) -> None:
        source, item = build_scan_manifest.parse_link(
            "https://digi.vatlib.it/iiif/MSS_Vat.ebr.66/manifest.json"
        )
        self.assertEqual(source, "iiif")
        self.assertTrue(item.endswith("manifest.json"))

    def test_an_unknown_address_names_no_source(self) -> None:
        for address in ("https://example.com/some/manuscript", "", "not a url"):
            self.assertEqual(build_scan_manifest.parse_link(address)[0], "", address)


class MetadataArrivesAsMarkup(unittest.TestCase):
    """Library records are written for a viewer, and carry tags to prove it.

    Cambridge wraps several values in ``<p>`` and one in a ``<div>`` of list
    styling around an ``<a onclick='store.loadPage(265)'>`` that means nothing
    outside its own site. Milah shows these in a sidebar, where a tag is not a
    tag but four stray characters.
    """

    def test_tags_are_taken_out(self) -> None:
        self.assertEqual(
            build_scan_manifest.strip_html("<p>Bound in half morocco, 1916</p>"),
            "Bound in half morocco, 1916",
        )

    def test_a_viewer_link_leaves_its_text_behind(self) -> None:
        self.assertEqual(
            build_scan_manifest.strip_html(
                "<div style='list-style-type: disc;'><p>Sefardi script; "
                "<a href='' onclick='store.loadPage(265);return false;'>132r-160v</a> "
                "copied by David Cohen.</p></div>"
            ),
            "Sefardi script; 132r-160v copied by David Cohen.",
        )

    def test_nothing_is_still_nothing(self) -> None:
        self.assertEqual(build_scan_manifest.strip_html(""), "")
        self.assertEqual(build_scan_manifest.strip_html(None), "")


class TheCambridgeRecordIsReadIntoAnEntry(unittest.TestCase):
    """Each field is buried differently, and each has to come out flat."""

    def setUp(self) -> None:
        # Answered from the fixture rather than from Cambridge.
        self._real = build_scan_manifest.fetch_json
        build_scan_manifest.fetch_json = lambda url: CUDL_RECORD
        self.entry = build_scan_manifest.cudl_scan("MS-OO-00001-00032", 1024)

    def tearDown(self) -> None:
        build_scan_manifest.fetch_json = self._real

    def test_the_plain_fields(self) -> None:
        self.assertEqual(self.entry["title"], "Hebrew translation of the New Testament")
        self.assertEqual(self.entry["shelfmark"], "MS Oo.1.32")
        self.assertEqual(self.entry["repository"], "Cambridge University Library")
        self.assertEqual(self.entry["material"], "Paper")
        self.assertEqual(self.entry["language"], "Hebrew")

    def test_the_buried_fields(self) -> None:
        # Origin is two lists deep, the date one, provenance one.
        self.assertEqual(self.entry["origin"], "Kochi")
        self.assertEqual(self.entry["date"], "Eighteenth century")
        self.assertEqual(self.entry["provenance"], "Presented in 1809")

    def test_the_terms_that_govern_fetching_are_the_ones_recorded(self) -> None:
        # displayImageRights covers Cambridge's own zooming viewer and says "All
        # rights reserved"; Milah fetches through the Image API, which is the
        # Creative Commons one. Recording the wrong one would misstate both.
        self.assertIn("CC BY-NC 3.0", self.entry["licence"])
        self.assertNotIn("All rights reserved", self.entry["licence"])
        self.assertEqual(self.entry["attribution"], "Provided by Cambridge University Library")

    def test_a_page_with_no_image_is_left_out(self) -> None:
        self.assertEqual(len(self.entry["pages"]), 2)
        self.assertEqual([page["n"] for page in self.entry["pages"]], [1, 2])

    def test_the_folio_labels_survive(self) -> None:
        # These are folio numbers — 1r, 1v — and they are what names a page in
        # the transcription window.
        self.assertEqual(self.entry["pages"][1]["label"], "1r")

    def test_the_image_address_is_fetchable(self) -> None:
        self.assertEqual(
            self.entry["pages"][0]["image"],
            "https://images.lib.cam.ac.uk/iiif/MS-OO-00001-00032-000-00001.jp2"
            "/full/1024,/0/default.jpg",
        )

    def test_the_width_is_the_one_asked_for(self) -> None:
        build_scan_manifest.fetch_json = lambda url: CUDL_RECORD
        wider = build_scan_manifest.cudl_scan("MS-OO-00001-00032", 2000)
        self.assertIn("/full/2000,/", wider["pages"][0]["image"])


class TheOpennDescriptionIsReadIntoAnEntry(unittest.TestCase):
    """TEI, because OPenn publishes no API — only files and a description."""

    def setUp(self) -> None:
        import xml.etree.ElementTree as ET

        self._real = build_scan_manifest.fetch_xml
        build_scan_manifest.fetch_xml = lambda url: ET.fromstring(OPENN_TEI)
        self.entry = build_scan_manifest.openn_scan("0047/sloane_ms_237", 1024)

    def tearDown(self) -> None:
        build_scan_manifest.fetch_xml = self._real

    def test_the_title_names_the_manuscript_not_the_record(self) -> None:
        # titleStmt/title is "Description of British Library, Sloane MS 237: …",
        # which is a title for the catalogue entry. The manuscript's own is in
        # msItem — the same trap build_manifest.py documents for OSIS headers.
        self.assertEqual(
            self.entry["title"], "The Revelation of St John in Hebrew translation."
        )

    def test_the_plain_fields(self) -> None:
        self.assertEqual(self.entry["shelfmark"], "Sloane MS 237")
        self.assertEqual(self.entry["repository"], "British Library")
        self.assertEqual(self.entry["language"], "Hebrew")
        self.assertEqual(self.entry["material"], "Paper")
        self.assertEqual(self.entry["provenance"], "Part of the Sloane bequest.")

    def test_the_date_comes_from_the_words_not_the_attributes(self) -> None:
        # origDate is an empty element carrying notBefore and notAfter; what a
        # cataloguer actually wrote is in a sibling paragraph.
        self.assertEqual(self.entry["date"], "Between 1500 and 1699")

    def test_an_absent_origin_place_is_simply_absent(self) -> None:
        # This manuscript has none, and many have none: a cataloguer who does
        # not know where a codex was written does not say.
        self.assertEqual(self.entry["origin"], "")

    def test_the_web_derivative_is_chosen_however_it_is_ordered(self) -> None:
        # The first surface lists master, thumb, then web; the second omits the
        # master; the third has only web. Position cannot be relied on.
        self.assertTrue(
            all("/data/web/" in page["image"] for page in self.entry["pages"]),
            self.entry["pages"],
        )

    def test_a_tiff_master_is_never_chosen(self) -> None:
        # Milah cannot decode TIFF, and OPenn's own robots.txt refuses to serve
        # one to a program. Handing it one would be a blank folio on screen.
        for page in self.entry["pages"]:
            self.assertNotIn("master/", page["image"])
            self.assertFalse(page["image"].endswith(".tif"), page["image"])

    def test_a_surface_with_no_image_is_left_out(self) -> None:
        self.assertEqual(len(self.entry["pages"]), 4)
        self.assertNotIn("unreleased", [page["label"] for page in self.entry["pages"]])

    def test_pages_are_numbered_by_order_because_labels_repeat(self) -> None:
        # i-r is the label of an endleaf at each end of the codex. Keying by it
        # would lose one of them; keying by position keeps both.
        labels = [page["label"] for page in self.entry["pages"]]
        self.assertEqual(labels.count("i-r"), 2)
        self.assertEqual([page["n"] for page in self.entry["pages"]], [1, 2, 3, 4])

    def test_the_image_addresses_are_absolute(self) -> None:
        self.assertEqual(
            self.entry["pages"][2]["image"],
            "https://openn.library.upenn.edu/Data/0047/sloane_ms_237/data/"
            "web/13561_0006_web.jpg",
        )

    def test_the_terms_that_govern_the_images_are_the_ones_recorded(self) -> None:
        # Two licences, told apart only by order: the first covers the images,
        # the second the metadata. It is the first that governs fetching a folio.
        self.assertIn("public domain", self.entry["licence"])
        self.assertNotIn("metadata", self.entry["licence"])
        self.assertIn("British Library", self.entry["attribution"])
        self.assertIn("OPenn", self.entry["attribution"])

    def test_a_description_that_could_not_be_read_is_not_an_entry(self) -> None:
        build_scan_manifest.fetch_xml = lambda url: None
        self.assertIsNone(build_scan_manifest.openn_scan("0047/nothing", 1024))


class BothIIIFVersionsAreRead(unittest.TestCase):
    """v2 is what every library publishes today; v3 is where the spec went."""

    def _scan(self, manifest: dict) -> dict:
        real = build_scan_manifest.fetch_json
        build_scan_manifest.fetch_json = lambda url: manifest
        try:
            return build_scan_manifest.iiif_scan("https://img.example/m", 800)
        finally:
            build_scan_manifest.fetch_json = real

    def test_version_two(self) -> None:
        entry = self._scan(IIIF_V2)
        self.assertEqual(entry["title"], "A codex somewhere else")
        self.assertEqual(entry["attribution"], "Provided by Somewhere")
        self.assertEqual(len(entry["pages"]), 1)
        self.assertEqual(entry["pages"][0]["label"], "1r")
        self.assertEqual(
            entry["pages"][0]["image"],
            "https://img.example/iiif/one.jp2/full/800,/0/default.jpg",
        )

    def test_version_three(self) -> None:
        entry = self._scan(IIIF_V3)
        # A v3 label is a language map, not a string.
        self.assertEqual(entry["title"], "A codex in the new shape")
        self.assertEqual(len(entry["pages"]), 1)
        self.assertEqual(entry["pages"][0]["label"], "1r")
        self.assertEqual(
            entry["pages"][0]["image"],
            "https://img.example/iiif/one/full/800,/0/default.jpg",
        )

    def test_a_manifest_that_could_not_be_read_is_not_an_entry(self) -> None:
        self.assertIsNone(self._scan({}))


class TheLinkListIsReadAsWritten(unittest.TestCase):
    """It is edited by hand, so it has to tolerate being annotated."""

    LINKS = Path(__file__).resolve().parents[1] / "src" / "scan_links.tsv"

    def test_comments_and_blank_lines_are_ignored(self) -> None:
        rows = build_scan_manifest.read_links(self.LINKS)
        self.assertTrue(rows, f"no rows read from {self.LINKS}")
        for row in rows:
            self.assertTrue(row.get("url", "").startswith("http"), row)

    def test_the_generator_defaults_here(self) -> None:
        # The defaults are the whole interface — nobody passes --links — so one
        # pointing at a file that has been renamed is a generator that quietly
        # does nothing.
        self.assertTrue(
            build_scan_manifest.LINKS.is_file(),
            f"no link list at {build_scan_manifest.LINKS}",
        )


class ThePublishedManifestIsUsable(unittest.TestCase):
    """Checked for shape rather than rebuilt, because rebuilding needs Cambridge.

    Every one of these is something Milah relies on and cannot check: a page
    with no image, or an address that is not absolute, is a blank folio in the
    transcription window with nothing to say why.
    """

    MANIFEST = Path(__file__).resolve().parents[1] / "manifest_scans.json"

    def setUp(self) -> None:
        self.assertTrue(self.MANIFEST.is_file(), f"no manifest at {self.MANIFEST}")
        self.document = json.loads(self.MANIFEST.read_text(encoding="utf-8"))

    def test_it_says_what_it_is(self) -> None:
        self.assertEqual(self.document["version"], 1)
        self.assertTrue(self.document["about"])
        self.assertTrue(self.document["scans"], "the manifest offers nothing")

    def test_every_scan_can_be_identified(self) -> None:
        for scan in self.document["scans"]:
            self.assertTrue(scan["id"], scan)
            self.assertTrue(scan["title"], scan["id"])
            self.assertTrue(scan["pages"], scan["id"])

    def test_every_folio_has_somewhere_to_be_fetched_from(self) -> None:
        for scan in self.document["scans"]:
            for page in scan["pages"]:
                self.assertIsInstance(page["n"], int)
                self.assertIn("label", page)
                self.assertTrue(
                    page["image"].startswith("https://"),
                    f"{scan['id']} page {page['n']}: {page['image']}",
                )

    def test_the_folios_run_in_order(self) -> None:
        for scan in self.document["scans"]:
            numbers = [page["n"] for page in scan["pages"]]
            self.assertEqual(numbers, sorted(numbers), scan["id"])

    def test_the_terms_are_recorded(self) -> None:
        # The images stay on the library's server under the library's terms, so
        # a scan whose terms have been lost is a scan nobody may use.
        for scan in self.document["scans"]:
            self.assertTrue(scan["licence"], f"{scan['id']} states no terms")
            self.assertTrue(scan["attribution"], f"{scan['id']} credits nobody")


if __name__ == "__main__":
    unittest.main()
