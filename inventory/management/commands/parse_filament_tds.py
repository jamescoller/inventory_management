"""Parse the committed Technical Data Sheets into a **review CSV** — no DB writes.

Phase 17.1. Reads ``filament_TDS/*.pdf`` with the dev-only ``pypdf`` lib (via
:mod:`inventory.filament_tds`) and writes one CSV row per sheet to a gitignored
``filament_review/`` directory for James to eyeball **before** any load. This
command deliberately never touches the ``Material`` table — backfilling existing
rows is a separate, human-gated step (see ``--help`` of a future loader command).
"""

import csv
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from inventory.filament_tds import CSV_FIELDS, parse_tds_dir

DEFAULT_TDS_DIR = "filament_TDS"
DEFAULT_OUT_DIR = "filament_review"
DEFAULT_OUT_NAME = "filament-tds-review.csv"


class Command(BaseCommand):
    help = (
        "Parse filament_TDS/*.pdf into a review CSV (drying temp/time, build-plate "
        "and hot-end compatibility, print-temp range). Writes ONLY to a gitignored "
        "review directory — it never modifies the database. A human verifies the "
        "CSV before any load step."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--tds-dir",
            default=None,
            help=f"Directory of TDS PDFs (default: <BASE_DIR>/{DEFAULT_TDS_DIR}).",
        )
        parser.add_argument(
            "--out",
            default=None,
            help=(
                "Output CSV path (default: "
                f"<BASE_DIR>/{DEFAULT_OUT_DIR}/{DEFAULT_OUT_NAME})."
            ),
        )

    def handle(self, *args, **options):
        base_dir = str(settings.BASE_DIR)
        tds_dir = options["tds_dir"] or os.path.join(base_dir, DEFAULT_TDS_DIR)
        out_path = options["out"] or os.path.join(
            base_dir, DEFAULT_OUT_DIR, DEFAULT_OUT_NAME
        )

        if not os.path.isdir(tds_dir):
            raise CommandError(f"TDS directory not found: {tds_dir}")

        report = parse_tds_dir(tds_dir)

        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for row in report.rows:
                writer.writerow(row.as_csv_dict())

        n = len(report.rows)
        blanks = sum(1 for r in report.rows if r.dry_temp_ideal_degC is None)
        self.stdout.write(
            self.style.SUCCESS(
                f"Parsed {n} TDS file(s) -> {out_path}. "
                f"{n - blanks} had drying data, {blanks} need manual review."
            )
        )
        if report.errors:
            self.stdout.write(
                self.style.WARNING(f"{len(report.errors)} file(s) failed to parse:")
            )
            for fname, msg in report.errors:
                self.stdout.write(f"  - {fname}: {msg}")

        self.stdout.write(
            "No database rows were created or modified. Review the CSV, then run "
            "the (human-gated) loader to backfill Material."
        )
