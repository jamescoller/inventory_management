"""Phase 17.4 follow-up: create Material rows for the PLA Tough and PLA Gradient
lines and link the orphaned FilamentColor catalog rows to them.

The 17.2/17.4 color catalog (docs/filament-colors.csv) carries 7 "PLA Tough" and
8 "PLA Gradient" colors, but no Material row existed for those two variants, so
``seed_filament_colors`` left their ``material`` FK null (15 rows). That leaves
their color sheets without enriched header specs. This data migration creates the
two Material rows (PLA-family specs copied from the existing "PLA Basic" row when
present) and links the existing orphan catalog rows. Idempotent and additive — it
self-heals prod with no manual step. ``store_slug`` is left blank (the store link
falls back to search); fill exact Bambu slugs in admin for precise deep links.
"""

from django.db import migrations

VARIANTS = {
    "Tough": "Bambu PLA Tough — a more durable, impact-tolerant PLA variant.",
    "Gradient": "Bambu PLA Basic Gradient — multi-color gradient PLA spools.",
}


def create_and_link(apps, schema_editor):
    Material = apps.get_model("inventory", "Material")
    FilamentColor = apps.get_model("inventory", "FilamentColor")

    basic = Material.objects.filter(name="PLA", material_type="Basic").first()
    common = {
        "mfr": "Bambu Lab",
        "category": "everyday",
        "drying_need": "recommended",
        "ams_capable": True,
        "dry_temp_ideal_degC": getattr(basic, "dry_temp_ideal_degC", None) or 55,
        "dry_time_hrs": getattr(basic, "dry_time_hrs", None) or 8,
        "print_temp_min_degC": getattr(basic, "print_temp_min_degC", None),
        "print_temp_max_degC": getattr(basic, "print_temp_max_degC", None),
        "print_temp_ideal_degC": getattr(basic, "print_temp_ideal_degC", None),
    }
    for material_type, description in VARIANTS.items():
        material, _ = Material.objects.get_or_create(
            name="PLA",
            material_type=material_type,
            defaults={**common, "description": description},
        )
        FilamentColor.objects.filter(
            material_name="PLA", material_type=material_type, material__isnull=True
        ).update(material=material)


def unlink(apps, schema_editor):
    # Reverse: unlink the catalog rows. The Material rows are left in place (they may
    # have accrued data); deleting them is out of scope for the reverse path.
    FilamentColor = apps.get_model("inventory", "FilamentColor")
    Material = apps.get_model("inventory", "Material")
    ids = Material.objects.filter(name="PLA", material_type__in=VARIANTS).values_list(
        "id", flat=True
    )
    FilamentColor.objects.filter(material_id__in=list(ids)).update(material=None)


class Migration(migrations.Migration):
    dependencies = [("inventory", "0040_inventory_item_fts")]

    operations = [migrations.RunPython(create_and_link, unlink)]
