"""Load the validated filament-guide property matrix into ``Material`` rows.

Reads ``docs/filament-guide-data.csv`` (committed; 38 rows). Idempotent
``get_or_create`` keyed on ``(name, material_type)``. Human-gated: run the
``load_guide_data`` management command on prod after reviewing the CSV.
"""

import csv

from inventory.models import Material

BOOL_FIELDS = [
    "uv_resistant",
    "flexible",
    "high_strength",
    "heat_resistant",
    "easy_to_print",
    "budget_friendly",
    "impact_resistant",
    "requires_enclosure",
]


def _as_bool(value):
    return str(value).strip().lower() in ("1", "true", "yes", "y", "x")


def load_guide_data(csv_path, *, overwrite=True):
    """Apply the guide CSV to Material rows. Returns a counts dict.

    ``overwrite=True`` (default) sets every column from the CSV — it is the
    authoritative source. ``overwrite=False`` only fills blank/False fields.

    Category values are normalised to lowercase to match the model's
    TextChoices (the CSV uses uppercase e.g. EVERYDAY → everyday).
    """
    stats = {"created": 0, "updated": 0, "unchanged": 0, "errors": []}
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            name = row["name"].strip()
            mtype = row["material_type"].strip()
            try:
                obj, created = Material.objects.get_or_create(
                    name=name, material_type=mtype
                )
            except Exception as exc:  # noqa: BLE001 - report, don't crash the batch
                stats["errors"].append((f"{name} {mtype}", str(exc)))
                continue
            changed = False
            for f in BOOL_FIELDS:
                want = _as_bool(row[f])
                if (overwrite or not getattr(obj, f)) and getattr(obj, f) != want:
                    setattr(obj, f, want)
                    changed = True
            for f in ("category", "drying_need", "description"):
                raw = row[f].strip()
                # Normalise category to lowercase to match TextChoices storage
                want = raw.lower() if f == "category" else raw
                if (
                    want
                    and (overwrite or not getattr(obj, f))
                    and getattr(obj, f) != want
                ):
                    setattr(obj, f, want)
                    changed = True
            if changed:
                obj.save()
            stats[
                "created" if created else ("updated" if changed else "unchanged")
            ] += 1
    return stats
