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

#: Cambridge's viewer address, which is what a reader copies out of the browser.
CUDL_VIEW = re.compile(r"/view/([^/?#]+)")
#: Its record, which is not the IIIF manifest. The manifest carries the same
#: facts with HTML and viewer-internal onclick handlers wrapped around them; this
#: gives each field as a plain string, and the dates machine-readable besides.
CUDL_RECORD = "https://services.cudl.lib.cam.ac.uk/v1/metadata/json/{item}"
#: Where the image server keeps a page, given the identifier the record names.
CUDL_IMAGE = "https://images.lib.cam.ac.uk/iiif/{image}.jp2"

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

    # Before the IIIF fallback below, which would otherwise never be reached for
    # OPenn but would be the wrong reader if its paths ever gained the word.
    if host.endswith(OPENN_HOST):
        found = OPENN_BROWSE.search(parsed.path) or OPENN_ITEM.search(parsed.path)
        if found:
            return "openn", f"{found.group(1)}/{found.group(2)}"
        return "", ""

    # Anything else that is plainly a IIIF manifest can still be read, just
    # without the richer record a library's own API would give.
    if "/iiif/" in parsed.path or parsed.path.endswith("manifest.json"):
        return "iiif", url.strip()

    return "", ""


def cudl_scan(item: str, width: int) -> dict | None:
    """One entry from Cambridge's own record of a manuscript."""
    record = fetch_json(CUDL_RECORD.format(item=item))
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
                "image": image_url(CUDL_IMAGE.format(image=identifier), width),
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
        # A credit line, not a rights statement. Cambridge splits rights in two:
        # displayImageRights covers its own zooming viewer and reads "All rights
        # reserved", while downloadImageRights covers fetching an image through
        # the Image API — which is what Milah does, and which is CC BY-NC. The
        # display terms are deliberately not recorded: they govern a viewer
        # nobody here uses, and printing "All rights reserved" beside a folio
        # fetched under a Creative Commons licence would misstate both.
        "attribution": f"Provided by {repository}" if repository else "",
        "licence": strip_html(str(metadata.get("downloadImageRights", ""))),
        "pages": pages,
    }


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
        "id": manifest_url,
        "title": _v3_label(manifest.get("label")),
        "shelfmark": "",
        "repository": "",
        "origin": "",
        "date": "",
        "language": "",
        "material": "",
        "provenance": "",
        "attribution": strip_html(str(manifest.get("attribution", ""))),
        "licence": strip_html(str(manifest.get("license", manifest.get("rights", "")))),
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
    # cannot key: it shows one of them twice and loses the other.
    given: set[str] = set()

    for row in rows:
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
            readers = {"cudl": cudl_scan, "openn": openn_scan, "iiif": iiif_scan}
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
        entry["pages"] = pages

        if not entry["title"]:
            print(f"  warning: {url} has no title in its record and none given")
        if not entry["licence"]:
            print(f"  warning: {url} states no terms for its images")

        entries.append(entry)
    return entries


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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
