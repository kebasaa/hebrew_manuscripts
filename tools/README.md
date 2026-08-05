# Tools

A reproducible converter turning Hebrew New Testament manuscript PDFs into
OSIS, and the generators that build the data files Milah reads at run time.

Nothing here is needed to build or run Milah, which lives in a sibling
repository, `milah` (`../../milah` relative to this file, if the two are
checked out side by side). The editor reads this corpus but does not depend
on the converter, and the two are developed independently.

```
tools/
  data/
    00_source_files/   the manuscript PDFs, the SWORD module, the scrape cache
  python/
    pdf2osis/          the converter package
    tools/             the generators for app/data/
    *.ipynb            notebooks driving the same package
```

The converted OSIS does not live here. It is written straight into
`manuscripts/` at the repository root — the published corpus — so there is no
second copy of any text to fall out of step with the one people download.

## Regenerating the corpus

Four commands, run from the repository root, in this order. Together they
rebuild every `.osis` file and the catalogue that lists them.

**1. Set up the environment, once.** `python\install_tp.bat` creates the shared
`tp` environment at `%USERPROFILE%\.venvs\tp`; then install this package into
it, from the `tools/` directory where `pyproject.toml` lives:

```powershell
tools\python\install_tp.bat
& "$env:USERPROFILE\.venvs\tp\Scripts\python.exe" -m pip install --no-build-isolation -e tools
```

**2. Convert every source.** No arguments needed: the sources default to
`tools/data/00_source_files` and the output to `manuscripts/`.

```powershell
& "$env:USERPROFILE\.venvs\tp\Scripts\python.exe" -m pdf2osis convert-all
```

This prints one JSON report per source — verse and chapter counts, empty and
alternate verses, note counts, excluded markers and anomalies. It takes a few
minutes, most of it Matthew's 25 PDFs. **Nothing is written unless every
variant of a source parsed and validated first**, so a failure leaves the
previous output untouched rather than half-replacing it.

To redo a single source, name it — `rev`, `jas`, `mat`, `sloane_rev`,
`ebr530_luke`, `ebr530_john`, `delitzsch`, `bsi_hnt`:

```powershell
& "$env:USERPROFILE\.venvs\tp\Scripts\python.exe" -m pdf2osis convert --book sloane_rev
```

Pass `--input` to convert a file from somewhere else, and `--output-dir` to
write somewhere other than `manuscripts/`.

**3. Rebuild the catalogue.** `manifest_manuscripts.json` is what Milah's
download dialog reads, and it carries each file's size and checksum, so it has
to be rebuilt whenever any `.osis` changes:

```powershell
& "$env:USERPROFILE\.venvs\tp\Scripts\python.exe" src\build_manifest.py
```

**4. Check the result.** Both suites, and then the diff:

```powershell
& "$env:USERPROFILE\.venvs\tp\Scripts\python.exe" -m pytest tools --basetemp tools\.pytest-tmp
& "$env:USERPROFILE\.venvs\tp\Scripts\python.exe" -m unittest discover tests
git status --short manuscripts/
```

`git status` should list only modified files. A file that appears or disappears
means a `BookProfile.stem` or `output_names()` changed, which changes what the
catalogue offers — check that it was meant.

### One source is generated but not published

`bsi_hnt` — the Bible Society in Israel's *HaBrit HaChadasha* — is converted
along with the rest so a local copy exists, but the publisher grants no reuse
permission of any kind. Its two files are git-ignored, and
`src/build_manifest.py` leaves them out of the catalogue: the manifest is a
list of downloads, and offering one the repository does not carry would fail
for whoever tried. The `.gitignore` rule and `build_manifest.LOCAL_ONLY_PREFIXES`
have to stay in step.

Its source is a scrape cache rather than a PDF, and refreshing that is a
separate, deliberate step — see [Modern Hebrew New Testament](#modern-hebrew-new-testament-scraped)
below. `convert-all` never touches the network.

## File naming

Output is named `<BOOK>_<Manuscript>_<variant>.osis`, as in
`REV_CochinOo.1.16.2_hebrew_commented.osis` or `LUK_Ebr530_translation.osis`.

`<BOOK>` is the uppercase three-letter code — `REV`, `JAS`, `MAT`, `LUK`,
`JOH` — or `NT` for a source spanning the whole New Testament in one file.
Note this is *not* the OSIS book id that names the `<div type="book"
osisID="…">` and every verse inside it (`Rev`, `Jas`, `Matt`, `Luke`, `John`):
the ids inside the file follow OSIS, the filename follows the shelf.

`<variant>` is `hebrew`, `hebrew_commented` or `translation`. Every filename
derives from `BookProfile.stem`, so that field is the single place the
convention lives.

**Which variants are published** is decided by `BookProfile.output_names()`.
The commented Hebrew is always published, and the translation wherever there is
one. The bare `hebrew` variant is published *only* where there is no separate
translation, as for Delitzsch: elsewhere the commented Hebrew carries the same
transcription plus an apparatus, and publishing both would put two copies of
one text in the catalogue. The bare variant is still buildable — `pdf2osis.osis`
exports `VARIANTS` for the tests that check the apparatus really is confined to
the annotated variants.

### Package layout

- `glyphs.py` — glyph-accurate decoding for PDFs whose ToUnicode CMap is wrong,
  resolving glyph IDs against each embedded font's own `cmap`
- `layout.py` — page geometry: column split, footnote separator detection,
  superscript and footnote-definition extraction
- `sloane.py` — extraction for British Library, Sloane MS 237
- `ebr530.py` — extraction for Vatican, Vat. ebr. 530 (Luke and John)
- `cochin.py` — one extractor per Cochin edition (`rev`, `jas`, `mat`)
- `osis.py` — OSIS construction: milestoned verses, attributed headers, and
  the indentation pass that gives one verse per line
- `validate.py`, `converter.py`, `profiles.py`, `models.py`

The CLI is the supported converter. The notebooks drive the same package and
exist for the commentary around it: `03_pdf2osis_REV_sloane237.ipynb` for the
Sloane 237 profile, `04_pdf2osis_LUK_JOH_ebr530.ipynb` for the two Vatican
ebr. 530 profiles, and `05_pdf2osis_cochin.ipynb` for the Cochin editions.

### Pointed manuscripts

MuPDF ≥1.26 already returns Hebrew in logical order, so nothing reverses it —
re-reversing, as the old notebooks did, roughly doubles the error rate. What
does need repair is the glyph mapping, and the two pointed manuscripts fail in
opposite ways:

| source | ToUnicode | embedded `cmap` | primitive |
|---|---|---|---|
| Sloane 237 | broken, ~12% of glyphs | present, correct | `get_texttrace` + font cmap |
| Vat. ebr. 530 | correct | **absent entirely** | `rawdict` glyph geometry |

Sloane 237's PDF embeds `David` as a Type0/Identity-H subset whose ToUnicode
CMap covers 30 of the ~170 glyph IDs in use and gets several wrong: sheva
decodes as dagesh, hiriq and qubuts as a shin dot, hataf segol as a space —
which is why a naive extraction produces more shin dots than shins. Its
embedded `cmap` is correct, so `pdf2osis.glyphs` resolves glyph IDs there.

Vat. ebr. 530's subsets have no `cmap` at all, and `get_texttrace` merges
adjacent runs — sometimes two whole printed lines — into one span, so reversing
a span swaps its runs. That profile reads `rawdict` and places each glyph by its
own coordinates. A combining mark is drawn at its base letter's left edge, so
attachment is exact; where two vowels overlap between neighbouring letters, the
rule that no letter takes the same point twice separates them.

`pdf2osis.layout` detects the footnote separator rule per page instead of
assuming a fixed y band; the rule moves between y=518 and y=621, and a fixed
band both dropped Revelation 1:18 and double-counted body text as footnotes.

### OSIS structure

All output uses milestoned `<chapter>` and `<verse>` so that material
belonging to no verse can sit in the flow:

- `<div type="introduction">` with a `<title type="main">` for the manuscript
  incipit, and `<div type="titlePage">` for the edition's title block
- `<title type="chapter">` for the gate heading dividing the two chapters
- `<milestone type="pb">` for the eight folio boundaries, at their true
  position — including mid-verse
- `<milestone type="x-ms-verse">` for divisions the manuscript numbers but the
  edition leaves unnumbered

Notes are `<note type="explanation" placement="foot">` with `osisRef` and
`osisID`, anchored at the offset where their superscript is printed.
`type="footnote"` is *not* a valid OSIS 2.1.1 note type, so nothing emits it.

Where a source states its own reference for a verse, it rides on
`subType="x-alt-…"` — Sloane's Hebrew letter-numerals, which disagree with the
printed numbering at Rev 1:9, 1:15, 1:16, 1:17 and 2:8, and Cochin's own
chapter and verse. OSIS requires such values to begin with `x-`, which is why
this is not a private-namespace attribute. The canonical reference stays in
`osisID`, and `n` carries the printed label — a range, such as `19-20`, where
one record covers two verses.

Every file validates against the upstream `osisCore.2.1.1.xsd`, vendored in
`tools/python/pdf2osis/schema/`, and is pretty-printed one verse per line.

### Cataloguing the manuscript

Five `<description type="x-…">` elements describe the physical object rather
than the file, which is why a translation carries the same answers as the
witness it renders — it is a rendering of the same object. They come from
`BookProfile`'s `folios`, `material`, `provenance`, `translated_from` and
`exemplar`, and `src/build_manifest.py` reads each into a column of the
catalogue.

| element | what it answers |
|---|---|
| `x-folios` | which folios of the codex this book occupies |
| `x-material` | what it is written on, and how much of it there is |
| `x-provenance` | how it reached the collection that holds it |
| `x-translated-from` | what the Hebrew was translated from |
| `x-exemplar` | what it was copied from |

This is the vocabulary Milah's transcription tab writes from its metadata dock
(`app/src/transcription_controller.cpp` in the sibling `milah` repository), so
a text transcribed by hand and one converted here describe themselves alike.

**All five are written whether or not there is an answer**, an unanswered one
as an empty element. To someone looking for the folios of a manuscript a
missing element and an empty one say the same nothing; the empty one at least
records that the question was put and has no published answer. That matters
here because several genuinely have none — no catalogue states what Cochin
Oo.1.16.2 is written on, and no exemplar is identified for any of the
manuscripts — and inventing one would be worse than saying so.

Every sentence names the authority it came from, in the same spirit as
`sources`. Two cases are worth reading before adding more:

- **A contested question records the disagreement rather than settling it.**
  What the Cochin manuscripts were translated from is disputed — van Dort
  argues from the Luther and Statenvertaling Bibles, van Rensburg finds most
  books close to the Syriac Peshitta while holding that Revelation, James and
  Jude derive from none of the Greek, Latin or Aramaic, and Cambridge names no
  source language at all. All three positions are named. Picking one would turn
  an open question into a fact of the catalogue.
- **"Nobody has said" and "the editor declined to say" are different answers.**
  Sloane 237's `x-translated-from` records that the editor put the question and
  said outright he had no answer; Vat. ebr. 530's is empty, because its
  catalogue simply never addresses it.

### Rights and licensing

Every variant of every file carries two `<rights>` elements, told apart by
`type` — the schema permits both the `type` attribute and repeating the
element (`rightsCT` in `osisCore.2.1.1.xsd`). They answer two different
questions, and `_work()` in `pdf2osis/osis.py` never conflates them:

- **`<rights type="x-copyright">`** — who holds copyright. Stated on the
  translation (or the sole variant, for a source with no separate
  translation), and on the commented Hebrew transcription too, wherever a
  named person or publisher did that commenting — Gordon's annotations,
  PTM's interlinear apparatus. The bare, uncommented `hebrew` variant of a
  source that also has a translation carries an **empty** element: nobody in
  particular is credited with producing it, and an empty `<rights>` says
  that was considered and answered "nobody" rather than skipped.
- **`<rights type="x-license">`** — what a reader may do with it. Never
  empty. Either the source's own stated term, verbatim (`profile.license` on
  the relevant `BookProfile`), or this repository's own default, **only**
  when the source states nothing at all:

  ```
  CC BY-NC-SA 4.0 (repository default; no licence stated in the source).
  ```

  The default is never used to loosen a term a source did state, however
  strict — Gordon's Ebr. 530 work is "All rights reserved.", the Cochin
  editions are "All Rights Reserved" (confirmed directly with Janice F. Baca
  / Project Truth Ministries, not printed in the PDFs themselves), and the
  Bible Society in Israel's scrape states outright that no reuse permission
  exists at all. Only `sloane_rev` currently has nothing stated and falls
  back to the default.

`src/build_manifest.py`, at the repository root, reads both into
`manifest_manuscripts.json` as separate `rights` and `license` fields, so a
reader of the catalogue sees which is which without opening the `.osis` file.

### Coverage

| profile | records | extent |
|---|---|---|
| `rev` | 405 | Revelation 1:1–22:21, including the combined `14:19-20` record |
| `jas` | 107 | James 1:1–5:20; its `2:15` record covers KJV 2:15–16, so there is no independent `2:26` |
| `mat` | 910 | Matthew 1:1–25:46, published a chapter at a time and still growing |
| `sloane_rev` | 33 | Revelation 1:1–2:13 |
| `ebr530_luke` / `ebr530_john` | 35 / 13 | Luke 1:1–35, John 1:1–13 |
| `delitzsch` | 7959 | The whole New Testament, Matthew 1:1–Revelation 22:21, one file |
| `bsi_hnt` | 7959 | The whole New Testament, Matthew 1:1–Revelation 22:21, one file |

Revelation is **405**, arrived at from two corrections in opposite directions.
`Rev 2:26` (PDF page 54) and `Rev 20:12` (page 329) are in the source but their
headers are not set at the usual type size, so a size-keyed search missed them;
both were checked against the rendered pages. Against that, the second
`Revelation 2:21` header is not a verse at all — see below — so counting it gave
406.

#### Verses the manuscripts lack

Five references are printed with no text because the manuscript has none:
`Rev 2:6`, `2:28`, `9:9`, `16:11` and `Jas 1:21`. Each is emitted as a numbered,
empty verse carrying the edition's own notice — "This verse does not exist in
the Cochin Oo.1.16.2 manuscript" — as a `<note type="explanation">` with
`osisID="…!note.absent"`. Absence by design is therefore never mistaken for a
gap in extraction.

Detection is anchored to the start of a transcription, translation or `Note:`
field. The same words appear elsewhere meaning something else: `Rev 14:19-20`'s
note says "verse 20 does not exist" while the record itself holds verse 19, Matt
8:10 translates "there does not exist faith like this", and the KJV and Aramaic
comparison columns use the phrase for their own missing text.

#### Verses the manuscript transposes

Cochin Oo.1.16.2 swaps `Rev 2:21` and `2:22` — Cochin 2:20 = KJV 2:22, Cochin
2:21 = KJV 2:21 — and the edition follows the manuscript's order. It marks the
swap with a bare `Revelation 2:21` header on page 50 whose whole content is
"Note: The Cochin manuscript changes the order of the following verses"; the
verse itself is on page 51. That signpost is not a verse, and counting it split
2:21 into a spurious empty `21a` and a real `21b`. It now attaches to `Rev.2.21`
as a `…!note.order` note.

Both transposed verses carry `type="x-reordered"`, which is a separate
`attributeExtension` from the `subType` holding the Cochin reference, so the
flag survives into the `hebrew` variant that has no apparatus. They are the only
two out-of-order verses in the corpus; James and Matthew have none.

### Cochin extraction

The Cochin editions share a house style but not a format, so each has its own
extractor in `pdf2osis/cochin.py`: Revelation is headed `Revelation N:V (Cochin
N:V)` and carries an interlinear gloss table, James is headed `James N:V (KJV …)`
with no such table, and Matthew is headed `Chapter C:V` and prints a Syriac
Aramaic column at the same type size as its English — so script, not size,
separates them. All three headers are read by one `parse_reference`, because
Matthew's occasionally carries the manuscript's own reference too: `Chapter
17:23 (Cochin 17:22b)`. A pattern that allowed no parenthetical dropped 17:23
and 17:24 outright, and a verse lost that way leaves nothing behind to notice.

#### Matthew is published a chapter at a time

Revelation and James are each one volume. Matthew is **25 of them**, a chapter
each, in `data/00_source_files/MS_Cochin_Oo.1.32_Mat_PTM/`, revised and
re-exported as the editor works. So the `mat` profile names that directory
rather than a file, and `BookProfile.part_pattern` picks the parts out of it in
chapter order — keyed on the chapter number in each filename, because the
publisher's names are not otherwise consistent (`Mathew` and `Matthew`, padded
and unpadded, a different date on every file).

Two things follow from reading a book in parts, both handled in `_run`:

- **Each part has its own front matter** — a title page, a copyright page and
  an introduction, the last with footnotes of its own — so nothing before a
  part's first verse header is read at all. This is why `mat` needs no
  `first_page`: the front matter is a different length in every file.
- **Each part numbers its footnotes from one**, so across the book those
  numbers collide — 52 of the 56 printed numbers are reused, and merging under
  them would let one note silently overwrite another. The parts are therefore
  renumbered into a single sequence as they are joined, and a note's `n` here
  is its place in the whole book rather than the number printed in that
  chapter's own volume. Markers are matched against their own part's
  definitions *before* the merge; afterwards a later part's note 6 would
  happily satisfy an earlier part's dangling marker 6. Renumbering is confined
  to editions that come in parts — Revelation's notes run 15–588 and James's
  8–33, and renumbering those would move every note in files already published.

Where the interlinear table repeats a transcription word at the same length and
differs in exactly one letter, the gloss wins: the two are set in different
subsets of one face and each resolves letters the other confuses (he read as
het, bet as kaf). Anything less clear-cut is left alone, because the
transcription is the authority on wording and order.

Output is pretty-printed one verse per line. lxml's `pretty_print` refuses to
reformat mixed content, which is exactly what milestone form produces, so
`pdf2osis.osis.indent_body` sets the tails by hand.

### Delitzsch Hebrew New Testament (SWORD module)

Not a PDF: `pdf2osis/sword.py` reads a CrossWire SWORD module directly with
`pysword`, which returns clean, already verse-segmented text — no glyph
decoding or page-layout detection applies here at all. The module's own
`Versification` declaration (NRSV) is the source of truth for how many
chapters and verses each book has.

This is a whole-Testament source — one translation across all 27 NT books —
so it produces **one file** covering the whole NT, not 27 per-book files:
`pdf2osis/osis.py`'s `build_multibook_osis` writes one `<div type="book">` per
book inside a single `osisText`, in canonical order (Matthew … Revelation).
`build_structured_osis` (every other, single-book profile) shares a
`_write_book` helper with it; only the wrapping around that shared per-book
logic differs.

Three verses across the whole NT — 2 Corinthians 13:14, 3 John 1:15,
Revelation 12:18 — are NRSV versification slots this module's text does not
fill. They are kept, numbered, empty, with the reason as a note.

There is no accompanying English text at all, so `BookProfile.has_translation
= False` suppresses the `translation` variant entirely, and the copyright and
translator credit — normally only on the translation variant (or the
commented Hebrew one, see "Rights and licensing" above) — move to *every*
Hebrew variant here, since there is nowhere else for those facts to go.

**Licensing**: the module is Streams in the Negev's 2003 transcription and
repointing of Delitzsch's 1885 translation, distributed by CrossWire
"free for use by any non-commercial project" — not public domain. Split
across `profiles.DELITZSCH`'s two fields: `rights` states the copyright
("Copyright 2003 (Streams in the Negev).") and `license` states this reuse
term verbatim, not the repository's CC BY-NC-SA default. The module zip is
downloaded, not committed (`tools/data/00_source_files/sword/`), and
`tests/test_sword.py` skips if it is not present locally.

### Modern Hebrew New Testament (scraped)

*HaBrit HaChadasha* (Bible Society in Israel, 1995, revised 2010) has no
digital edition, app or API the publisher offers directly — the only place
its text exists online is a third-party mirror, `nocr.net`, which prints it
one chapter at a time with no bulk export. `pdf2osis/bsi_hnt.py` therefore
splits into two steps that never touch the network at the same time:

- `fetch_bsi_nt()` walks all 27 books, chapter by chapter, until a chapter
  comes back with no Hebrew cell (there is no chapter count published
  anywhere to check against), and writes the result to a local JSON cache —
  a politeness delay is applied between requests, since this is a small,
  non-commercial mirror, not an API meant for bulk access.
- `extract_bsi_nt()` reads that cache. Conversion, including every test in
  `tests/test_bsi_hnt.py`, never re-scrapes the site.

Verse numbers are printed inline in each chapter's text ("1:1 … 1:2 …") with
no other delimiter, so splitting on that pattern is the only way to recover
individual verses; the split result is checked for strictly sequential verse
numbers, which is what would break if a verse's own text happened to contain
something that looked like a reference. The site's own combining-mark order
for Hebrew niqqud varies verse to verse for visually identical text, so
`_split_verses` normalises every verse to NFC — un-normalised, two "identical"
verses can fail `==` while rendering the same.

Structurally this mirrors Delitzsch exactly — one multi-book file via the same
`build_multibook_osis`, no `translation` variant, the same NRSV-shaped
versification (7959 verses total, matching Delitzsch's count, confirmed rather
than assumed). It is fully pointed with niqqud, unlike ordinary modern Hebrew
prose, though without Delitzsch's cantillation marks. Sixteen verses across
the NT are printed with no text — thirteen are the well-known verses modern
NT translations based on the earliest manuscripts omit or restructure (Matt
17:21, Mark 9:44, Acts 8:37, and others), and Romans 9:12 and 16:24 are
combined-verse cases where the source prints the reference with nothing
before the next one. All are kept, numbered, empty, with a note.

**Licensing**: unlike Delitzsch, there is **no license grant at all** — the
source states only "copyrighted (c) 1995, revised (c) 2010 by The Bible
Society in Israel," with no reuse or redistribution permission anywhere.
`profiles.BSI_HNT.rights` states the copyright notice; `.license` states the
absence of permission verbatim, in the OSIS header's `x-license` element —
this is the one profile whose `license` is a real stated refusal, not the
repository's CC BY-NC-SA default, and not empty either: "no licence" is
itself a fact worth recording, not an unanswered question. The cache
(`tools/data/00_source_files/bsi_hnt/`) and generated output are for local
use only — not committed, not redistributed, absent direct permission from
the publisher.

### Known issues

- The Cochin editions print no material outside their verses, so unlike the two
  manuscripts they carry no `<title>`, folio milestones or introduction div —
  there is nothing in the source to put there.
- The absence and order notices are attached as notes, so they appear only in
  the `hebrew_commented` and `translation` variants. The `x-reordered` flag is
  an attribute and appears in all of them.
- PyMuPDF must be ≥1.26, where MuPDF switched to returning text in logical
  order. Every extractor reads Hebrew on that assumption, so an older wheel
  reverses it silently rather than failing.

## Data-file generators

`tools/python/tools/` builds the files Milah reads from its own `app/data/` at
run time. Milah lives in the sibling `milah` repository, so these write across
a repo boundary — every command below is run from this repository's root and
assumes `milah` is checked out beside it, reachable as `../milah` from there.
They are run rarely and their output is committed to `milah`, so a normal
Milah build never needs them.

```powershell
python tools/python/tools/build_lexicon.py --strongs <…> --wlc <…> --tbesh <…> --out ../milah/app/data/hebrew_lexicon.json
python tools/python/tools/build_wordlist.py --out ../milah/app/data/rabbinic.words.txt
python tools/python/tools/build_roots.py --lexicon ../milah/app/data/hebrew_lexicon.json --output ../milah/app/data/hebrew_roots.json
```

- `build_lexicon.py` — Strong's numbers and the inflected forms they appear as
- `build_wordlist.py` — rabbinic Hebrew vocabulary, refusing any Sefaria version
  that is not public domain, CC0 or CC-BY
- `build_roots.py` — the root index the suggestion checks consult

`build_lexicon.py` mirrors `comparisonKey()` from `app/src/core/tokenize.cpp`
in the `milah` repository character for character; the two are a join key and
must not drift.

**Sources, licences and what each file covers are documented in
`milah`'s `app/data/README.md`** — including the attribution that CC-BY
requires and that travels with every build.
