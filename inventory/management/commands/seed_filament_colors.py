"""Seed the FilamentColor catalog from docs/filament-colors.csv (human-gated)."""

import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from inventory.color_catalog import seed_filament_colors

DEFAULT_CSV = "docs/filament-colors.csv"


class Command(BaseCommand):
    help = "Seed/refresh the FilamentColor catalog from the color CSV (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv", default=None, help=f"CSV path (default {DEFAULT_CSV})."
        )
        parser.add_argument(
            "--manufacturer",
            default="Bambu Lab",
            help="Default brand when the CSV row has no manufacturer column.",
        )

    def handle(self, *args, **options):
        path = options["csv"] or os.path.join(str(settings.BASE_DIR), DEFAULT_CSV)
        if not os.path.isfile(path):
            raise CommandError(f"CSV not found: {path}")
        stats = seed_filament_colors(path, default_manufacturer=options["manufacturer"])
        self.stdout.write(
            self.style.SUCCESS(
                f"created={stats['created']} updated={stats['updated']} "
                f"unchanged={stats['unchanged']} no_material={len(stats['no_material'])}"
            )
        )
        for name in stats["no_material"]:
            self.stdout.write(f"  no Material row: {name}")
