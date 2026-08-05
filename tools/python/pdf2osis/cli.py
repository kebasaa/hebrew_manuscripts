from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from .converter import (
    ConversionError,
    ConversionReport,
    convert_bsi_nt,
    convert_pdf,
    convert_sword_nt,
)
from .profiles import BOOK_PROFILES, get_profile

_CONVERTERS = {"sword": convert_sword_nt, "bsi_hnt": convert_bsi_nt}

# tools/python/pdf2osis/cli.py -> tools/python -> tools -> the repository.
# Defaulting to paths inside this repository is safe in a way that defaulting
# across a repository boundary is not: this package ships with the corpus it
# converts, so the two move together.
_REPOSITORY = Path(__file__).resolve().parents[3]
#: Where the source PDFs, SWORD module and scrape cache live.
DEFAULT_SOURCE_DIR = _REPOSITORY / "tools" / "data" / "00_source_files"
#: The published corpus. Conversion writes here directly, so there is no second
#: copy of any text to fall out of step with the one people actually download.
DEFAULT_OUTPUT_DIR = _REPOSITORY / "manuscripts"


def _convert(profile, input_path, output_dir) -> ConversionReport:
    convert = _CONVERTERS.get(profile.extractor, convert_pdf)
    return convert(input_path, profile, output_dir)


def _report(report: ConversionReport) -> None:
    data = asdict(report)
    data["input_path"] = str(report.input_path)
    data["output_paths"] = {
        key: str(value)
        for key, value in report.output_paths.items()
    }
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdf2osis",
        description="Convert Hebrew manuscript PDFs to OSIS.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    convert = subparsers.add_parser("convert", help="convert one source")
    convert.add_argument("--book", choices=sorted(BOOK_PROFILES), required=True)
    convert.add_argument(
        "--input",
        type=Path,
        help="the source file, or directory for an edition published in "
        "parts; defaults to this book's own source under --source-dir",
    )
    convert.add_argument(
        "--source-dir", type=Path, default=DEFAULT_SOURCE_DIR
    )
    convert.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR
    )

    convert_all = subparsers.add_parser(
        "convert-all",
        help="convert every source in the corpus",
    )
    convert_all.add_argument(
        "--source-dir", type=Path, default=DEFAULT_SOURCE_DIR
    )
    convert_all.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "convert":
            profile = get_profile(args.book)
            source = args.input or profile.default_path(args.source_dir)
            report = _convert(profile, source, args.output_dir)
            _report(report)
        else:
            for profile in BOOK_PROFILES.values():
                report = _convert(
                    profile,
                    profile.default_path(args.source_dir),
                    args.output_dir,
                )
                _report(report)
    except (ConversionError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0
