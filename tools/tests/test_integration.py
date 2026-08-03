from __future__ import annotations

from pathlib import Path
import re

from lxml import etree
import pytest

from pdf2osis.converter import convert_pdf
from pdf2osis.cochin import extract_cochin
from pdf2osis.osis import OSIS_NS
from pdf2osis.profiles import JAS, MAT, REV

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "00_source_files"


@pytest.mark.parametrize(
    ("profile", "filename", "count", "chapters"),
    [
        # 405. Revelation 2:26 and 20:12 are in the source but their headers are
        # not set at the usual size, so a size-keyed search missed them, giving
        # 404; both were verified against the rendered pages. Against that, the
        # second "Revelation 2:21" header is a signpost carrying the notice that
        # the manuscript transposes 2:21 and 2:22, not a verse, and counting it
        # gave 406.
        (REV, REV.default_pdf, 405, 22),
        (JAS, JAS.default_pdf, 107, 5),
        (MAT, MAT.default_pdf, 646, 19),
    ],
)
def test_full_pdf_record_coverage(
    profile,
    filename: str,
    count: int,
    chapters: int,
) -> None:
    document = extract_cochin(SOURCE / filename, profile)
    records, definitions = document.records, document.notes
    anomalies = document.anomalies
    assert len(records) == count
    assert len({record.chapter for record in records}) == chapters
    assert records[0].hebrew.startswith(profile.expected_hebrew_prefix)
    assert definitions
    assert all(
        marker.number in definitions
        for record in records
        for marker in record.hebrew_markers + record.english_markers
        if marker.number in record.notes
    )
    assert not any("markers without definitions" in item for item in anomalies)
    assert not any(re.search(r"[A-Za-z]", record.hebrew) for record in records)


def test_james_source_specific_structure() -> None:
    records = extract_cochin(SOURCE / JAS.default_pdf, JAS).records
    by_id = {(record.chapter, record.verse): record for record in records}
    assert by_id[(1, "21")].empty
    assert by_id[(2, "15")].alt_verse == "15-16"
    # The PDF combines KJV 2:15-16 and consequently has 25 source records
    # in chapter 2. Inventing or duplicating a Jas.2.26 record would alter it.
    assert (2, "26") not in by_id
    assert "The Covenant with Yehovah" not in by_id[(5, "20")].english


def test_revelation_source_specific_structure() -> None:
    document = extract_cochin(SOURCE / REV.default_pdf, REV)
    records, definitions = document.records, document.notes
    anomalies = document.anomalies
    by_id = {(record.chapter, record.verse): record for record in records}
    assert by_id[(14, "19")].source_verse == "19-20"
    assert by_id[(14, "19")].hebrew
    assert by_id[(14, "19")].english
    assert by_id[(22, "21")].english.startswith("May the grace")
    assert "Pa’al/Qal" not in by_id[(1, "1")].english
    assert by_id[(1, "1")].english.endswith("John.")
    assert not re.search(r"[A-Za-z]", by_id[(1, "1")].hebrew)
    assert by_id[(1, "6")].hebrew.startswith(
        "ועשה אותנו למלכים ולכהנים לפני ה֞"
    )
    assert {
        marker.number for marker in by_id[(1, "1")].hebrew_markers
    } == {"18", "19", "22", "23"}
    assert {
        marker.number for marker in by_id[(1, "1")].english_markers
    } == {"20"}
    # The edition subdivides four verses and prints the letters itself, so they
    # survive extraction with their text intact.
    lettered = {
        (r.chapter, r.verse): r for r in records if not r.verse.isdigit()
    }
    assert sorted(lettered) == [(2, "27a"), (2, "27b"), (13, "1a"), (13, "1b")]
    assert all(record.hebrew for record in lettered.values())

    # Revelation 2:21 is one verse, not two. PDF page 50 prints a bare
    # "Revelation 2:21" header whose whole content is an order notice; the verse
    # itself is on page 51 as "Revelation 2:21 (Cochin 2:21)". Counting the
    # signpost split it into a spurious empty 21a and a real 21b.
    twenty_one = [r for r in records if r.chapter == 2 and r.verse.startswith("21")]
    assert [r.verse for r in twenty_one] == ["21"]
    assert twenty_one[0].hebrew.startswith("ואני נתתי לה")
    assert twenty_one[0].alt_verse == "21"
    assert not twenty_one[0].empty
    assert twenty_one[0].order_note == (
        "The Cochin manuscript changes the order of the following verses."
    )
    # The edition follows the manuscript's order, so 2:22 is printed before
    # 2:21. Those two are the only transposition in the whole corpus.
    assert {(r.chapter, r.verse) for r in records if r.reordered} == {
        (2, "22"),
        (2, "21"),
    }
    assert any("out of canonical order" in item for item in anomalies)
    # Footnote 90 is defined in the source but never referenced in the body, so
    # it is reported rather than guessed onto a verse.
    assert definitions["90"].startswith("Pergamum is an older spelling")
    assert not any("90" in record.notes for record in records)
    assert any("footnote 90 is defined but unreferenced" in item for item in anomalies)


def test_conversion_is_deterministic_and_variants_share_coverage(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    report_one = convert_pdf(SOURCE / JAS.default_pdf, JAS, first)
    report_two = convert_pdf(SOURCE / JAS.default_pdf, JAS, second)
    assert report_one.verses == report_two.verses == 107
    namespace = {"osis": OSIS_NS}
    coverages = []
    for variant, name in JAS.output_names().items():
        first_bytes = (first / name).read_bytes()
        second_bytes = (second / name).read_bytes()
        assert first_bytes == second_bytes
        root = etree.fromstring(first_bytes)
        coverages.append(
            root.xpath("//osis:verse/@osisID", namespaces=namespace)
        )
    assert coverages[0] == coverages[1] == coverages[2]


@pytest.mark.parametrize("profile", [REV, JAS, MAT])
def test_cochin_output_is_structurally_first_class(profile, tmp_path: Path) -> None:
    """The Cochin editions use the same OSIS shape as the manuscripts.

    They used to emit container verses, a `footnote` note type that OSIS 2.1.1
    does not define, and an `alt:num` attribute in a private namespace, none of
    which the upstream schema accepts.
    """
    report = convert_pdf(SOURCE / profile.default_pdf, profile, tmp_path)
    namespace = {"osis": OSIS_NS}

    for variant, path in report.output_paths.items():
        payload = path.read_bytes()
        root = etree.fromstring(payload)
        verses = root.xpath("//osis:verse", namespaces=namespace)
        starts = [verse.get("sID") for verse in verses if verse.get("sID")]
        ends = [verse.get("eID") for verse in verses if verse.get("eID")]
        assert starts and starts == ends, (profile.key, variant)
        # Milestone form is all-or-nothing.
        assert not [verse for verse in verses if verse.text], (profile.key, variant)

        for note in root.xpath("//osis:note", namespaces=namespace):
            assert note.get("type") == "explanation"
            assert note.get("osisRef")
            assert note.get("osisID", "").count("!") == 1

        assert not [
            key
            for verse in verses
            for key in verse.attrib
            if key.startswith("{")
        ], f"{profile.key} {variant} carries a private-namespace attribute"

        lines = payload.decode("utf-8").splitlines()
        opening = [line for line in lines if "<verse sID=" in line]
        assert len(opening) == report.verses, (profile.key, variant)
        for line in opening:
            assert line.count("<verse sID=") == 1
            assert "<verse eID=" in line


@pytest.mark.parametrize("profile", [REV, JAS, MAT])
def test_cochin_rights_split_copyright_from_license(
    profile, tmp_path: Path
) -> None:
    """Every Cochin edition: copyright present save on the bare Hebrew, and
    All Rights Reserved on every variant — confirmed directly with Janice F.
    Baca / Project Truth Ministries, not read out of any source PDF."""
    report = convert_pdf(SOURCE / profile.default_pdf, profile, tmp_path)
    namespace = {"osis": OSIS_NS}

    for variant, path in report.output_paths.items():
        root = etree.fromstring(path.read_bytes())
        work = root.xpath("//osis:header/osis:work", namespaces=namespace)[0]

        def rights(kind: str) -> str:
            found = work.xpath(
                f"./osis:rights[@type='x-{kind}']/text()", namespaces=namespace
            )
            return found[0] if found else ""

        if variant == "hebrew":
            assert rights("copyright") == "", (profile.key, variant)
        else:
            assert profile.rights == rights("copyright"), (profile.key, variant)
        assert rights("license") == "All Rights Reserved", (profile.key, variant)


@pytest.mark.parametrize(
    ("profile", "absent"),
    [
        (REV, [(2, "6"), (2, "28"), (9, "9"), (16, "11")]),
        (JAS, [(1, "21")]),
        (MAT, []),
    ],
)
def test_verses_the_edition_says_are_missing_are_empty_but_present(
    profile, absent
) -> None:
    """Absent by design, not by extraction failure — and the source says so."""
    records = extract_cochin(SOURCE / profile.default_pdf, profile).records
    by_id = {(r.chapter, r.verse): r for r in records}
    assert [(r.chapter, r.verse) for r in records if r.empty] == absent
    for key in absent:
        record = by_id[key]
        assert record.hebrew == ""
        assert record.english == ""
        # The edition's own wording, so an empty verse can never be mistaken
        # for one this code failed to read.
        assert record.absence and "does not exist" in record.absence.lower()


def test_a_combined_record_is_not_read_as_an_absent_one() -> None:
    """Revelation 14:19-20 says "verse 20 does not exist" — of verse 20, only.

    The record covers verse 19, which is present, and the old substring match
    flagged the whole record empty on the strength of that phrase.
    """
    records = extract_cochin(SOURCE / REV.default_pdf, REV).records
    record = {(r.chapter, r.verse): r for r in records}[(14, "19")]
    assert not record.empty
    assert record.absence is None
    assert record.hebrew and record.english
    assert record.source_verse == "19-20"


def test_transposed_verses_are_flagged_in_the_osis(tmp_path: Path) -> None:
    report = convert_pdf(SOURCE / REV.default_pdf, REV, tmp_path)
    for variant, path in report.output_paths.items():
        root = etree.fromstring(path.read_bytes())
        flagged = root.xpath(
            "//osis:verse[@type='x-reordered']/@osisID", namespaces={"osis": OSIS_NS}
        )
        # An attribute rather than a note, so it survives into `hebrew`, which
        # carries no apparatus at all.
        assert flagged == ["Rev.2.22", "Rev.2.21"], variant


def test_an_absent_verse_carries_the_edition_s_notice_as_a_note(
    tmp_path: Path,
) -> None:
    report = convert_pdf(SOURCE / REV.default_pdf, REV, tmp_path)
    ns = {"osis": OSIS_NS}
    root = etree.fromstring(report.output_paths["hebrew_commented"].read_bytes())
    note = root.xpath("//osis:note[@osisID='Rev.2.6!note.absent']", namespaces=ns)[0]
    assert note.get("type") == "explanation"
    assert "does not exist" in note.text
    order = root.xpath("//osis:note[@osisID='Rev.2.21!note.order']", namespaces=ns)[0]
    assert "changes the order" in order.text
    # The plain Hebrew variant carries no apparatus, so it has neither note.
    bare = etree.fromstring(report.output_paths["hebrew"].read_bytes())
    assert bare.xpath("//osis:note", namespaces=ns) == []


def test_cochin_records_its_own_versification_on_the_verse(tmp_path: Path) -> None:
    """Revelation 14:19 is one record for two verses, labelled as printed."""
    report = convert_pdf(SOURCE / REV.default_pdf, REV, tmp_path)
    root = etree.fromstring(report.output_paths["hebrew"].read_bytes())
    verse = root.xpath(
        "//osis:verse[@osisID='Rev.14.19']", namespaces={"osis": OSIS_NS}
    )[0]
    assert verse.get("n") == "19-20"
    assert verse.get("subType") == "x-alt-14.19"
