from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BookProfile:
    key: str
    name: str
    osis_book: str
    scope: str
    stem: str
    default_pdf: str
    first_page: int
    last_page: int
    header_y1: float
    footer_y0: float
    expected_first: tuple[int, str]
    expected_last: tuple[int, str]
    expected_chapters: int
    expected_verses: int
    manuscript: str
    alt_namespace: str
    hebrew_work: str
    translation_work: str
    title: str
    translation_title: str
    description: str
    expected_hebrew_prefix: str

    # Which module extracts this source: pdf2osis.cochin, .sloane, .ebr530 or
    # .sword.
    extractor: str = "cochin"
    # False for a source with no accompanying English text at all — Delitzsch
    # is a Hebrew-only translation — so no translation variant is produced and
    # `validate_records` does not expect `record.english` to be populated.
    has_translation: bool = True
    # The CrossWire/SWORD module identifier this profile reads; see
    # pdf2osis.sword. Irrelevant for every other extractor.
    sword_module: str = ""
    # The OSIS book abbreviations a multi-book source covers, in the order
    # they must appear. Empty for every single-book profile; see
    # pdf2osis.osis.build_multibook_osis and validate_multibook_records.
    expected_book_order: tuple[str, ...] = ()
    # Provenance for the OSIS header, as ``(type, text)`` pairs. OSIS restricts
    # description/@type to `usfm` or an `x-` extension, so these are `x-…`
    # values. Every claim here should be traceable to one of `sources`.
    descriptions: tuple[tuple[str, str], ...] = ()
    # Where the provenance came from, emitted as <source> elements so a reader
    # can check it rather than take our word for it.
    sources: tuple[str, ...] = ()
    coverage: str = ""
    relation: str = ""
    # Page geometry, which differs per source; see pdf2osis.layout.
    footer_top: float = 660.0
    column_split: float = 305.0
    # The book's own name, where it differs from the OSIS abbreviation.
    osis_book_name: str = ""
    # Which Cochin extractor handles this edition; see pdf2osis.cochin.
    cochin_book: str = ""
    # An edition published a part at a time rather than as one volume. When set,
    # `default_pdf` names a directory and every PDF in it matching this pattern
    # is read, ordered by the integer its `chapter` group captures. The names
    # themselves are not listed: this publisher renames and re-exports files
    # freely, so matching on the chapter number survives what a fixed list of
    # filenames would not. Empty for every edition published in one volume, and
    # `first_page`/`last_page` are then unused — each part carries its own front
    # matter, so the body start is found per file rather than configured.
    part_pattern: str = ""
    # Calendar for <date>. A century range is not an ISO date.
    date_calendar: str = "ISO"
    # Header credits. The defaults describe the Project Truth Ministries Cochin
    # editions; other sources override them.
    publisher: str = "Project Truth Ministries"
    original_date: str = "ca. 1730"
    edition_date: str = "2024"
    translator: str = "Project Truth Ministries"
    contributor: str = "Janice F. Baca"
    contributor_file_as: str = "Baca, Janice F."
    # Who holds copyright over this text, and when — attribution only. May
    # legitimately be empty (see osis._work): the bare, uncommented Hebrew
    # variant of a source that also has a translation carries none, because
    # nobody in particular is credited with producing it.
    rights: str = "© copyright 2024 Janice F. Baca"
    # What a reader may do with it — never empty, unlike `rights` above. This
    # is this repository's stated default for a source that states no reuse
    # terms of its own; a source that does state something, however strict
    # ("All rights reserved."), overrides this field to say that instead. Never
    # invented, never silently loosened past what the source actually says.
    license: str = (
        "CC BY-NC-SA 4.0 (repository default; no licence stated in the source)."
    )

    def output_names(self) -> dict[str, str]:
        names = {
            "hebrew": f"{self.stem}_hebrew.osis",
            "hebrew_commented": f"{self.stem}_hebrew_commented.osis",
        }
        if self.has_translation:
            names["translation"] = f"{self.stem}_translation.osis"
        return names

    def default_path(self, source_dir: Path) -> Path:
        return source_dir / self.default_pdf

    def part_paths(self, source: Path) -> list[Path]:
        """Every file this edition is made of, in reading order.

        One entry — `source` itself — unless the edition was published a part
        at a time, in which case `source` is the directory holding the parts
        and they are ordered by the chapter each one covers. Sorting on the
        captured number rather than the filename keeps the order right however
        the publisher pads or spells them.
        """
        if not self.part_pattern:
            return [source]

        pattern = re.compile(self.part_pattern, re.I)
        found: dict[int, Path] = {}
        for path in sorted(source.glob("*.pdf")):
            match = pattern.search(path.name)
            if match is None:
                continue
            chapter = int(match.group("chapter"))
            if chapter in found:
                raise ValueError(
                    f"{self.key}: two files claim chapter {chapter}: "
                    f"{found[chapter].name} and {path.name}"
                )
            found[chapter] = path
        if not found:
            raise ValueError(
                f"{self.key}: no part of this edition found in {source}"
            )
        return [found[chapter] for chapter in sorted(found)]


REV = BookProfile(
    key="rev",
    name="Revelation",
    osis_book="Rev",
    scope="Rev",
    stem="Rev_CochinOo.1.16.2",
    default_pdf="MS_Cochin_Oo.1.16.2_REV_ProjectTruthMinistries.pdf",
    first_page=15,
    # The final 22:21 transcription is on PDF page 370 and its translation
    # continues on page 371. Page 372 starts the back matter.
    last_page=370,
    header_y1=40,
    footer_y0=728,
    expected_first=(1, "1"),
    expected_last=(22, "21"),
    expected_chapters=22,
    # 405. Revelation 2:26 and 20:12 are in the source but their headers are not
    # set at the usual size, so the old extractor's size-keyed search dropped
    # them, giving 404. Against that, the second "Revelation 2:21" header is not
    # a verse at all: it is a signpost carrying the notice that the manuscript
    # transposes 2:21 and 2:22, and counting it gave 406.
    expected_verses=405,
    manuscript="MS.Oo.1.16.2",
    alt_namespace="https://projecttruthministries.org/studies/cochin-revelation/",
    hebrew_work="CochinOo.1.16.2_REV_Hebrew",
    translation_work="CochinOo.1.16.2_REV_PTM",
    title="Revelation (Cochin MS Oo.1.16.2)",
    translation_title="Translation of Revelation (Cochin MS Oo.1.16.2)",
    description=(
        "The Cochin Hebrew New Testament manuscripts are significant "
        "18th-century Hebrew versions of the New Testament. This file "
        "encodes Revelation from Cambridge MS Oo.1.16.2."
    ),
    expected_hebrew_prefix="אלה הסודות",
    cochin_book="rev",
    # Confirmed directly with Janice F. Baca / Project Truth Ministries: this
    # edition is All Rights Reserved. Not previously stated in any published
    # file's rights text — new information the tool has to be told, not read
    # out of the source PDF.
    license="All Rights Reserved",
)

JAS = BookProfile(
    key="jas",
    name="James",
    osis_book="Jas",
    scope="Jas",
    stem="Jas_CochinOo.1.32",
    default_pdf="MS_Cochin_Oo.1.32_JAS_ProjectTruthMinistries.pdf",
    first_page=10,
    last_page=68,
    header_y1=49,
    footer_y0=728,
    expected_first=(1, "1"),
    expected_last=(5, "20"),
    expected_chapters=5,
    expected_verses=107,
    manuscript="MS.Oo.1.32",
    alt_namespace="https://projecttruthministries.org/studies/cochin-james/",
    hebrew_work="CochinOo.1.32_JAS_Hebrew",
    translation_work="CochinOo.1.32_JAS_PTM",
    title="James (Cochin MS Oo.1.32)",
    translation_title="Translation of James (Cochin MS Oo.1.32)",
    description=(
        "The Cochin Hebrew New Testament manuscripts are significant "
        "18th-century Hebrew versions of the New Testament. This file "
        "encodes James from Cambridge MS Oo.1.32."
    ),
    expected_hebrew_prefix="יעקב עבד",
    cochin_book="jas",
    # See REV — confirmed directly, the same publisher and terms.
    license="All Rights Reserved",
)

SLOANE_REV = BookProfile(
    key="sloane_rev",
    name="Revelation",
    osis_book="Rev",
    scope="Rev",
    # The edition prints "MS Sloane 273", but the British Library catalogue
    # records the Hebrew Revelation as Sloane MS 237 — four paper folios in
    # square Hebrew script, which is exactly the 1r–4v this text occupies.
    stem="Rev_Sloane237",
    default_pdf=(
        "A-Hebrew-Manuscript-of-the-Book-of-Revelation-"
        "British-Library-Sloane-273.pdf"
    ),
    first_page=1,
    last_page=11,
    header_y1=60,
    footer_y0=660,
    expected_first=(1, "1"),
    expected_last=(2, "13"),
    expected_chapters=2,
    expected_verses=33,
    manuscript="British Library, Sloane MS 237",
    alt_namespace="https://www.nehemiaswall.com/sloane-273",
    hebrew_work="Sloane237_REV_Hebrew",
    translation_work="Sloane237_REV_Gordon",
    title="Revelation (British Library, Sloane MS 237)",
    translation_title=(
        "English Translation of Revelation (British Library, Sloane MS 237)"
    ),
    description=(
        "Hebrew transcription and English translation of the Revelation "
        "passages in British Library, Sloane MS 237, a fully pointed Hebrew "
        "manuscript, transcribed and translated by Nehemia Gordon."
    ),
    descriptions=(
        (
            "x-contents",
            "A Hebrew translation of the Revelation of John occupying four "
            "paper folios, 1r–4v. This edition covers Revelation 1:1–2:13.",
        ),
        (
            "x-script",
            "Square Hebrew script, fully vocalised, ruled and written ten "
            "lines to the page.",
        ),
        (
            "x-provenance",
            "From the collection of Sir Hans Sloane (1660–1753), baronet, "
            "physician and collector. Part of the Sloane bequest, "
            "incorporated into the newly founded British Museum in 1753 and "
            "held by the British Library since 1973.",
        ),
        (
            "x-editorial",
            "The editor's notes record pointing absent from the manuscript — "
            "a missing sheva, shin- and sin-dots, and a cholam — together "
            "with one extraneous kamatz that the manuscript does carry. The "
            "manuscript numbers its own verses with Hebrew letters, which "
            "disagree with the printed numbering at Revelation 1:9, 1:15, "
            "1:16, 1:17 and 2:8.",
        ),
    ),
    sources=(
        "Shelfmark, extent, script, date and provenance from the British "
        "Library Archives and Manuscripts catalogue record for Sloane MS 237.",
        "Text, translation and annotation from Nehemia Gordon, 'A Hebrew "
        "Manuscript of the Book of Revelation' (2017), nehemiaswall.com.",
    ),
    coverage="Revelation 1:1–2:13",
    date_calendar="Gregorian",
    expected_hebrew_prefix="חֲזוֹן יְהוֹשֻׁעַ",
    extractor="sloane",
    publisher="Nehemia Gordon",
    original_date="between 1500 and 1699",
    edition_date="2017",
    translator="Nehemia Gordon",
    contributor="Nehemia Gordon",
    contributor_file_as="Gordon, Nehemia",
    rights="© 2017 by Nehemia Gordon",
)


EBR530_LUKE = BookProfile(
    key="ebr530_luke",
    name="Luke",
    osis_book="Luke",
    osis_book_name="Luke",
    scope="Luke",
    stem="Luke_Ebr530",
    default_pdf=(
        "Hebrew-Gospels-of-Luke-and-John-from-the-Vatican_"
        "Biblioteca Apostolica ebr. 530.pdf"
    ),
    first_page=1,
    last_page=13,
    header_y1=60,
    footer_y0=701,
    expected_first=(1, "1"),
    expected_last=(1, '35'),
    expected_chapters=1,
    expected_verses=35,
    manuscript=(
        "Biblioteca Apostolica Vaticana, Vat. ebr. 530, part 1, fragment 11, "
        "folios 1r–2v"
    ),
    alt_namespace="https://digi.vatlib.it/view/MSS_Vat.ebr.530.pt.1",
    hebrew_work="Ebr530_LUK_Hebrew",
    translation_work="Ebr530_LUK_Gordon",
    title="Luke (Vatican, Vat. ebr. 530)",
    translation_title="English Translation of Luke (Vatican, Vat. ebr. 530)",
    description=(
        "Hebrew transcription and English translation of Luke from "
        "Biblioteca Apostolica Vaticana, Vat. ebr. 530, part 1, fragment 11, "
        "folios 1r–2v, transcribed, translated and annotated by Nehemia "
        "Gordon."
    ),
    descriptions=(
        (
            "x-contents",
            "Part 1, fragment 11 of a composite volume of fragments. Folios "
            "1r–2v carry Luke 1:1–35 and John 1:1–13 in Hebrew, each "
            "with a heading and a chapter heading.",
        ),
        (
            "x-script",
            "Fully pointed Hebrew. The pointing is irregular by Tiberian "
            "standards: dagesh is often omitted where expected, and kamatz "
            "and patach — like tsere and segol — are used "
            "interchangeably, which the editor relates to the Sephardic "
            "pronunciation and to Palestinian pointing (Nikud Eretz-Yisraeli).",
        ),
        (
            "x-provenance",
            "Held by the Biblioteca Apostolica Vaticana and published through "
            "its digitisation programme on DigiVatLib.",
        ),
        (
            "x-editorial",
            "The editor notes that a scribe scratched out Adonai and wrote "
            "Yehovah in its place, and records variant forms attested in "
            "Mishnaic manuscripts and in the Bar Ilan Responsa Database.",
        ),
    ),
    sources=(
        "Shelfmark, extent and repository from the manuscript's record in "
        "DigiVatLib, https://digi.vatlib.it/view/MSS_Vat.ebr.530.pt.1. "
        "Codicological detail is catalogued by Umberto Cassuto, 'Codices "
        "Vaticani Hebraici' — cited here, not consulted.",
        "Text, translation and annotation from Nehemia Gordon, 'Hebrew "
        "Gospels of Luke and John found in the Vatican Library', version 3.9 "
        "(2018), nehemiaswall.com.",
    ),
    coverage="Luke 1:1–35",
    date_calendar="Gregorian",
    original_date="undated",
    edition_date="2018",
    publisher="Nehemia Gordon",
    translator="Nehemia Gordon",
    contributor="Nehemia Gordon",
    contributor_file_as="Gordon, Nehemia",
    rights="© 2018 Nehemia Gordon.",
    license="All rights reserved.",
    expected_hebrew_prefix="בִהְיוֹת",
    extractor="ebr530",
    footer_top=701.0,
    column_split=306.0,
)

EBR530_JOHN = BookProfile(
    key="ebr530_john",
    name="John",
    osis_book="John",
    osis_book_name="John",
    scope="John",
    stem="John_Ebr530",
    default_pdf=(
        "Hebrew-Gospels-of-Luke-and-John-from-the-Vatican_"
        "Biblioteca Apostolica ebr. 530.pdf"
    ),
    first_page=1,
    last_page=13,
    header_y1=60,
    footer_y0=701,
    expected_first=(1, "1"),
    expected_last=(1, '13'),
    expected_chapters=1,
    expected_verses=13,
    manuscript=(
        "Biblioteca Apostolica Vaticana, Vat. ebr. 530, part 1, fragment 11, "
        "folios 1r–2v"
    ),
    alt_namespace="https://digi.vatlib.it/view/MSS_Vat.ebr.530.pt.1",
    hebrew_work="Ebr530_JOH_Hebrew",
    translation_work="Ebr530_JOH_Gordon",
    title="John (Vatican, Vat. ebr. 530)",
    translation_title="English Translation of John (Vatican, Vat. ebr. 530)",
    description=(
        "Hebrew transcription and English translation of John from "
        "Biblioteca Apostolica Vaticana, Vat. ebr. 530, part 1, fragment 11, "
        "folios 1r–2v, transcribed, translated and annotated by Nehemia "
        "Gordon."
    ),
    descriptions=(
        (
            "x-contents",
            "Part 1, fragment 11 of a composite volume of fragments. Folios "
            "1r–2v carry Luke 1:1–35 and John 1:1–13 in Hebrew, each "
            "with a heading and a chapter heading.",
        ),
        (
            "x-script",
            "Fully pointed Hebrew. The pointing is irregular by Tiberian "
            "standards: dagesh is often omitted where expected, and kamatz "
            "and patach — like tsere and segol — are used "
            "interchangeably, which the editor relates to the Sephardic "
            "pronunciation and to Palestinian pointing (Nikud Eretz-Yisraeli).",
        ),
        (
            "x-provenance",
            "Held by the Biblioteca Apostolica Vaticana and published through "
            "its digitisation programme on DigiVatLib.",
        ),
        (
            "x-editorial",
            "The editor notes that a scribe scratched out Adonai and wrote "
            "Yehovah in its place, and records variant forms attested in "
            "Mishnaic manuscripts and in the Bar Ilan Responsa Database.",
        ),
    ),
    sources=(
        "Shelfmark, extent and repository from the manuscript's record in "
        "DigiVatLib, https://digi.vatlib.it/view/MSS_Vat.ebr.530.pt.1. "
        "Codicological detail is catalogued by Umberto Cassuto, 'Codices "
        "Vaticani Hebraici' — cited here, not consulted.",
        "Text, translation and annotation from Nehemia Gordon, 'Hebrew "
        "Gospels of Luke and John found in the Vatican Library', version 3.9 "
        "(2018), nehemiaswall.com.",
    ),
    coverage="John 1:1–13",
    date_calendar="Gregorian",
    original_date="undated",
    edition_date="2018",
    publisher="Nehemia Gordon",
    translator="Nehemia Gordon",
    contributor="Nehemia Gordon",
    contributor_file_as="Gordon, Nehemia",
    rights="© 2018 Nehemia Gordon.",
    license="All rights reserved.",
    expected_hebrew_prefix="בְרֵאשִׁית",
    extractor="ebr530",
    footer_top=701.0,
    column_split=306.0,
)

MAT = BookProfile(
    key="mat",
    name="Matthew",
    osis_book="Matt",
    osis_book_name="Matthew",
    scope="Matt",
    stem="Matt_CochinOo.1.32",
    # A directory, not a file: this edition is published a chapter at a time,
    # and each chapter is its own book with its own title page, copyright page
    # and introduction. The chapters cover Matthew 1–25 so far; the edition is
    # still being written, and when chapter 26 arrives `expected_last`,
    # `expected_chapters` and `expected_verses` below all need raising.
    # `validate_records` fails loudly until they are, which is the point.
    default_pdf="MS_Cochin_Oo.1.32_Mat_PTM",
    part_pattern=r"Chapter[-_ ]?(?P<chapter>\d+)",
    # Unused: each part carries its own front matter of a different length, so
    # the body start is found per file rather than fixed here. See
    # pdf2osis.cochin._mat_page.
    first_page=0,
    last_page=0,
    # Matthew carries no running header; its verse headers start as high as
    # y=33, so clipping the top of the page would drop them.
    header_y1=0,
    footer_y0=728,
    expected_first=(1, "1"),
    expected_last=(25, "46"),
    expected_chapters=25,
    expected_verses=910,
    manuscript="MS.Oo.1.32",
    alt_namespace="https://projecttruthministries.org/studies/cochin-matthew/",
    hebrew_work="CochinOo.1.32_MAT_Hebrew",
    translation_work="CochinOo.1.32_MAT_PTM",
    title="Matthew (Cochin MS Oo.1.32)",
    translation_title="Translation of Matthew (Cochin MS Oo.1.32)",
    description=(
        "The Cochin Hebrew New Testament manuscripts are significant "
        "18th-century Hebrew versions of the New Testament. This file "
        "encodes Matthew from Cambridge MS Oo.1.32."
    ),
    descriptions=(
        (
            "x-contents",
            "Matthew 1:1–25:46. The edition is published a chapter at a time "
            "and has reached chapter 25; the remaining chapters are not out "
            "yet. Chapter 17:23 and 17:24 are numbered as the edition prints "
            "them, with the manuscript's own 17:22b and 17:23 recorded beside "
            "them.",
        ),
        (
            "x-script",
            "Essentially unpointed Hebrew, with gershayim marking divine names "
            "and abbreviations.",
        ),
        (
            "x-editorial",
            "Each verse is set with the Hebrew transcription, an English "
            "translation, The Scriptures 2009 for comparison, a Syriac Aramaic "
            "witness with its own English rendering, and an interlinear gloss "
            "table.",
        ),
        (
            "x-apparatus",
            "Each chapter is published separately and numbers its footnotes "
            "from one, so the notes are renumbered into a single sequence as "
            "the chapters are joined. A note's number here is its place in the "
            "whole book, not the number printed in that chapter's own volume.",
        ),
    ),
    sources=(
        "Text, translation and commentary from Janice F. Baca, 'The Cochin "
        "Hebrew Book of Matthew' (Project Truth Ministries, 2025–2026), "
        "published a chapter at a time.",
    ),
    coverage="Matthew 1:1–25:46",
    original_date="ca. 1730",
    edition_date="2026",
    rights="© copyright 2025 Janice F. Baca",
    # See REV — confirmed directly, the same publisher and terms.
    license="All Rights Reserved",
    expected_hebrew_prefix="ספר הלידה",
    cochin_book="mat",
)

# The 27 NT books in canonical order, as OSIS abbreviations — shared by both
# whole-Testament profiles below. Chapter/verse counts are never duplicated
# here; each source's own extractor reads them from the source itself.
_NT_BOOK_ORDER = (
    "Matt", "Mark", "Luke", "John", "Acts", "Rom", "1Cor", "2Cor", "Gal",
    "Eph", "Phil", "Col", "1Thess", "2Thess", "1Tim", "2Tim", "Titus", "Phlm",
    "Heb", "Jas", "1Pet", "2Pet", "1John", "2John", "3John", "Jude", "Rev",
)

DELITZSCH = BookProfile(
    key="delitzsch",
    name="New Testament",
    # No single book applies to a whole-Testament source; the OSIS builder
    # reads expected_book_order instead. Kept non-empty because it is a
    # required field, and used nowhere a multi-book document is involved.
    osis_book="",
    scope="NT",
    stem="NT_Delitzsch",
    # Not a PDF: the CrossWire SWORD module zip, read by pdf2osis.sword.
    default_pdf="sword/HebDelitzsch.zip",
    first_page=0,
    last_page=0,
    header_y1=0,
    footer_y0=0,
    expected_first=(1, "1"),
    expected_last=(22, "21"),
    expected_chapters=0,
    # Total verses across all 27 NT books under the module's own NRSV
    # versification — confirmed by summing the module's declared chapter
    # lengths, not assumed.
    expected_verses=7959,
    manuscript="Delitzsch Hebrew New Testament (Streams in the Negev transcription)",
    alt_namespace="https://github.com/HebrewNewTestament/HebDelitzsch",
    hebrew_work="Delitzsch_NT_Hebrew",
    # No accompanying English text exists for this source; see has_translation.
    translation_work="Delitzsch_NT_NoTranslation",
    title="New Testament (Delitzsch Hebrew New Testament)",
    translation_title="(No English translation is included in this edition.)",
    description=(
        "Franz Delitzsch's Hebrew translation of the whole New Testament, "
        "read from the CrossWire SWORD module 'HebDelitzsch', a fully "
        "pointed digital transcription and re-pointing by Streams in the "
        "Negev (2003)."
    ),
    descriptions=(
        (
            "x-contents",
            "A Hebrew translation of the whole New Testament from Greek, all "
            "27 books in one file. Verse division follows the module's own "
            "NRSV versification.",
        ),
        (
            "x-provenance",
            "Delitzsch (1813-1890) first published his Hebrew New Testament "
            "in 1877 and revised it through several editions; this digital "
            "text is based on the 1885 edition. Streams in the Negev "
            "transcribed and re-pointed it in 2003, distributed since as the "
            "CrossWire SWORD module 'HebDelitzsch'.",
        ),
        (
            "x-editorial",
            "Fully pointed with niqqud and cantillation. No English text "
            "accompanies this translation. A handful of NRSV-versification "
            "verse slots the module leaves empty — 2 Cor 13:14, 3 John 1:15, "
            "Rev 12:18 — are kept, numbered, as the module has them.",
        ),
    ),
    sources=(
        "Text from the CrossWire SWORD module 'HebDelitzsch' (version 1.2.1, "
        "2022-08-05), https://www.crosswire.org/sword/modules/ModDisp.jsp"
        "?modType=Bibles&modName=Delitzsch.",
        "Underlying transcription and pointing by Streams in the Negev "
        "(2003), https://github.com/HebrewNewTestament/HebDelitzsch.",
    ),
    coverage="Matthew 1:1–Revelation 22:21",
    date_calendar="Gregorian",
    original_date="1885",
    edition_date="2003",
    publisher="Streams in the Negev",
    translator="Franz Delitzsch",
    contributor="Streams in the Negev",
    contributor_file_as="Streams in the Negev",
    rights="Copyright 2003 (Streams in the Negev).",
    # The module's own DistributionLicense is "Copyrighted; permission to
    # distribute granted to CrossWire"; STEPBible states the plainer term
    # under which CrossWire in turn makes it available.
    license="Free for use by any non-commercial project.",
    expected_hebrew_prefix="סֵפֶר תּוֹלְדֹת יֵשׁוּעַ",
    extractor="sword",
    has_translation=False,
    sword_module="HebDelitzsch",
    expected_book_order=_NT_BOOK_ORDER,
)

BSI_HNT = BookProfile(
    key="bsi_hnt",
    name="New Testament",
    # No single book applies to a whole-Testament source; see DELITZSCH.
    osis_book="",
    scope="NT",
    stem="NT_BSI_HaBritHaChadasha",
    # Not a PDF and not downloaded as one file: the local JSON cache
    # pdf2osis.bsi_hnt.fetch_bsi_nt writes by scraping nocr.net, since the
    # Bible Society in Israel publishes no digital edition of its own.
    default_pdf="bsi_hnt/cache.json",
    first_page=0,
    last_page=0,
    header_y1=0,
    footer_y0=0,
    expected_first=(1, "1"),
    expected_last=(22, "21"),
    expected_chapters=0,
    # Verified by the actual scrape (pdf2osis.bsi_hnt.fetch_bsi_nt), not
    # assumed. It happens to equal Delitzsch's total exactly — both follow
    # the same NRSV-style versification — but that was confirmed, not relied
    # on going in; this translation's own paragraphing could have combined or
    # split verses differently.
    expected_verses=7959,
    manuscript=(
        "HaBrit HaChadasha (Bible Society in Israel, 1995, revised 2010)"
    ),
    alt_namespace="https://nocr.net/hbm/hebrew/hebmht/index.php",
    hebrew_work="BSI_NT_Hebrew",
    # No accompanying English text exists for this source; see has_translation.
    translation_work="BSI_NT_NoTranslation",
    title="New Testament (HaBrit HaChadasha, Bible Society in Israel)",
    translation_title="(No English translation is included in this edition.)",
    description=(
        "The Bible Society in Israel's modern Hebrew translation of the New "
        "Testament, HaBrit HaChadasha (1995, revised 2010), read from its "
        "nocr.net mirror — the publisher has no digital edition of its own."
    ),
    descriptions=(
        (
            "x-contents",
            "A modern Hebrew translation of the whole New Testament, all 27 "
            "books in one file. Verse division follows the source as "
            "printed; it need not match another translation's versification "
            "at every disputed verse.",
        ),
        (
            "x-provenance",
            "Published by the Bible Society in Israel in 1995 and revised in "
            "2010. No copy of the text exists on the publisher's own site; "
            "this was read from nocr.net, a third-party mirror that displays "
            "it chapter by chapter with the publisher's copyright notice "
            "attached.",
        ),
        (
            "x-editorial",
            "Fully pointed with niqqud, though without cantillation marks. "
            "No English text accompanies this translation.",
        ),
    ),
    sources=(
        "Text scraped from https://nocr.net/hbm/hebrew/hebmht/index.php, "
        "chapter by chapter, by pdf2osis.bsi_hnt.",
    ),
    coverage="Matthew 1:1–Revelation 22:21",
    date_calendar="Gregorian",
    original_date="1995",
    edition_date="2010",
    publisher="The Bible Society in Israel",
    # Delitzsch's translator/contributor fields name real people; there is no
    # named translator for this edition, only its publisher.
    translator="The Bible Society in Israel",
    contributor="The Bible Society in Israel",
    contributor_file_as="Bible Society in Israel, The",
    rights="Copyrighted (c) 1995, revised (c) 2010 by The Bible Society in Israel.",
    # No license is granted at all — not even Delitzsch's restrictive
    # "non-commercial" permission. This states the source's own notice
    # verbatim, not the repository's CC BY-NC-SA default; see tools/README.md
    # for why this output stays local, never committed or redistributed,
    # absent direct permission from the publisher.
    license=(
        "No reuse or redistribution permission is stated anywhere by the "
        "publisher; this edition is for local, personal use only."
    ),
    expected_hebrew_prefix="סֵפֶר הַיּוּחֲסִין שֶׁל יֵשׁוּעַ",
    extractor="bsi_hnt",
    has_translation=False,
    expected_book_order=_NT_BOOK_ORDER,
)

BOOK_PROFILES = {
    "rev": REV,
    "jas": JAS,
    "mat": MAT,
    "sloane_rev": SLOANE_REV,
    "ebr530_luke": EBR530_LUKE,
    "ebr530_john": EBR530_JOHN,
    "delitzsch": DELITZSCH,
    "bsi_hnt": BSI_HNT,
}


def get_profile(key: str) -> BookProfile:
    try:
        return BOOK_PROFILES[key.lower()]
    except KeyError as exc:
        valid = ", ".join(sorted(BOOK_PROFILES))
        raise ValueError(f"Unknown book {key!r}; expected one of: {valid}") from exc
