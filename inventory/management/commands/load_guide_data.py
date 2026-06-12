"""Load docs/filament-guide-data.csv into Material guide fields (human-gated)."""

import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from inventory.guide_data import load_guide_data

DEFAULT_CSV = "docs/filament-guide-data.csv"


class Command(BaseCommand):
    help = (
        "Load the filament-guide property matrix CSV into Material rows (idempotent)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            default=None,
            help=f"CSV path (default <BASE_DIR>/{DEFAULT_CSV}).",
        )
        parser.add_argument(
            "--fill-blank-only",
            action="store_true",
            help="Only fill blank/False fields instead of overwriting.",
        )

    def handle(self, *args, **options):
        path = options["csv"] or os.path.join(str(settings.BASE_DIR), DEFAULT_CSV)
        if not os.path.isfile(path):
            raise CommandError(f"CSV not found: {path}")
        stats = load_guide_data(path, overwrite=not options["fill_blank_only"])
        self.stdout.write(
            self.style.SUCCESS(
                f"created={stats['created']} updated={stats['updated']} "
                f"unchanged={stats['unchanged']}"
            )
        )
        for name, msg in stats["errors"]:
            self.stdout.write(self.style.WARNING(f"  - {name}: {msg}"))
