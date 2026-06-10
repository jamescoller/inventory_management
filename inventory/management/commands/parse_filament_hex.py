"""Parse ``filament_hex/*.pdf`` into a color->hex **review CSV** — no DB writes.

Phase 17.2. Reads the text Hex Code Table PDFs with the dev-only ``pypdf`` lib (via
:mod:`inventory.filament_hex`) and writes one row per color to a gitignored
``filament_review/`` directory for James to eyeball **before** any load into
``Filament.hex_code`` / ``color_family``. Never touches the database. The 16
screenshot PNGs in that folder need a separate vision pass and are not parsed here.
"""

import csv
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from inventory.filament_hex import CSV_FIELDS, parse_hex_dir

DEFAULT_HEX_DIR = "filament_hex"
DEFAULT_OUT_DIR = "filament_review"
DEFAULT_OUT_NAME = "filament-hex-review.csv"


class Command(BaseCommand):
    help = (
        "Parse filament_hex/*.pdf (text Hex Code Tables) into a color->hex review "
        "CSV. Writes ONLY to a gitignored review directory; it never modifies the "
        "database. The 16 screenshot PNGs need a separate vision pass."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--hex-dir",
            default=None,
            help=f"Directory of hex PDFs (default: <BASE_DIR>/{DEFAULT_HEX_DIR}).",
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
        hex_dir = options["hex_dir"] or os.path.join(base_dir, DEFAULT_HEX_DIR)
        out_path = options["out"] or os.path.join(
            base_dir, DEFAULT_OUT_DIR, DEFAULT_OUT_NAME
        )

        if not os.path.isdir(hex_dir):
            raise CommandError(f"Hex directory not found: {hex_dir}")

        rows, errors = parse_hex_dir(hex_dir)

        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for row in rows:
                writer.writerow(row.as_csv_dict())

        self.stdout.write(
            self.style.SUCCESS(f"Parsed {len(rows)} colors from PDFs -> {out_path}.")
        )
        if errors:
            self.stdout.write(self.style.WARNING(f"{len(errors)} file(s) failed:"))
            for fname, msg in errors:
                self.stdout.write(f"  - {fname}: {msg}")
        self.stdout.write(
            "Note: the 16 screenshot PNGs in filament_hex/ still need a vision pass."
        )
