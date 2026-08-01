# hebrew_manuscripts

Hebrew New Testament manuscript witnesses and their translations, as OSIS XML,
published for the [Milah](https://github.com/kebasaa/milah) collation app to
download.

## Layout

| path | what |
|---|---|
| `manuscripts/*.osis` | the texts |
| `manifest_manuscripts.json` | the catalogue of texts Milah reads |
| `src/build_manifest.py` | writes that catalogue from the OSIS headers |
| `manifest_scans.json` | the catalogue of published scans Milah reads |
| `src/scan_links.tsv` | the scans offered, one address per row |
| `src/build_scan_manifest.py` | writes that catalogue from the libraries' records |
| `tests/` | checks on the generators |

Two catalogues, because they hold opposite things: one lists **texts already
transcribed** that Milah downloads and collates, the other lists **images waiting
to be transcribed** that Milah opens a folio at a time.

Each manifest entry names a **file, not a path** — where the texts are kept is
Milah's to know. Moving the folder is then one constant in the app rather than a
rewrite of every entry.

### File format

Every text is [OSIS](https://www.bibletechnologies.net/) XML, validated against
`osisCore.2.1.1.xsd`: verses are marked with paired `<verse sID.../>` /
`<verse eID.../>` milestones, editorial remarks are `<note>` elements inline in
the text, and a `<header>` carries the bibliographic and provenance metadata
(title, contributor, shelfmark, repository, date, rights, coverage, …) that
`build_manifest.py` reads to build the catalogue.

### Filenames

Filenames are `BOOK_Witness_kind.osis`, where `kind` is one of:

| suffix | contents | manifest role |
|---|---|---|
| `_hebrew_commented.osis` | the Hebrew transcription of the witness — full text with footnotes on textual and grammatical peculiarities (irregular pointing, variant forms, etc.) | `manuscript` |
| `_translation.osis` | the accompanying English translation, same verse structure | `translation` |

`build_manifest.py` derives the role from this suffix rather than from the
declared `xml:lang`, and warns if a `_translation`-named file declares Hebrew —
the filename is the explicit signal, because "not Hebrew" is not an honest
test.

## After adding or correcting a text

```bash
python src/build_manifest.py
```

No arguments needed. Commit the result: the manifest is what Milah reads, so a
stale one hides a manuscript sitting right beside it. It carries a `sha256` per
file, which is how Milah tells a reader that a text they downloaded has since
been corrected — a size cannot, because fixing `Sloane MS 237` to
`MS Sloane 273` moves not one byte.

Sizes and checksums are taken over the LF form of each file, which is what
GitHub serves and therefore what Milah downloads. Measuring the working copy
instead would make every manuscript report an update for ever on any clone
checked out with `core.autocrlf=true`, and taking the update would not settle it.

## After adding a scan

Add its address to `src/scan_links.tsv` — the URL as copied from the library's
own viewer — and re-run:

```bash
python src/build_scan_manifest.py
```

Unlike the text catalogue, **this one needs the internet**: what it writes is
resolved from the holding library's own record, so the title, shelfmark, date,
origin and the address of every folio are the library's own and not somebody's
transcription of them. Commit the result.

Scans are **linked, not copied**. No image is downloaded here and none is kept in
this repository: an entry says where each folio lives on the library's server,
and carries the licence and attribution that library states. Cambridge's images,
for instance, are CC BY-NC 3.0 — which is why the terms travel with the entry
rather than being assumed to match this repository's own licence.

Only `url` is required in a row. `title` overrides a library record that names a
whole codex where only part of it is being transcribed, `book` groups a scan that
is of one book, and `width` asks for a different image size — honoured only where
the library lets a size be asked for. Cambridge serves any width but caps
delivery at 2000px; OPenn publishes fixed derivatives and chooses for you, and
says so when a row asks anyway.

`build_scan_manifest.py` knows three kinds of source:

| source | how it is read |
|---|---|
| Cambridge (CUDL) | its own JSON record, which gives clean fields where the IIIF manifest gives HTML |
| OPenn | the TEI description beside the images — OPenn publishes no API at all |
| anything else | a IIIF manifest, Presentation v2 or v3 — the Bodleian, the Vatican, e-codices, the National Library of Israel |

Adding a library means a resolver function and a line in `parse_link`, so that
every library's quirks stay here rather than in the app. Milah only ever sees a
list of image addresses, which is why adding OPenn needed no change to it at all.

Only the `web` derivatives are linked from OPenn. Its masters are sometimes TIFF,
which Milah cannot decode and which OPenn's own `robots.txt` declines to serve to
a program.

## Tests

```bash
python -m unittest discover tests
```

Nothing in them touches the network. The scan generator's transforms are pinned
against recorded fixtures, and the published `manifest_scans.json` is checked for
shape rather than rebuilt — a test that needed Cambridge would fail on a train,
and would quietly be testing their uptime rather than this code.

## Licence

[CC BY-NC-SA 4.0](LICENSE) (Attribution-NonCommercial-ShareAlike). Individual
transcriptions may carry their own attribution and copyright in their OSIS
headers; read them before redistributing.
