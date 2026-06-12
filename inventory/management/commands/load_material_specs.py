"""Load docs/filament-tds-specs.csv (TDS drying temp/time) into Material rows (human-gated)."""

import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from inventory.material_specs import load_material_specs

DEFAULT_CSV = "docs/filament-tds-specs.csv"


class Command(BaseCommand):
    help = "Load TDS drying temp/time into Material rows (idempotent, blank-only by default)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv", default=None, help=f"CSV path (default <BASE_DIR>/{DEFAULT_CSV})."
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Overwrite already-set drying specs.",
        )

    def handle(self, *args, **options):
        path = options["csv"] or os.path.join(str(settings.BASE_DIR), DEFAULT_CSV)
        if not os.path.isfile(path):
            raise CommandError(f"CSV not found: {path}")
        stats = load_material_specs(path, overwrite=options["overwrite"])
        self.stdout.write(
            self.style.SUCCESS(
                f"updated={stats['updated']} unchanged={stats['unchanged']} "
                f"unmatched={len(stats['unmatched'])}"
            )
        )
        for name in stats["unmatched"]:
            self.stdout.write(f"  unmatched: {name}")
        for name, msg in stats["errors"]:
            self.stdout.write(self.style.WARNING(f"  - {name}: {msg}"))
