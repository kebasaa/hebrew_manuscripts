# hebrew_manuscripts

Hebrew New Testament manuscript witnesses and their translations, as OSIS XML,
published for the [Milah](https://github.com/kebasaa/milah) collation app to
download.

## Layout

| path | what |
|---|---|
| `manuscripts/*.osis` | the texts |
| `manuscripts/manifest.json` | the catalogue Milah reads |
| `src/build_manifest.py` | writes the catalogue from the OSIS headers |
| `tests/` | checks on the generator |

The catalogue lives beside the texts it describes rather than at the root, so
Milah needs one address for both and the manifest cannot drift into describing a
different folder than the one it sits in.

Filenames are `BOOK_Witness_kind.osis`. A name ending `_translation` is loaded by
Milah as a translation rather than as a witness — the manifest states this
explicitly, because "not Hebrew" is not an honest test.

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

GPL-3.0. Individual transcriptions may carry their own attribution and copyright
in their OSIS headers; read them before redistributing.
