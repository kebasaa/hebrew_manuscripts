"""Builds the manifest Milah reads to offer published scans for transcription.

Reads the links in ``src/scan_links.tsv`` and writes ``manifest_scans.json`` at
the root of this repository, so Milah can list what can be transcribed and open a
folio without anyone downloading a codex first::

    python src/build_scan_manifest.py

Unlike ``build_manifest.py`` this one needs the internet: what it writes is
resolved from the holding library's own record. Re-run it whenever a link is
added, and commit the result.

Linked, not copied
------------------

No image is downloaded here and none is kept in this repository. An entry names
where each folio lives on the library's own server, and carries the licence and
attribution the library states, because they travel with the images and a scan
whose terms have been lost is a scan nobody may use.

Why the page list is written out
--------------------------------

The image URLs could nearly always be generated from a pattern — Cambridge
numbers this manuscript's folios ``-000-00001`` to ``-000-00328``. They are
written out one by one anyway, because "nearly always" is the problem: the infix
is not the same for every item, and a pattern that is wrong for one manuscript is
wrong silently, in the app, in front of somebody transcribing. Writing the list
also keeps every library's quirks here rather than in Milah, which then only ever
sees a list of URLs.

Offering a codex as its books
-----------------------------

A row may name a folio range in ``folios``, and then it offers that range rather
than the whole codex. MS Oo.1.32 is one binding of 328 images holding twenty-six
New Testament books, and a single entry of 328 images is not something anybody
can choose Mark out of. Many rows may name one address: the record behind it is
read once for the whole run, and each row keeps the slice it asked for.

The endpoints are labels the library itself wrote — ``1r``, ``21v`` — and are
found by position in the page list. Not by arithmetic: Cambridge's first image is
the front cover, so folio 22r is image 45 in this codex and image something else
in the next. Not by sorting either, because ``10r`` sorts before ``2r`` in any
string comparison and folio labels are not numbers. A label that is not there
stops the row with a message rather than quietly producing a shorter entry: an
entry titled Mark that opens on Matthew is the silent kind of wrong this file
exists to avoid.

Adding a library
----------------

Write a resolver that returns one entry, and teach ``parse_link`` to recognise
its addresses. ``iiif_scan`` already handles anything that publishes a IIIF
manifest, which covers the Bodleian, the Vatican, e-codices and the National
Library of Israel; a library with its own richer record — as Cambridge has —
deserves its own function, because IIIF metadata is written for a viewer to
display rather than for a program to read.

Not always a new function, though: Manchester turned out to run the same
platform Cambridge does, discovered only by reading its record and finding the
same shape. ``Platform`` and ``platform_scan`` are what that led to — check
whether a new host is already one of these before writing a fourth reader.

Known but never photographed
-----------------------------

A row may set ``status`` to ``unavailable`` instead of naming an address. There
is nothing to fetch — Cambridge MS Oo.1.16 has no viewer to copy a link from,
and the British Library's own catalogue records Add MS 26964's images as
"currently unavailable" — so the row supplies by hand what a resolver would
otherwise have read: ``title``, ``shelfmark``, ``repository``, and a ``note``
saying why there is nothing here yet. The entry this produces carries no pages,
which the shape everywhere else in this file treats as an error to skip; here
it is the point, marked by a non-empty ``unavailable`` field so Milah can tell
the two apart and offer the manuscript anyway, disabled, rather than making it
invisible until somebody already knows to look for it.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import NamedTuple

#: Named rather than left to the default, because a default one gets blocked.
#: Cambridge bot-filters unidentified clients — its own help pages answer 403 —
#: and the National Library of Israel refuses them outright.
USER_AGENT = "milah-build"

#: How wide an image to ask for. Cambridge serves this manuscript from a 4331px
#: master but caps delivery at 2000px, silently: asking for more returns the
#: same bytes rather than an error. 1024 is legible for pointed Hebrew at the
#: size a folio is actually read on screen, and a folio is fetched every time it
#: is opened, so it is also a size worth waiting for.
DEFAULT_WIDTH = 1024

#: The viewer address, which is what a reader copies out of the browser. Shared
#: by every library on this platform: Manchester's viewer answers to the same
#: /view/{item} shape Cambridge's does, because it is the same platform.
CUDL_VIEW = re.compile(r"/view/([^/?#]+)")


class Platform(NamedTuple):
    """Where one digital-library platform keeps its record and its images.

    Cambridge and the John Rylands Library in Manchester turned out, on
    inspection, to run the identical software: the same JSON shape from
    ``descriptiveMetadata``/``pages`` down to the two-part rights split, the
    same viewer address, even the same field names. So one reader serves both
    rather than carrying two records that are nearly the same and drifting
    apart the first time one of them changes a field.

    They are not identical, though, and this record is where they are told
    apart. Believing the host was the only difference is what once asked
    Manchester for every page twice-extensioned; see ``jp2``.
    """

    #: Its record, which is not the IIIF manifest. The manifest carries the same
    #: facts with HTML and viewer-internal onclick handlers wrapped around them;
    #: this gives each field as a plain string, and the dates machine-readable
    #: besides.
    record: str
    #: Where the image server keeps its pages. The identifier goes on the end as
    #: the record gives it — not with an extension added here, because the two
    #: platforms do not agree on whether the record already carries one.
    image: str


CAMBRIDGE = Platform(
    record="https://services.cudl.lib.cam.ac.uk/v1/metadata/json/{item}",
    image="https://images.lib.cam.ac.uk/iiif/{image}",
)
#: The image host is singular — "image", not "images" — and its page
#: identifiers arrive with ".jp2" already on them, which Cambridge's do not.
MANCHESTER = Platform(
    record="https://services.digitalcollections.manchester.ac.uk/v1/metadata/json/{item}",
    image="https://image.digitalcollections.manchester.ac.uk/iiif/{image}",
)

#: OPenn publishes no API at all: a manuscript is a directory of static files on
#: an Apache server, and the TEI beside them is the only thing that says which of
#: them is a page and in what order. The image filenames carry an internal
#: document number rather than the manuscript's name, so they cannot be worked
#: out from the address either — they have to be read.
OPENN_HOST = "openn.library.upenn.edu"
OPENN_DATA = "https://openn.library.upenn.edu/Data/{collection}/{slug}/data/"
#: Every form a reader might copy. Two patterns rather than one clever one: the
#: browse pages live under html/ and the manuscripts beside it, so a single
#: expression with an optional html/ would read the collection listing
#: /Data/0047/html/ as a manuscript named "html". `Data` is capital-D and
#: case-sensitive — /data/0047/… is a 404.
OPENN_BROWSE = re.compile(r"/Data/(\d{4})/html/([^/]+)\.html$")
#: The item directory, with or without its slash, and anything under it — the
#: TEI, or a single image somebody had open.
OPENN_ITEM = re.compile(r"/Data/(\d{4})/(?!html/)([^/]+)(?:/.*)?$")
TEI_NS = {"t": "http://www.tei-c.org/ns/1.0"}

#: Alvin, the Swedish platform Uppsala publishes on, has no IIIF at all — no
#: manifest, no image API, nothing under any of the addresses the others use.
#: What it has is a record page and a run of numbered attachments, and the
#: pages have to be counted off those.
ALVIN_HOST = "alvin-portal.org"
ALVIN_RECORD = "https://www.alvin-portal.org/alvin/view.jsf?pid=alvin-record:{item}"
ALVIN_IMAGE = (
    "https://www.alvin-portal.org/alvin/attachment/record/"
    "alvin-record:{item}/ATTACHMENT-{n:04d}"
)
#: The record id, from any of the addresses its viewer and its record page use.
ALVIN_PID = re.compile(r"alvin-record[:%]3?A?(\d+)", re.IGNORECASE)
#: Where the images stop. Every attachment is ATTACHMENT-0001 upwards with no
#: extension and no label, except the last, which is the whole manuscript as a
#: PDF and is the only one written with one. So the PDF's number is not a page
#: — it is where the pages end, and the count is one short of it. Checked
#: against both manuscripts offered here: O Hebr. 41 ends at 62 with the PDF
#: at 63, O Hebr. 32 at 426 with the PDF at 427, and one past each is a 404.
ALVIN_PDF = re.compile(r"ATTACHMENT-(\d{4})\.pdf")

_TAGS = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")

#: What separates the two ends of a folio range. Not the hyphen, however
#: naturally "22r-33v" reads: OPenn labels Sloane MS 237's endleaves "i-r" and
#: "front-i", so a hyphen is a character inside a label here, and splitting on it
#: would read "i-r..i-v" as beginning at "i". The dashes a catalogue prints are
#: taken as well, because "ff. 1r–21v" is what gets copied out of one.
FOLIO_SEPARATOR = re.compile(r"\.\.|–|—")

#: Anything that cannot go in an identifier unquoted. Cambridge labels its covers
#: "front cover" and "inside front cover", and an id with a space in it is an id
#: that has to be quoted everywhere it is used.
_NOT_ID = re.compile(r"[^A-Za-z0-9]+")


def fetch(url: str) -> bytes:
    """The body at a URL, or an empty result the caller has to notice."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def fetch_json(url: str) -> dict:
    """The JSON at a URL, or an empty dict when it cannot be had.

    A library being down, or having moved an address, is a reason to skip one
    manuscript with a word about it — not to lose the whole manifest and every
    other scan in it.
    """
    try:
        payload = json.loads(fetch(url))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as failure:
        print(f"  could not read {url}: {failure}")
        return {}
    return payload if isinstance(payload, dict) else {}


def fetch_text(url: str) -> str:
    """The page at a URL as text, or "" when it cannot be had.

    Same forgiving contract as fetch_json: a library being down is one
    manuscript to skip with a word about it, not a manifest to lose. For the
    one platform here that publishes no API and has to be read as a page.
    """
    try:
        return fetch(url).decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as failure:
        print(f"  could not read {url}: {failure}")
        return ""


def fetch_xml(url: str) -> ET.Element | None:
    """The XML at a URL, or None when it cannot be had or cannot be parsed.

    Same forgiving contract as fetch_json, and for the same reason: a library
    being down is a manuscript to skip with a word about it, not a manifest to
    lose.
    """
    try:
        return ET.fromstring(fetch(url))
    except (urllib.error.URLError, TimeoutError, ET.ParseError, OSError) as failure:
        print(f"  could not read {url}: {failure}")
        return None


def tei_text(parent: ET.Element | None, path: str) -> str:
    """The plain text at a TEI path, empty when it is not there.

    Every field is optional and meant to be: Sloane MS 237 has no origin place
    at all, and its origin date is an empty element carrying only attributes.
    """
    if parent is None:
        return ""
    found = parent.find(path, TEI_NS)
    if found is None:
        return ""
    return strip_html("".join(found.itertext()))


def strip_html(value: str) -> str:
    """A metadata value as plain text.

    Library records are written for a viewer to display, so a value arrives as
    markup: Cambridge wraps several of them in ``<p>`` and one in a ``<div>`` of
    list styling around an ``<a onclick='store.loadPage(265)'>`` that means
    nothing outside its own website. Milah shows these in a sidebar, where a tag
    is not a tag but four stray characters.
    """
    return _SPACE.sub(" ", _TAGS.sub(" ", value or "")).strip()


def display_form(field: object) -> str:
    """The readable string out of one of Cambridge's metadata objects.

    Every descriptive field is ``{"displayForm": …, "label": …, "seq": …}``
    rather than a bare string, and a missing field is missing rather than empty,
    so this answers "" for both and the caller need not tell them apart.
    """
    if isinstance(field, dict):
        return strip_html(str(field.get("displayForm", "")))
    return ""


def first_value(field: object) -> dict:
    """The first entry of a field that carries a ``value`` list.

    Provenance, origin and creation are all lists of one in practice, but they
    are lists: a manuscript may have been made in two places, and the record has
    room to say so even where it does not.
    """
    if isinstance(field, dict):
        values = field.get("value")
        if isinstance(values, list) and values and isinstance(values[0], dict):
            return values[0]
    return {}


def jp2(identifier: str) -> str:
    """A page identifier as its image server keeps it, exactly one .jp2 deep.

    The two platforms disagree here and neither record says so. Cambridge names
    a page "MS-OO-00001-00032-000-00001"; Manchester names the same kind of page
    "MS-GASTER-HEBREW-01616-000-00001.jp2". Appending the extension either way
    asks Manchester for "…jp2.jp2", which is a 404 — on every folio of every
    book of the only manuscript it holds, silently, because a manifest full of
    addresses that fetch nothing looks exactly like one that works.
    """
    return identifier if identifier.endswith(".jp2") else f"{identifier}.jp2"


def image_url(service: str, width: int) -> str:
    """The IIIF Image API address of a whole page at a given width.

    ``jpg`` because that is all Cambridge's image server offers at level 1 —
    asking for png or tif is an error, not a conversion.
    """
    return f"{service.rstrip('/')}/full/{width},/0/default.jpg"


def parse_link(url: str) -> tuple[str, str]:
    """Which library a link belongs to, and what it identifies there.

    Returns an empty source for an address nothing here knows how to read,
    which is a thing to report rather than to guess at: guessing produces a
    manifest entry that looks right and fetches nothing.
    """
    parsed = urllib.parse.urlparse(url.strip())
    host = parsed.netloc.lower()

    if host.endswith("cudl.lib.cam.ac.uk"):
        found = CUDL_VIEW.search(parsed.path)
        if found:
            return "cudl", found.group(1)
        return "", ""

    if host.endswith("digitalcollections.manchester.ac.uk"):
        # The same /view/{item} shape Cambridge's viewer uses, because it is
        # the same platform.
        found = CUDL_VIEW.search(parsed.path)
        if found:
            return "manchester", found.group(1)
        return "", ""

    # Before the IIIF fallback below, which would otherwise never be reached for
    # OPenn but would be the wrong reader if its paths ever gained the word.
    if host.endswith(OPENN_HOST):
        found = OPENN_BROWSE.search(parsed.path) or OPENN_ITEM.search(parsed.path)
        if found:
            return "openn", f"{found.group(1)}/{found.group(2)}"
        return "", ""

    # Before the IIIF fallback, which Alvin would never reach anyway — it
    # publishes none — but which its viewer address would otherwise fall past
    # into the "nothing here can read this" case with no explanation.
    if host.endswith(ALVIN_HOST):
        found = ALVIN_PID.search(url)
        if found:
            return "alvin", found.group(1)
        return "", ""

    # Anything else that is plainly a IIIF manifest can still be read, just
    # without the richer record a library's own API would give. The bare
    # "/manifest" ending is the National Library of Israel's usual shape:
    # /IIIFv21/DOCID/{id}/manifest, with neither the lowercase word nor the
    # file extension the other two tests look for. A composite volume there
    # can carry a further /{intellectual entity id} after "manifest" too,
    # scoping the same address down to one bibliographic item inside a
    # shared binding — Guenzburg 363's "manifest/IE70811450" is host to
    # twenty unrelated Hebrew texts, of which this is the address of one.
    # Matched case-insensitively because NLI's own path segment is
    # "/IIIFv21/", capitalised, which the plain lowercase substring below
    # would otherwise miss.
    path = parsed.path
    path_lower = path.lower()
    if (
        "/iiif/" in path_lower
        or path_lower.endswith("manifest.json")
        or path_lower.endswith("/manifest")
        or "/manifest/" in path_lower
    ):
        return "iiif", url.strip()

    return "", ""


def platform_scan(item: str, width: int, platform: Platform) -> dict | None:
    """One entry from a record published by the shared platform.

    Cambridge and Manchester alike: see ``Platform`` for why this is one
    function rather than two nearly-identical ones.
    """
    record = fetch_json(platform.record.format(item=item))
    if not record:
        return None

    described = record.get("descriptiveMetadata") or [{}]
    metadata = described[0] if isinstance(described[0], dict) else {}
    creation = first_value(metadata.get("creations"))

    pages = []
    for page in record.get("pages") or []:
        identifier = page.get("IIIFImageURL")
        if not identifier:
            # A page the library has not released has no image to point at.
            continue
        pages.append(
            {
                "n": int(page.get("sequence") or len(pages) + 1),
                "label": strip_html(str(page.get("label", ""))),
                "image": image_url(platform.image.format(image=jp2(identifier)), width),
            }
        )

    languages = metadata.get("languages")
    language = ", ".join(str(name) for name in languages) if isinstance(languages, list) else ""
    repository = display_form(metadata.get("physicalLocation"))

    return {
        "id": item,
        "title": display_form(metadata.get("title")),
        "shelfmark": display_form(metadata.get("shelfLocator")),
        "repository": repository,
        "origin": display_form(first_value(creation.get("places"))),
        "date": display_form(creation.get("dateDisplay")),
        "language": strip_html(language),
        "material": display_form(metadata.get("material")),
        "provenance": display_form(first_value(metadata.get("provenances"))),
        # A credit line, not a rights statement. This platform splits rights in
        # two: displayImageRights covers its own zooming viewer and reads "All
        # rights reserved", while downloadImageRights covers fetching an image
        # through the Image API — which is what Milah does, and which is
        # CC BY-NC. The display terms are deliberately not recorded: they
        # govern a viewer nobody here uses, and printing "All rights reserved"
        # beside a folio fetched under a Creative Commons licence would
        # misstate both.
        "attribution": f"Provided by {repository}" if repository else "",
        "licence": strip_html(str(metadata.get("downloadImageRights", ""))),
        "pages": pages,
    }


def cudl_scan(item: str, width: int) -> dict | None:
    """Cambridge's own record of a manuscript."""
    return platform_scan(item, width, CAMBRIDGE)


def manchester_scan(item: str, width: int) -> dict | None:
    """The John Rylands Library's own record of a manuscript."""
    return platform_scan(item, width, MANCHESTER)


def openn_scan(identifier: str, width: int) -> dict | None:
    """One entry from OPenn's TEI description of a manuscript.

    `identifier` is "collection/slug", as parse_link gives it.
    """
    collection, _, slug = identifier.partition("/")
    data = OPENN_DATA.format(collection=collection, slug=slug)
    root = fetch_xml(f"{data}{slug}_TEI.xml")
    if root is None:
        return None

    if width != DEFAULT_WIDTH:
        # Said rather than ignored: OPenn serves fixed derivatives, so a row
        # asking for a size would otherwise look as though it had been honoured.
        print(f"  {slug}: OPenn chooses its own image sizes, so width is not used")

    description = root.find(".//t:sourceDesc/t:msDesc", TEI_NS)
    identity = description.find("t:msIdentifier", TEI_NS) if description is not None else None

    # Not titleStmt/title, which reads "Description of British Library, Sloane
    # MS 237: …" — a title for the catalogue record rather than for the
    # manuscript. The same trap build_manifest.py documents for OSIS headers.
    title = tei_text(description, "t:msContents/t:msItem/t:title")
    if not title:
        title = tei_text(root, ".//t:titleStmt/t:title")

    # The human form first: the machine-readable one is an empty element
    # carrying only notBefore and notAfter, which reads as a range and not as
    # what a cataloguer wrote.
    date = tei_text(description, "t:history/t:origin/t:p")
    if not date:
        origin = description.find("t:history/t:origin/t:origDate", TEI_NS) \
            if description is not None else None
        if origin is not None:
            span = [origin.get("notBefore", ""), origin.get("notAfter", "")]
            date = "–".join(part for part in span if part)

    pages = []
    for surface in root.findall(".//t:facsimile/t:surface", TEI_NS):
        image = ""
        for graphic in surface.findall("t:graphic", TEI_NS):
            url = graphic.get("url", "")
            # By prefix, never by position. The order here happens to be master,
            # thumb, web, but that is a convention rather than a promise — and
            # the master may be a TIFF of ninety megabytes, which Milah cannot
            # decode and OPenn's own robots.txt refuses to serve to a program.
            if url.startswith("web/"):
                image = data + url
                break
        if not image:
            continue
        pages.append(
            {
                # Numbered by position, because the label is not a key: the
                # endleaves repeat i-r, i-v, ii-r and ii-v at both ends of the
                # codex, and x-v is missing between x-r and xi-r.
                "n": len(pages) + 1,
                "label": surface.get("n", ""),
                "image": image,
            }
        )

    repository = tei_text(identity, "t:repository")
    licences = root.findall(".//t:publicationStmt/t:availability/t:licence", TEI_NS)

    return {
        "id": f"openn-{collection}-{slug}",
        "title": title,
        "shelfmark": tei_text(identity, 't:idno[@type="call-number"]'),
        "repository": repository,
        # Absent from this manuscript entirely, and from many: a cataloguer who
        # does not know where a codex was written does not say.
        "origin": tei_text(description, "t:history/t:origin/t:origPlace"),
        "date": date,
        "language": tei_text(description, "t:msContents/t:textLang"),
        "material": tei_text(description, "t:physDesc/t:objectDesc/t:supportDesc/t:support/t:p"),
        "provenance": tei_text(description, "t:history/t:provenance"),
        # OPenn asks that both the holding institution and OPenn itself be
        # cited. The library owns the manuscript; Penn only distributes it.
        "attribution": (
            f"Provided by {repository}, distributed by OPenn "
            "(University of Pennsylvania Libraries)"
            if repository
            else "Distributed by OPenn (University of Pennsylvania Libraries)"
        ),
        # The first of two: it covers the images, which is what a transcriber
        # fetches. The second covers the metadata and is not what governs this.
        "licence": strip_html("".join(licences[0].itertext())) if licences else "",
        "pages": pages,
    }


def alvin_scan(item: str, width: int) -> dict | None:
    """One entry from Alvin, the platform Uppsala publishes on.

    Alvin serves no IIIF and no API: there is a record page, and beside it a
    run of numbered attachments, and nothing that says how many. The count is
    read off the one attachment that names its format — the whole manuscript
    as a PDF, always last — because the record page itself lists only the
    dozen or so thumbnails it has loaded, and believing that count would offer
    fifteen pages of a two-hundred-folio manuscript.

    Nothing here is a folio label, so the pages are numbered and named for
    their position. Alvin knows nothing of r and v.
    """
    page = fetch_text(ALVIN_RECORD.format(item=item))
    if not page:
        return None

    end = ALVIN_PDF.search(page)
    if not end:
        # Without it there is no way to know where the images stop, and
        # guessing produces an entry that is short by an unknown amount.
        print(f"  {item}: no PDF attachment, so no way to count the pages")
        return None
    last = int(end.group(1)) - 1

    if width != DEFAULT_WIDTH:
        # Said rather than ignored, as for OPenn: Alvin serves one size.
        print(f"  {item}: Alvin serves a single image size, so width is not used")

    pages = [
        {
            "n": n,
            "label": f"image {n}",
            "image": ALVIN_IMAGE.format(item=item, n=n),
        }
        for n in range(1, last + 1)
    ]

    return {
        "id": f"alvin-{item}",
        # Alvin renders its record with JavaScript, so the fields a IIIF
        # manifest would carry are not in the page this fetched. They are
        # given in scan_links.tsv instead, which is what its override columns
        # are for.
        "title": "",
        "shelfmark": "",
        "repository": "",
        "origin": "",
        "date": "",
        "language": "",
        "material": "",
        "provenance": "",
        "attribution": "",
        "licence": "",
        "pages": pages,
    }


def iiif_scan(manifest_url: str, width: int) -> dict | None:
    """One entry from a IIIF manifest, for a library with no richer record.

    Handles Presentation API v2 and v3. Everything published today by the
    Bodleian, the Vatican, e-codices and Cambridge is v2, but v3 is where the
    specification has gone, so the shape is asked rather than assumed.
    """
    manifest = fetch_json(manifest_url)
    if not manifest:
        return None

    context = str(manifest.get("@context", ""))
    pages: list[dict] = []

    if "/presentation/3/" in context or manifest.get("type") == "Manifest":
        for index, canvas in enumerate(manifest.get("items") or [], start=1):
            service = _v3_service(canvas)
            if service:
                pages.append(
                    {
                        "n": index,
                        "label": _v3_label(canvas.get("label")),
                        "image": image_url(service, width),
                    }
                )
    else:
        sequences = manifest.get("sequences") or [{}]
        canvases = sequences[0].get("canvases") if isinstance(sequences[0], dict) else []
        for index, canvas in enumerate(canvases or [], start=1):
            service = _v2_service(canvas)
            if service:
                pages.append(
                    {
                        "n": index,
                        "label": strip_html(str(canvas.get("label", ""))),
                        "image": image_url(service, width),
                    }
                )

    return {
        "id": iiif_id(manifest_url),
        # Through the same reader as the terms: a title arrives in every shape
        # they do, and a codex called "['', 'Pubblico']" would be no better.
        "title": iiif_text(manifest.get("label")),
        "shelfmark": "",
        "repository": "",
        "origin": "",
        "date": "",
        "language": "",
        "material": "",
        "provenance": "",
        "attribution": iiif_text(manifest.get("attribution")),
        "licence": iiif_text(manifest.get("license") or manifest.get("rights")),
        "pages": pages,
    }


def _v2_service(canvas: dict) -> str:
    """The image service of a v2 canvas.

    Through ``service`` rather than through the resource's own ``@id``: the two
    are the same string at Cambridge, and that string is a JP2 nobody can fetch.
    Only the service takes the Image API syntax that turns it into a picture.
    """
    images = canvas.get("images") or []
    if not images or not isinstance(images[0], dict):
        return ""
    resource = images[0].get("resource") or {}
    service = resource.get("service") or {}
    if isinstance(service, list):
        service = service[0] if service and isinstance(service[0], dict) else {}
    return str(service.get("@id", "")) if isinstance(service, dict) else ""


def _v3_service(canvas: dict) -> str:
    """The image service of a v3 canvas, where service is always a list."""
    for annotation_page in canvas.get("items") or []:
        for annotation in annotation_page.get("items") or []:
            body = annotation.get("body") or {}
            services = body.get("service") or []
            if isinstance(services, dict):
                services = [services]
            for service in services:
                if isinstance(service, dict):
                    identifier = service.get("id") or service.get("@id")
                    if identifier:
                        return str(identifier)
    return ""


def iiif_text(value: object) -> str:
    """A IIIF metadata value as one readable line, whatever shape it arrives in.

    The specification lets attribution and rights be a string, a language map,
    or an array of either, and libraries use all of them: the Laurenziana sends
    ``["", "Pubblico"]``, which ``str()`` renders as ``['', 'Pubblico']`` —
    brackets, quotes and a stray comma, shown to a reader in a sidebar as though
    that were the library's own wording.

    Empty parts are dropped rather than joined, because that array's first entry
    is one and a line beginning "; " is not a statement of terms.
    """
    if isinstance(value, list):
        parts = [iiif_text(item) for item in value]
        return "; ".join(part for part in parts if part)
    if isinstance(value, dict):
        return _v3_label(value)
    if value is None:
        return ""
    return strip_html(str(value))


def _v3_label(label: object) -> str:
    """A label from either version.

    v2 gives a string; v3 gives ``{"en": ["…"]}``; some v2 servers give
    ``{"@value": "…"}``. All three arrive here.
    """
    if isinstance(label, str):
        return strip_html(label)
    if isinstance(label, dict):
        if "@value" in label:
            return strip_html(str(label["@value"]))
        for values in label.values():
            if isinstance(values, list) and values:
                return strip_html(str(values[0]))
            if isinstance(values, str):
                return strip_html(values)
    return ""


#: What `translationCertainty` may say. Anything else is a typo in the link
#: list, and is dropped with a warning rather than published — Milah has the
#: same four words and would show an unknown one as no answer at all, which is
#: a quieter way to lose a fact than saying so here.
CERTAINTIES = ("certain", "uncertain", "original", "original-uncertain")


def judgements(row: dict) -> dict:
    """What a row says about the text, as against about the object.

    No library record carries these: whether a Hebrew text renders a Greek one,
    and whether it copies an older book, are arguments rather than catalogue
    entries. They are written by hand in the link list and travel with the scan
    so that a transcription started from it begins already knowing them.

    ``translationCertainty`` is kept apart from the sentence beside it because
    two things are being said at once — what it renders, and whether that is
    settled — and for several of these manuscripts the second is the whole
    dispute. Empty means nobody has recorded an answer, which is not the same
    as "not a translation": that is ``original``.
    """
    certainty = (row.get("translationCertainty") or "").strip().lower()
    if certainty and certainty not in CERTAINTIES:
        print(
            f"  warning: {row.get('url', '').strip() or 'a row'} says "
            f"translationCertainty={certainty!r}, which is not one of "
            f"{', '.join(CERTAINTIES)} — dropped"
        )
        certainty = ""
    return {
        "translatedFrom": (row.get("translatedFrom") or "").strip(),
        "translationCertainty": certainty,
        "exemplar": (row.get("exemplar") or "").strip(),
    }


def read_links(path: Path) -> list[dict]:
    """The link list, as rows keyed by column name.

    Blank lines and ``#`` comments are dropped before the reader sees them, so
    the file can carry a note about why a manuscript is there.
    """
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return [dict(row) for row in csv.DictReader(lines, delimiter="\t")]


def page_id(label: str) -> str:
    """A folio label as a piece of an identifier.

    Cambridge labels its covers "front cover" and "inside front cover", and an id
    with a space in it is an id that has to be quoted everywhere it is used — in
    an address, in a filename, in a log line.
    """
    return _NOT_ID.sub("-", label).strip("-").lower()


def iiif_id(manifest_url: str) -> str:
    """An identifier for a manuscript a library gives no identifier for.

    Cambridge and OPenn name their manuscripts and those names become the ids;
    a bare IIIF manifest names nothing, so the address has to serve. It cannot
    serve as it stands: an id is not only a key. Milah writes it into the name
    of every folio inside a saved transcription, and an address makes a name
    with "https://" in it, which the archive refuses — the double slash does
    not survive being cleaned, so the file cannot be written, and because a
    folio is committed on the way off it, the page cannot be turned either.
    A transcriber is left on folio one with a message about unsafe paths.

    The whole address is folded in rather than whichever part looks
    distinctive, because "looks distinctive" is a guess and two manuscripts
    that agreed on the guess would come back as one manuscript. Nothing is
    lost by the length: this is read by a program, and by anyone who opens a
    transcription to see which leaf an entry is.
    """
    address = manifest_url.split("://", 1)[-1]
    # Both endings, in this order, because libraries split between them:
    # Gallica and the Vatican end "/manifest.json", while the Bodleian names the
    # file for the manuscript's own uuid and ends "<uuid>.json". Stripping only
    # the first left the Bodleian's id trailing the word "json"; stripping only
    # the second left the others trailing "manifest". Neither word says which
    # manuscript this is, and no two manifests differ only by them.
    for ending in (".json", "/manifest"):
        if address.endswith(ending):
            address = address[: -len(ending)]
    return page_id(address)


def label_sample(labels: list[str]) -> str:
    """A few of a codex's labels, to say what shape they are.

    The usual mistake is not a typo but a guess at the form — "f. 22r", "22",
    "22R" for a codex that says "22r" — and four real labels correct that where
    the words "not found" do not.
    """
    if len(labels) <= 5:
        return ", ".join(f'"{label}"' for label in labels)
    shown = ", ".join(f'"{label}"' for label in labels[:4])
    return f'{shown} … "{labels[-1]}"'


def folio_range(pages: list[dict], folios: str) -> tuple[list[dict], str]:
    """The pages a ``folios`` cell names, and what is wrong with it if anything.

    An empty cell is the whole codex, returned unchanged: that is what every row
    was before this existed, and what most rows still are.

    Both endpoints are matched against the labels the library itself gave, and
    the slice is taken by position. Folio labels cannot be sorted — "10r" comes
    before "2r" in any string comparison — and their numbers cannot be done
    arithmetic on either, because the sequence number counts images while the
    label counts folios: MS Oo.1.32 opens with a cover and an inside cover, so
    folio 1r is image 3 there and image something else in the next manuscript.

    A cell that cannot be resolved comes back with no pages and a reason to
    print. It deliberately does not fall back to the whole codex, nor to the
    nearest label: an entry of 328 images titled "Mark", or one that begins a
    folio early, is wrong in a way nobody notices until somebody is transcribing
    from it — which is the whole reason the page list is written out at all.
    """
    if not folios:
        return pages, ""

    ends = [part.strip() for part in FOLIO_SEPARATOR.split(folios)]
    if len(ends) > 2:
        return [], f'folios "{folios}" names {len(ends)} ends rather than two'
    if not all(ends):
        # "1r.." and "..21v" — half a range, which would otherwise look for a
        # label of "" and read as a page carrying no label at all.
        return [], f'folios "{folios}" is missing an end'
    start, end = ends[0], ends[-1]

    labels = [str(page.get("label", "")) for page in pages]
    if start not in labels:
        return [], f'no page is labelled "{start}" — here they read {label_sample(labels)}'

    first = labels.index(start)
    # The end is searched forward from the start rather than from the beginning
    # of the codex, because a label is not a key: OPenn repeats "i-r", "i-v",
    # "ii-r" and "ii-v" at both ends of Sloane MS 237, and a range running from
    # the text to a back endleaf has to find the second one.
    if end not in labels[first:]:
        if end in labels:
            return [], f'folios "{folios}" ends before it begins'
        return [], f'no page is labelled "{end}" — here they read {label_sample(labels)}'
    last = labels.index(end, first)

    # Copied, not aliased. Several rows slice one fetched record, and a page dict
    # shared between two entries makes a correction to one of them silently a
    # correction to the other.
    return [dict(page) for page in pages[first : last + 1]], ""


def unavailable_entry(row: dict, given: set[str]) -> dict | None:
    """A stub entry for a manuscript known to exist with nothing to fetch.

    Everything a resolver would otherwise have read is supplied by hand:
    Cambridge MS Oo.1.16 has no viewer address to copy, and the British
    Library's own catalogue calls Add MS 26964's images "currently
    unavailable" — there being nothing to ask for is the point, not something
    a URL column can name.

    None when the row cannot even be shown — no title and no shelfmark is a
    manuscript nobody could choose from a list — or when its id collides with
    one already given out. Both are printed by the caller, not here, so every
    refusal in a run reads in the same voice.
    """
    title = (row.get("title") or "").strip()
    shelfmark = (row.get("shelfmark") or "").strip()
    identity = shelfmark or title
    if not identity:
        return None

    entry_id = f"unavailable-{page_id(identity)}"
    if entry_id in given:
        return None
    given.add(entry_id)

    note = (row.get("note") or "").strip()
    return {
        "id": entry_id,
        "title": title or shelfmark,
        "shelfmark": shelfmark,
        "repository": (row.get("repository") or "").strip(),
        "origin": "",
        "date": "",
        "language": "",
        "material": "",
        "provenance": "",
        "attribution": "",
        "licence": "",
        "book": (row.get("book") or "").strip(),
        # The one thing a stub row may still usefully link to: not a viewer,
        # since there isn't one, but wherever a reader could confirm this for
        # themselves — a plain catalogue record, most often.
        "source": (row.get("url") or "").strip(),
        "folios": "",
        # Carried even here. What a text renders and what it copies are known
        # or argued about quite independently of whether anybody has
        # photographed it, and a reader looking a manuscript up is often
        # looking for exactly that.
        **judgements(row),
        # Non-empty is what tells Milah this absence is deliberate rather than
        # a resolver that came back with nothing to show — see fromJson().
        "unavailable": note or "Not digitised; no scan has been published.",
        "pages": [],
    }


def build(rows: list[dict]) -> list[dict]:
    entries = []
    # One reading per record per width, however many rows slice it. Twenty-six
    # rows name MS Oo.1.32 — one per New Testament book — and twenty-six fetches
    # of one record is how a build gets itself blocked halfway through: Cambridge
    # rate-limits and bot-filters unidentified clients, which is why USER_AGENT
    # exists at all. Width is part of the key because it is part of every image
    # address, so two widths are genuinely two records.
    fetched: dict[tuple[str, str, int], dict | None] = {}
    # Ids already handed out. Two entries under one id is a catalogue Milah
    # cannot key: it shows one of them twice and loses the other. Shared with
    # unavailable_entry(), because an ordinary scan and a stub must not collide
    # either.
    given: set[str] = set()

    for row in rows:
        status = (row.get("status") or "").strip().lower()
        if status == "unavailable":
            entry = unavailable_entry(row, given)
            if entry is None:
                print(f"  skipped (needs a title or a shelfmark, or repeats an id): {row}")
                continue
            if not (row.get("note") or "").strip():
                # Not fatal — the manifest still offers the manuscript, disabled
                # — but "not digitised" alone tells a transcriber nothing a
                # library-specific reason would.
                print(f"  warning: {entry['id']} is marked unavailable with no note explaining why")
            entries.append(entry)
            continue

        url = (row.get("url") or "").strip()
        if not url:
            continue

        source, identifier = parse_link(url)
        if not source:
            print(f"  skipped (no reader for this address): {url}")
            continue

        try:
            width = int((row.get("width") or "").strip() or DEFAULT_WIDTH)
        except ValueError:
            print(f"  {url}: width is not a number, using {DEFAULT_WIDTH}")
            width = DEFAULT_WIDTH

        folios = (row.get("folios") or "").strip()
        key = (source, identifier, width)
        if key in fetched:
            # Said rather than passed over in silence, so that a run of
            # twenty-six rows does not read as twenty-six fetches of a
            # rate-limited library.
            print(f"  {url}: {folios or 'the whole codex'}, from the record already read")
        else:
            print(f"  reading {url}")
            readers = {
                "cudl": cudl_scan,
                "manchester": manchester_scan,
                "openn": openn_scan,
                "alvin": alvin_scan,
                "iiif": iiif_scan,
            }
            fetched[key] = readers[source](identifier, width)
        record = fetched[key]

        if record is None:
            continue
        if not record.get("pages"):
            print(f"  skipped (the record names no images): {url}")
            continue

        pages, complaint = folio_range(record["pages"], folios)
        if complaint:
            print(f"  skipped ({complaint}): {url}")
            continue

        # Copied before anything is written into it, because the record behind it
        # is shared with every other row naming this codex: overriding the title
        # for Matthew would otherwise retitle Mark, Luke and John as well.
        entry = dict(record)
        if folios:
            # The resolved labels rather than the cell as it was typed, so that
            # "1r..21v" and "1r–21v" are one entry and not two.
            entry["id"] = (
                f"{entry['id']}-{page_id(pages[0]['label'])}-{page_id(pages[-1]['label'])}"
            )
        if entry["id"] in given:
            print(f"  skipped (another row is already {entry['id']}): {url}")
            continue
        given.add(entry["id"])

        # What the library calls it, unless the link list says otherwise. An
        # override is not second-guessing the library: a record may name a
        # codex in a way that says nothing about the part being transcribed.
        title = (row.get("title") or "").strip()
        if title:
            entry["title"] = title
        elif folios:
            # Twenty-six entries all called "Hebrew translation of the New
            # Testament" is a list nobody can choose a book out of.
            print(f"  warning: {url} {folios} has no title of its own, so it takes the codex's")

        # Given where the record does not carry one. A bare IIIF manifest states
        # no shelfmark at all — Gallica's says only "BnF. Département des
        # Manuscrits. Hébreu 132", as a title — and a scan with no shelfmark is
        # one a reader cannot file: it is what tells two manuscripts of the same
        # book apart, and what the picker heads a manuscript's books with.
        shelfmark = (row.get("shelfmark") or "").strip()
        if shelfmark:
            entry["shelfmark"] = shelfmark

        # Given for the same reason: a bare IIIF manifest states no repository
        # at all, and "Held at" is blank in the picker for every one of them —
        # Gallica, the Bodleian, the Laurenziana, the Vatican all name only
        # themselves in the licence line, never in a field this file can read.
        repository = (row.get("repository") or "").strip()
        if repository:
            entry["repository"] = repository

        # A credit line for a platform that publishes none. Alvin states no
        # fields at all, so an entry from it would otherwise reach Milah
        # crediting nobody, which is the one thing every scan here owes the
        # library that made it. Only filled where it is empty: a record that
        # names its own credit keeps it, wording and all.
        if not entry["attribution"] and entry["repository"]:
            entry["attribution"] = f"Provided by {entry['repository']}"

        # Where a library states its terms somewhere a manifest has no field
        # for. The Bodleian puts them in the attribution line and leaves
        # `license` unset; the Laurenziana states an access status and no terms
        # at all. This is for copying out what the library says — not for
        # deciding what it ought to have said, which is nobody's to decide here.
        licence = (row.get("licence") or "").strip()
        if licence:
            entry["licence"] = licence

        # Lifted out and put back so the folio list stays the last key of the
        # entry. It is hundreds of lines long, and anything after it would be
        # unreadable in a file people do open to see what is offered.
        entry.pop("pages")
        entry["book"] = (row.get("book") or "").strip()
        entry["source"] = url
        # Which part of the codex this is, said outright: several sliced entries
        # share a shelfmark, a date and a repository, and the first thing anyone
        # reading the file needs is which folios each one covers.
        entry["folios"] = folios
        # Written by hand in the link list, because they are judgements about
        # the text and no library record carries them.
        entry.update(judgements(row))
        # Always present and always empty here: this entry was resolved and
        # has pages. A stub for a manuscript with no scan is the only place
        # this field is ever non-empty — see unavailable_entry().
        entry["unavailable"] = ""
        entry["pages"] = pages

        if not entry["title"]:
            print(f"  warning: {url} has no title in its record and none given")
        if not entry["licence"]:
            print(f"  warning: {url} states no terms for its images")

        entries.append(entry)
    return entries


def probe(url: str) -> str:
    """Empty when an address answers with a picture, or why it does not.

    One byte is asked for rather than the image: this checks that the address is
    right, not that the folio is worth having. HEAD would be lighter still, but
    digi.vatlib.it answers HEAD with 405 — a check that reports the Vatican
    broken because it asked the wrong way is worse than no check at all.

    The content type is read as well as the status because the failure this
    exists to catch arrived as a 404 carrying HTML, and a library's "not
    available" page served as 200 would otherwise pass.
    """
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Range": "bytes=0-0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            kind = response.headers.get("Content-Type", "")
            if not kind.split(";")[0].strip().startswith("image/"):
                return f"answered {response.status} {kind or 'with no content type'}"
    except (urllib.error.URLError, TimeoutError, OSError) as failure:
        return str(failure)
    return ""


def verify(entries: list[dict]) -> int:
    """Fetch the first folio of every entry. Returns the number that failed.

    One page each rather than all of them. The addresses within an entry are
    built off one record by one rule, so they stand or fall together — and
    asking seven libraries for two thousand pictures to check a manifest is not
    a reasonable thing to do to them.

    Worth running whenever a reader is added or changed. The fault this was
    written after was a working manifest in every respect except that none of
    its addresses fetched anything, which no amount of reading it would show.
    """
    failures = 0
    for entry in entries:
        pages = entry.get("pages") or []
        if not pages:
            # A manuscript recorded as having no scan; nothing to check.
            continue
        reason = probe(pages[0]["image"])
        if reason:
            failures += 1
            print(f"  {entry['id']}: {reason}")
            print(f"    {pages[0]['image']}")

    checked = sum(1 for entry in entries if entry.get("pages"))
    if failures:
        print(f"{failures} of {checked} scans do not answer with an image")
    else:
        print(f"{checked} scans checked, every one answers with an image")
    return failures


#: src/ sits at the repository root, so the manifest is one level up. Named for
#: what it catalogues, beside manifest_manuscripts.json: one lists texts already
#: transcribed, this one lists images waiting to be.
REPOSITORY = Path(__file__).resolve().parents[1]
LINKS = Path(__file__).resolve().parent / "scan_links.tsv"
MANIFEST = REPOSITORY / "manifest_scans.json"


def parser() -> argparse.ArgumentParser:
    parsed = argparse.ArgumentParser(description=__doc__)
    parsed.add_argument(
        "--links",
        type=Path,
        default=LINKS,
        help="Tab-separated list of scan addresses.",
    )
    parsed.add_argument(
        "--out",
        type=Path,
        default=MANIFEST,
        help="Where to write the catalogue.",
    )
    parsed.add_argument(
        "--verify",
        action="store_true",
        help="After writing, fetch the first folio of every scan and report "
        "any that does not answer with an image. Off by default because it "
        "asks every library for a picture.",
    )
    return parsed


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)

    if not args.links.is_file():
        print(f"No such file: {args.links}")
        return 1

    entries = build(read_links(args.links))
    if not entries:
        print(f"Nothing could be read from {args.links}")
        return 1

    document = {
        "version": 1,
        "about": (
            "Published manuscript scans Milah can transcribe from, generated "
            "from the holding libraries' own records by src/build_scan_manifest.py "
            "in this repository. Do not edit by hand: regenerate it whenever "
            "src/scan_links.tsv changes. The images are linked, not copied — "
            "each scan stays on its library's server under the terms that "
            "library states, which are recorded with it."
        ),
        "scans": entries,
    }
    args.out.write_text(
        json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )

    # Offered, not held: a codex sliced into its books offers each of its images
    # once per book that covers it, so this counts higher than the number of
    # pictures on the library's server, and is meant to.
    folios = sum(len(entry["pages"]) for entry in entries)
    print(f"{len(entries)} scans, {folios} folios offered -> {args.out}")

    if args.verify and verify(entries):
        # Written all the same: a manifest that fetches nothing is easier to
        # read than to imagine, and the addresses are what has to be looked at.
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
