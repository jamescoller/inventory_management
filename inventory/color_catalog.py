"""Seed the :class:`FilamentColor` catalog from ``docs/filament-colors.csv``.

Idempotent ``get_or_create`` keyed on
``(manufacturer, material_name, material_type, color_name)``. The CSV has no
``manufacturer`` column today (all Bambu); a missing/blank value defaults to
``Bambu Lab``. Human-gated: run ``seed_filament_colors`` on prod after review.
"""

import csv

from django.utils.text import slugify

from inventory.models import Filament, FilamentColor, Material


def group_slug(manufacturer, material_name, material_type):
    """Stable URL slug for a sheet group, e.g. 'bambu-lab-pla-matte'."""
    return slugify(f"{manufacturer} {material_name} {material_type}")


def _norm_hex(value):
    """Canonicalize a hex value the way ``FilamentColor.save`` will store it.

    ``FilamentColor.save`` lowercases the hex via ``Filament._norm_hex``, so the
    loader must compare against the same canonical form — otherwise an
    uppercase-hex CSV (which is what ``docs/filament-colors.csv`` uses) would
    look "changed" on every run and idempotency would break.
    """
    if not value:
        return value
    return Filament._norm_hex(value) or value


def _resolve_material(material_name, material_type):
    return Material.objects.filter(
        name__iexact=material_name, material_type__iexact=material_type
    ).first()


def seed_filament_colors(csv_path, *, default_manufacturer="Bambu Lab"):
    stats = {"created": 0, "updated": 0, "unchanged": 0, "no_material": []}
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            material_name = (row.get("material") or "").strip()
            material_type = (row.get("material_type") or "").strip()
            color_name = (row.get("color_name") or "").strip()
            hex_code = (row.get("hex_code") or "").strip()
            if not material_name or not color_name or not hex_code:
                continue
            hex_code = _norm_hex(hex_code)
            manufacturer = (
                row.get("manufacturer") or ""
            ).strip() or default_manufacturer
            hex2 = _norm_hex((row.get("hex_code_2") or "").strip())
            source = (row.get("source_file") or row.get("notes") or "").strip()
            material = _resolve_material(material_name, material_type)
            if material is None:
                stats["no_material"].append(
                    f"{manufacturer} {material_name} {material_type} {color_name}".strip()
                )

            obj, created = FilamentColor.objects.get_or_create(
                manufacturer=manufacturer,
                material_name=material_name,
                material_type=material_type,
                color_name=color_name,
                defaults={
                    "hex_code": hex_code,
                    "hex_code_2": hex2,
                    "material": material,
                    "source": source,
                },
            )
            if created:
                stats["created"] += 1
                continue
            changed = False
            for field, value in (
                ("hex_code", hex_code),
                ("hex_code_2", hex2),
                ("material", material),
                ("source", source),
            ):
                if getattr(obj, field) != value:
                    setattr(obj, field, value)
                    changed = True
            if changed:
                obj.save()
                stats["updated"] += 1
            else:
                stats["unchanged"] += 1
    return stats
