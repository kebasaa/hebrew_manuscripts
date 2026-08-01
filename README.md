# hebrew_manuscripts

Hebrew New Testament manuscript witnesses and their translations, as OSIS XML,
published for the [Milah](https://github.com/kebasaa/milah) collation app to
download.

## Layout

| path | what |
|---|---|
| `manuscripts/*.osis` | the texts |
| `manifest_manuscripts.json` | the catalogue Milah reads |
| `src/build_manifest.py` | writes the catalogue from the OSIS headers |
| `tests/` | checks on the generator |

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

## Tests

```bash
python -m unittest discover tests
```

## Licence

[CC BY-NC-SA 4.0](LICENSE) (Attribution-NonCommercial-ShareAlike). Individual
transcriptions may carry their own attribution and copyright in their OSIS
headers; read them before redistributing.
