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

import contextlib
import io
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

#: Cut from the real answer for Gaster Hebrew MS 1616 — the same shape as
#: CUDL_RECORD but for a different host, which is the whole point of the class
#: this fixture serves: proof that one reader was always going to be enough.
MANCHESTER_RECORD = {
    "descriptiveMetadata": [
        {
            "title": {"displayForm": "New Testament in Hebrew translation"},
            "shelfLocator": {"displayForm": "Gaster Hebrew MS 1616"},
            "physicalLocation": {"displayForm": "The John Rylands Library"},
            "material": {"displayForm": "Paper"},
            "languages": ["Hebrew"],
            "creations": {
                "value": [{"dateDisplay": {"displayForm": "1810"}}]
            },
            "downloadImageRights": "… (CC BY-NC 3.0)",
        }
    ],
    "pages": [
        {"sequence": 1, "label": "Front_cover", "IIIFImageURL": "MS-GASTER-HEBREW-01616-000-00001"},
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

#: A codex big enough to slice, carrying every shape a range has to step over:
#: covers at each end that are not folios at all, labels with a space in them,
#: and folios a string sort would put in the wrong order — "10r" before "2r".
#: The numbers are Cambridge's own, which is why 1r is 3 and not 1.
CODEX = [
    {"n": number, "label": label, "image": f"https://img.example/{number}.jpg"}
    for number, label in enumerate(
        [
            "front cover",
            "inside front cover",
            "1r",
            "1v",
            "2r",
            "2v",
            "9r",
            "9v",
            "10r",
            "10v",
            "back cover",
        ],
        start=1,
    )
]

#: The shape OPenn gives, which is why a hyphen cannot separate a range and why
#: the end of one is searched forward from its start: i-r and i-v label an
#: endleaf at each end of the codex, so the labels repeat.
ENDLEAVES = [
    {"n": number, "label": label, "image": f"https://img.example/{number}.jpg"}
    for number, label in enumerate(
        ["front", "front-i", "i-r", "i-v", "1r", "1v", "i-r", "i-v", "back"],
        start=1,
    )
]

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


class ManchesterIsReadByTheSameReaderAsCambridge(unittest.TestCase):
    """Discovered rather than assumed: the two turned out to run one platform.

    Not a second copy of TheCambridgeRecordIsReadIntoAnEntry — that class is
    the proof the shared reader still behaves exactly as it did before it had
    a second caller. This one is the proof that a *different* host reaches it.
    """

    def setUp(self) -> None:
        self._real = build_scan_manifest.fetch_json
        build_scan_manifest.fetch_json = lambda url: MANCHESTER_RECORD
        self.entry = build_scan_manifest.manchester_scan("MS-GASTER-HEBREW-01616", 1024)

    def tearDown(self) -> None:
        build_scan_manifest.fetch_json = self._real

    def test_the_plain_fields_read_the_same_shape(self) -> None:
        self.assertEqual(self.entry["title"], "New Testament in Hebrew translation")
        self.assertEqual(self.entry["shelfmark"], "Gaster Hebrew MS 1616")
        self.assertEqual(self.entry["repository"], "The John Rylands Library")

    def test_the_image_host_is_manchesters_own(self) -> None:
        # The one place the two platforms actually differ: Manchester's image
        # host is singular, "image", not the "images" Cambridge answers to.
        self.assertEqual(
            self.entry["pages"][0]["image"],
            "https://image.digitalcollections.manchester.ac.uk/iiif/"
            "MS-GASTER-HEBREW-01616-000-00001.jp2/full/1024,/0/default.jpg",
        )

    def test_a_manchester_viewer_link_is_recognised(self) -> None:
        source, item = build_scan_manifest.parse_link(
            "https://www.digitalcollections.manchester.ac.uk/view/"
            "MS-GASTER-HEBREW-01616/1"
        )
        self.assertEqual(source, "manchester")
        self.assertEqual(item, "MS-GASTER-HEBREW-01616")


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

    def test_the_address_becomes_an_id_that_can_be_a_filename(self) -> None:
        # The library names nothing, so the address has to serve — but not as
        # it stands: "images/https://gallica.bnf.fr/…-0001.jpg" is refused by
        # Milah's archive writer, which pinned a transcriber to folio one.
        identifier = build_scan_manifest.iiif_id(
            "https://gallica.bnf.fr/iiif/ark:/12148/btv1b10720220s/manifest.json"
        )
        self.assertEqual(identifier, "gallica-bnf-fr-iiif-ark-12148-btv1b10720220s")

    def test_two_manuscripts_at_one_library_keep_their_own_ids(self) -> None:
        # The whole address is folded in rather than whichever part looks
        # distinctive: "looks distinctive" is a guess, and two manuscripts that
        # agreed on the guess would come back as one manuscript.
        first = build_scan_manifest.iiif_id("https://digi.vatlib.it/iiif/MSS_Vat.ebr.101/manifest.json")
        second = build_scan_manifest.iiif_id("https://digi.vatlib.it/iiif/MSS_Vat.ebr.102/manifest.json")
        self.assertNotEqual(first, second)

    def test_an_address_with_no_manifest_suffix_is_still_an_id(self) -> None:
        self.assertEqual(
            build_scan_manifest.iiif_id("https://example.org/iiif/codex-7"),
            "example-org-iiif-codex-7",
        )

    def test_a_manifest_named_for_its_manuscript_does_not_trail_the_word_json(self) -> None:
        # The Bodleian ends with the manuscript's own uuid and ".json" rather
        # than with "/manifest.json", so stripping only the latter left an id
        # ending "-json".
        identifier = build_scan_manifest.iiif_id(
            "https://iiif.bodleian.ox.ac.uk/iiif/manifest/44cd9a82-b931.json"
        )
        self.assertFalse(identifier.endswith("json"), identifier)
        self.assertTrue(identifier.endswith("44cd9a82-b931"), identifier)

    def test_terms_given_as_a_list_are_not_printed_as_one(self) -> None:
        # The Laurenziana sends ["", "Pubblico"]. Passed through str() that
        # reaches a reader as ['', 'Pubblico'] — brackets, quotes and a stray
        # comma — shown in a sidebar as though it were the library's wording.
        # The empty first entry is dropped rather than joined, because a line
        # opening "; " is not a statement of terms either.
        entry = self._scan(
            {
                **IIIF_V2,
                "attribution": ["", "Pubblico"],
                "license": ["https://example.org/terms", ""],
            }
        )
        self.assertEqual(entry["attribution"], "Pubblico")
        self.assertEqual(entry["licence"], "https://example.org/terms")

    def test_terms_given_as_a_language_map_are_read(self) -> None:
        entry = self._scan({**IIIF_V2, "attribution": {"en": ["Provided by Somewhere"]}})
        self.assertEqual(entry["attribution"], "Provided by Somewhere")

    def test_terms_that_are_absent_are_empty_rather_than_none(self) -> None:
        # str(None) is "None", which reads as a licence saying None.
        entry = self._scan({key: value for key, value in IIIF_V2.items()
                            if key != "attribution"})
        self.assertEqual(entry["attribution"], "")
        self.assertEqual(entry["licence"], "")

    def test_a_title_given_as_a_list_is_not_printed_as_one(self) -> None:
        entry = self._scan({**IIIF_V2, "label": ["Eben bochen", "Lapis discernens"]})
        self.assertEqual(entry["title"], "Eben bochen; Lapis discernens")


class ACodexCanBeOfferedAsItsBooks(unittest.TestCase):
    """One binding is twenty-six books, and a range says which of them a row is.

    Every test here is a way of getting a range slightly wrong, and a range
    slightly wrong is an entry that looks perfectly well formed and opens on the
    wrong folio in front of somebody transcribing.
    """

    def test_no_range_is_the_whole_codex(self) -> None:
        # What every row was before this column existed, and what most still are.
        pages, complaint = build_scan_manifest.folio_range(CODEX, "")
        self.assertEqual(complaint, "")
        self.assertEqual(pages, CODEX)

    def test_a_range_is_taken_by_label(self) -> None:
        pages, complaint = build_scan_manifest.folio_range(CODEX, "1r..2v")
        self.assertEqual(complaint, "")
        self.assertEqual([page["label"] for page in pages], ["1r", "1v", "2r", "2v"])

    def test_a_range_is_not_taken_by_sorting_the_labels(self) -> None:
        # "10r" sorts before "2r" in any string comparison. Folio labels are not
        # numbers and cannot be ordered as either.
        pages, _ = build_scan_manifest.folio_range(CODEX, "2r..10v")
        self.assertEqual(
            [page["label"] for page in pages], ["2r", "2v", "9r", "9v", "10r", "10v"]
        )

    def test_a_range_is_not_taken_by_counting_folios(self) -> None:
        # Folio 1r is the third image: the covers come first, and how many of
        # them there are differs from one codex to the next.
        pages, _ = build_scan_manifest.folio_range(CODEX, "1r..1r")
        self.assertEqual(pages[0]["n"], 3)

    def test_the_pages_keep_the_numbers_the_library_gave_them(self) -> None:
        # n is the number in Cambridge's own viewer address, which is what a
        # transcriber quotes when checking a reading. Renumbering from 1 would
        # give every book a page 1 that is a different picture.
        pages, _ = build_scan_manifest.folio_range(CODEX, "9r..10v")
        self.assertEqual([page["n"] for page in pages], [7, 8, 9, 10])

    def test_a_single_label_is_a_range_of_one_page(self) -> None:
        pages, complaint = build_scan_manifest.folio_range(CODEX, "9r")
        self.assertEqual(complaint, "")
        self.assertEqual([page["label"] for page in pages], ["9r"])

    def test_a_catalogue_dash_separates_too(self) -> None:
        # "ff. 1r–21v" is what gets pasted out of a catalogue record.
        for written in ("1r–2r", "1r—2r"):
            pages, complaint = build_scan_manifest.folio_range(CODEX, written)
            self.assertEqual(complaint, "", written)
            self.assertEqual([page["label"] for page in pages], ["1r", "1v", "2r"])

    def test_a_hyphen_does_not_separate_because_labels_contain_one(self) -> None:
        # OPenn labels endleaves i-r and front-i. Splitting on the hyphen would
        # read "i-r..i-v" as beginning at "i", which is no label at all.
        pages, complaint = build_scan_manifest.folio_range(ENDLEAVES, "i-r..i-v")
        self.assertEqual(complaint, "")
        self.assertEqual([page["label"] for page in pages], ["i-r", "i-v"])

    def test_a_repeated_label_is_found_forward_from_the_start(self) -> None:
        # i-r and i-v label an endleaf at each end of the codex. A range running
        # from the text to a back endleaf has to reach the second one.
        pages, complaint = build_scan_manifest.folio_range(ENDLEAVES, "1r..i-v")
        self.assertEqual(complaint, "")
        self.assertEqual(
            [page["label"] for page in pages], ["1r", "1v", "i-r", "i-v"]
        )

    def test_an_endpoint_that_is_not_a_label_is_refused_not_rounded(self) -> None:
        pages, complaint = build_scan_manifest.folio_range(CODEX, "1x..2v")
        self.assertEqual(pages, [])
        self.assertIn("1x", complaint)

    def test_the_refusal_says_what_the_labels_here_look_like(self) -> None:
        # The usual mistake is a guess at the form — "f. 22r", "22", "22R" — and
        # the words "not found" alone do not correct it.
        _, complaint = build_scan_manifest.folio_range(CODEX, "f. 1r..2v")
        self.assertIn("front cover", complaint)
        self.assertIn("1r", complaint)

    def test_a_range_that_ends_before_it_begins_is_refused(self) -> None:
        pages, complaint = build_scan_manifest.folio_range(CODEX, "10v..1r")
        self.assertEqual(pages, [])
        self.assertIn("ends before it begins", complaint)

    def test_half_a_range_is_refused(self) -> None:
        # Otherwise the missing end looks for a label of "", which reads as a
        # page carrying no label at all.
        for written in ("1r..", "..2v"):
            pages, complaint = build_scan_manifest.folio_range(CODEX, written)
            self.assertEqual(pages, [], written)
            self.assertIn("missing an end", complaint)

    def test_more_than_two_ends_is_refused(self) -> None:
        pages, complaint = build_scan_manifest.folio_range(CODEX, "1r..2r..9r")
        self.assertEqual(pages, [])
        self.assertIn("rather than two", complaint)

    def test_the_pages_are_copies_not_the_records_own(self) -> None:
        # Several rows slice one fetched record. A page dict shared between two
        # entries makes a correction to one of them silently a correction to the
        # other.
        pages, _ = build_scan_manifest.folio_range(CODEX, "1r..1v")
        pages[0]["label"] = "meddled with"
        self.assertEqual(CODEX[2]["label"], "1r")

    def test_a_label_a_codex_does_not_have_is_refused_even_when_it_is_a_prefix(
        self,
    ) -> None:
        # "1" is the beginning of "1r" and "10r" and nothing in itself.
        pages, complaint = build_scan_manifest.folio_range(CODEX, "1..2")
        self.assertEqual(pages, [])
        self.assertTrue(complaint)


class OneRecordServesEveryRowThatNamesIt(unittest.TestCase):
    """Twenty-six rows, one reading.

    Cambridge rate-limits and bot-filters unidentified clients, which is why this
    generator names its User-Agent at all. Twenty-six fetches of one record is a
    build that gets itself blocked halfway through.
    """

    ROW = "https://cudl.lib.cam.ac.uk/view/MS-OO-00001-00032/1"

    def setUp(self) -> None:
        self.readings: list[tuple[str, int]] = []
        self._real = build_scan_manifest.cudl_scan
        build_scan_manifest.cudl_scan = self._record

    def tearDown(self) -> None:
        build_scan_manifest.cudl_scan = self._real

    def _record(self, item: str, width: int) -> dict:
        self.readings.append((item, width))
        return {
            "id": item,
            "title": "Hebrew translation of the New Testament",
            "shelfmark": "MS Oo.1.32",
            "repository": "Cambridge University Library",
            "origin": "Kochi",
            "date": "Eighteenth century",
            "language": "Hebrew",
            "material": "Paper",
            "provenance": "Presented in 1809",
            "attribution": "Provided by Cambridge University Library",
            "licence": "… (CC BY-NC 3.0)",
            "pages": [dict(page) for page in CODEX],
        }

    def _build(self, rows: list[dict]) -> list[dict]:
        """build() with its progress lines caught, so a passing run stays quiet."""
        noise = io.StringIO()
        with contextlib.redirect_stdout(noise):
            entries = build_scan_manifest.build(rows)
        self.said = noise.getvalue()
        return entries

    def _rows(self, *folios: str) -> list[dict]:
        return [{"url": self.ROW, "title": f"Book {n}", "folios": f}
                for n, f in enumerate(folios, start=1)]

    def test_the_record_is_read_once_however_many_books_ask_for_it(self) -> None:
        self._build(self._rows("1r..1v", "2r..2v", "9r..10v"))
        self.assertEqual(len(self.readings), 1)

    def test_each_book_is_an_entry_of_its_own(self) -> None:
        entries = self._build(self._rows("1r..1v", "9r..10v"))
        self.assertEqual(len(entries), 2)
        self.assertEqual([page["label"] for page in entries[0]["pages"]], ["1r", "1v"])
        self.assertEqual(
            [page["label"] for page in entries[1]["pages"]], ["9r", "9v", "10r", "10v"]
        )

    def test_no_two_books_share_an_id(self) -> None:
        entries = self._build(self._rows("1r..1v", "2r..2v"))
        self.assertEqual(len({entry["id"] for entry in entries}), 2)
        self.assertEqual(entries[0]["id"], "MS-OO-00001-00032-1r-1v")

    def test_a_row_with_no_range_keeps_the_id_it_has_always_had(self) -> None:
        # The whole-codex entry is already published under this id; anything in
        # Milah holding it must go on resolving.
        entries = self._build([{"url": self.ROW}])
        self.assertEqual(entries[0]["id"], "MS-OO-00001-00032")
        self.assertEqual(entries[0]["folios"], "")

    def test_a_title_given_to_one_book_is_not_given_to_the_others(self) -> None:
        # The record behind them is shared, so writing into it rather than into a
        # copy would retitle every book at once.
        entries = self._build(
            [
                {"url": self.ROW, "title": "Matthew", "folios": "1r..1v"},
                {"url": self.ROW, "folios": "2r..2v"},
            ]
        )
        self.assertEqual(entries[0]["title"], "Matthew")
        self.assertEqual(entries[1]["title"], "Hebrew translation of the New Testament")

    def test_the_pages_of_one_book_are_not_the_pages_of_another(self) -> None:
        entries = self._build(self._rows("1r..1v", "2r..2v"))
        entries[0]["pages"][0]["label"] = "meddled with"
        self.assertEqual(entries[1]["pages"][0]["label"], "2r")

    def test_a_different_width_is_a_different_reading(self) -> None:
        # Width is part of every image address, so two widths are two records.
        self._build(
            [
                {"url": self.ROW, "folios": "1r..1v"},
                {"url": self.ROW, "folios": "1r..1v", "width": "2000"},
            ]
        )
        self.assertEqual(len(self.readings), 2)

    def test_the_folio_list_is_the_last_key_of_every_entry(self) -> None:
        # It is hundreds of lines long, and anything after it would be unreadable
        # in a file people do open to see what is offered.
        for entry in self._build(self._rows("1r..1v", "2r..2v")):
            self.assertEqual(list(entry)[-1], "pages")

    def test_a_row_whose_range_cannot_be_resolved_is_left_out_and_said(self) -> None:
        entries = self._build(self._rows("1r..1v", "22x..33v"))
        self.assertEqual(len(entries), 1)
        self.assertIn("skipped", self.said)
        self.assertIn("22x", self.said)

    def test_a_row_repeating_another_rows_range_is_left_out(self) -> None:
        entries = self._build(self._rows("1r..1v", "1r..1v"))
        self.assertEqual(len(entries), 1)
        self.assertIn("already", self.said)

    def test_the_same_range_written_two_ways_is_one_entry(self) -> None:
        # The id is built from the resolved labels, not from the cell as typed.
        entries = self._build(self._rows("1r..1v", "1r–1v"))
        self.assertEqual(len(entries), 1)


class AManuscriptWithNothingToFetchIsOfferedAnyway(unittest.TestCase):
    """A row may say ``unavailable`` instead of naming an address.

    Cambridge MS Oo.1.16 has no viewer to copy a link from. Nothing here is
    resolved, so these tests never touch ``fetch_json`` — the point is what
    ``build()`` does with a row that has no url at all.
    """

    def _build(self, rows: list[dict]) -> list[dict]:
        noise = io.StringIO()
        with contextlib.redirect_stdout(noise):
            entries = build_scan_manifest.build(rows)
        self.said = noise.getvalue()
        return entries

    def test_a_shelfmark_alone_is_enough_to_be_offered(self) -> None:
        entries = self._build(
            [{"status": "unavailable", "shelfmark": "MS Oo.1.16", "note": "Not on CUDL."}]
        )
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["shelfmark"], "MS Oo.1.16")
        # Falls back to the shelfmark: nothing else names the manuscript.
        self.assertEqual(entries[0]["title"], "MS Oo.1.16")

    def test_it_carries_no_pages_and_says_why(self) -> None:
        entry = self._build(
            [{"status": "unavailable", "title": "Even Bohan", "note": "Not digitised."}]
        )[0]
        self.assertEqual(entry["pages"], [])
        self.assertEqual(entry["unavailable"], "Not digitised.")

    def test_nothing_with_neither_a_title_nor_a_shelfmark_can_be_shown(self) -> None:
        entries = self._build([{"status": "unavailable", "note": "Not digitised."}])
        self.assertEqual(entries, [])
        self.assertIn("skipped", self.said)

    def test_a_url_is_kept_as_something_to_learn_more_from_not_fetched(self) -> None:
        real = build_scan_manifest.fetch_json
        build_scan_manifest.fetch_json = lambda url: (_ for _ in ()).throw(
            AssertionError("an unavailable row must never be fetched")
        )
        try:
            entry = self._build(
                [
                    {
                        "status": "unavailable",
                        "shelfmark": "Add MS 26964",
                        "url": "https://searcharchives.bl.uk/catalog/032-003313863",
                        "note": "Images currently unavailable.",
                    }
                ]
            )[0]
        finally:
            build_scan_manifest.fetch_json = real
        self.assertEqual(entry["source"], "https://searcharchives.bl.uk/catalog/032-003313863")

    def test_a_note_missing_is_a_warning_not_a_refusal(self) -> None:
        entries = self._build([{"status": "unavailable", "shelfmark": "MS Oo.1.16"}])
        self.assertEqual(len(entries), 1)
        self.assertIn("warning", self.said)
        self.assertIn("no note", self.said)

    def test_two_unavailable_rows_naming_the_same_manuscript_are_one_entry(self) -> None:
        entries = self._build(
            [
                {"status": "unavailable", "shelfmark": "MS Oo.1.16", "note": "First."},
                {"status": "unavailable", "shelfmark": "MS Oo.1.16", "note": "Second."},
            ]
        )
        self.assertEqual(len(entries), 1)

    def test_an_unavailable_id_cannot_collide_with_an_ordinary_scans(self) -> None:
        # A resolved scan and a hand-written stub must not be able to share an
        # id even if a shelfmark happened to match a real one's identifier.
        entry = self._build(
            [{"status": "unavailable", "shelfmark": "x", "note": "n"}]
        )[0]
        self.assertTrue(entry["id"].startswith("unavailable-"))

    def test_status_is_read_case_and_space_insensitively(self) -> None:
        for written in ("unavailable", "Unavailable", " UNAVAILABLE "):
            entries = self._build(
                [{"status": written, "shelfmark": "x", "note": "n"}]
            )
            self.assertEqual(len(entries), 1, written)


class TheLinkListIsReadAsWritten(unittest.TestCase):
    """It is edited by hand, so it has to tolerate being annotated."""

    LINKS = Path(__file__).resolve().parents[1] / "src" / "scan_links.tsv"

    def test_comments_and_blank_lines_are_ignored(self) -> None:
        rows = build_scan_manifest.read_links(self.LINKS)
        self.assertTrue(rows, f"no rows read from {self.LINKS}")
        for row in rows:
            # An unavailable row is the one kind that legitimately has no
            # address: there is nothing to fetch, only a manuscript to name.
            if (row.get("status") or "").strip().lower() == "unavailable":
                continue
            self.assertTrue(row.get("url", "").startswith("http"), row)

    def test_every_range_in_the_list_names_two_ends(self) -> None:
        # Whether the labels exist needs Cambridge; whether the cell is even the
        # right shape does not, and a hyphen or a stray dot is caught here.
        for row in build_scan_manifest.read_links(self.LINKS):
            folios = (row.get("folios") or "").strip()
            if not folios:
                continue
            ends = build_scan_manifest.FOLIO_SEPARATOR.split(folios)
            self.assertLessEqual(len(ends), 2, folios)
            self.assertTrue(all(part.strip() for part in ends), folios)

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
            # Empty pages is refused everywhere except the one place it is the
            # point: a manuscript recorded as unavailable, which says so.
            self.assertTrue(
                scan["pages"] or scan.get("unavailable"),
                f"{scan['id']} has no pages and does not say why",
            )

    def test_every_id_can_be_a_name_inside_an_archive(self) -> None:
        # An id is not only a key. Milah writes it into the name of every folio
        # inside a saved transcription, and a name carrying "https://" is
        # refused by the archive writer — the doubled slash does not survive
        # being cleaned. That refusal cost a transcriber the whole manuscript:
        # a folio is committed on the way off it, so a file that cannot be
        # written is a page that cannot be turned.
        for scan in self.document["scans"]:
            for forbidden in ("/", "\\", ":", " ", ".."):
                self.assertNotIn(
                    forbidden,
                    scan["id"],
                    f"{scan['id']} cannot be part of an archive entry name",
                )

    def test_no_two_scans_share_an_id(self) -> None:
        # Two entries under one id is a catalogue Milah cannot key: it shows one
        # of them twice and loses the other. Twenty-six of these entries are
        # slices of one codex and differ only by their folios, so this is the
        # invariant the whole id scheme exists to hold.
        ids = [scan["id"] for scan in self.document["scans"]]
        self.assertEqual(len(ids), len(set(ids)), sorted(ids))

    def test_every_book_a_scan_names_is_one_the_texts_would_recognise(self) -> None:
        # book is what groups the two catalogues together, so a scan filed under
        # JHN beside a text filed under JOH is two lists that never meet.
        for scan in self.document["scans"]:
            book = scan.get("book", "")
            if book:
                self.assertRegex(book, r"^[1-3]?[A-Z]{2,3}$", scan["id"])

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
        # a scan whose terms have been lost is a scan nobody may use. Not asked
        # of an unavailable entry: there is no image to state terms for.
        for scan in self.document["scans"]:
            if scan.get("unavailable"):
                continue
            self.assertTrue(scan["licence"], f"{scan['id']} states no terms")
            self.assertTrue(scan["attribution"], f"{scan['id']} credits nobody")

    def test_every_scan_says_whether_it_is_unavailable(self) -> None:
        # Always present, even when empty, the same discipline "folios" is
        # held to: a key a reader has to check for is a key that gets forgotten.
        for scan in self.document["scans"]:
            self.assertIn("unavailable", scan, scan["id"])

    def test_an_unavailable_scan_explains_itself_and_has_nothing_to_open(self) -> None:
        for scan in self.document["scans"]:
            if not scan.get("unavailable"):
                continue
            self.assertEqual(scan["pages"], [], scan["id"])
            self.assertTrue(scan["shelfmark"] or scan["title"], scan["id"])
            self.assertNotEqual(
                scan["unavailable"],
                "Not digitised; no scan has been published.",
                f"{scan['id']} carries only the generic fallback note",
            )


if __name__ == "__main__":
    unittest.main()
