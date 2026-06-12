"""Backfill Filament hex codes from docs/filament-colors.csv (human-gated)."""

import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from inventory.hex_loader import load_filament_hex

DEFAULT_CSV = "docs/filament-colors.csv"


class Command(BaseCommand):
    help = "Backfill Filament.hex_code/hex_code_2 from the merged color CSV (blank-only by default)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            default=None,
            help=f"CSV path (default <BASE_DIR>/{DEFAULT_CSV}).",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Overwrite spools that already have a hex.",
        )

    def handle(self, *args, **options):
        path = options["csv"] or os.path.join(str(settings.BASE_DIR), DEFAULT_CSV)
        if not os.path.isfile(path):
            raise CommandError(f"CSV not found: {path}")
        stats = load_filament_hex(path, overwrite=options["overwrite"])
        self.stdout.write(
            self.style.SUCCESS(
                f"filled={stats['filled']} skipped_set={stats['skipped_set']} "
                f"unmatched={len(stats['unmatched'])}"
            )
        )
        for name in stats["unmatched"]:
            self.stdout.write(f"  unmatched: {name}")
