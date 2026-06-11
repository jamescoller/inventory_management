"""Backfill ``Filament.manufacturer`` from each spool's linked ``material.mfr``.

Existing rows predate the per-product manufacturer field; for the install this
ships to that means the whole catalog is effectively Bambu Lab (``Material.mfr``
defaults to "Bambu Lab"). Copying ``material.mfr`` onto blank rows labels that
existing stock so the new summary group-by and search filter have data to work
with from day one. The shared helper only touches rows where ``manufacturer`` is
still blank, so any value set by hand before this runs is preserved. Reverse is a
no-op: we never want to wipe a manufacturer the user may have since edited.
"""

from django.db import migrations

from . import _mfr_backfill_helper


def backfill_manufacturer(apps, schema_editor):
    Filament = apps.get_model("inventory", "Filament")
    _mfr_backfill_helper(Filament)


def noop_reverse(apps, schema_editor):
    # Intentional no-op: reversing should not blank out manufacturers.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0035_filament_manufacturer"),
    ]

    operations = [
        migrations.RunPython(backfill_manufacturer, noop_reverse),
    ]
