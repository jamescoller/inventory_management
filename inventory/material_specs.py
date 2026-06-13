"""Load TDS-sourced drying specs (temp/time) into existing ``Material`` rows.

Reads ``docs/filament-tds-specs.csv`` — drying temperature/time extracted from the
Bambu Technical Data Sheets (Phase 17.1). Matches existing ``Material`` rows by
``(name, material_type)`` and **never creates** rows. Fills only blank (NULL) fields
by default (``overwrite=False``). Human-gated: run the ``load_material_specs``
management command on prod after reviewing the CSV.
"""

import csv

from inventory.models import Material

INT_FIELDS = ["dry_temp_ideal_degC", "dry_time_hrs"]
STR_FIELDS = ["build_plate_compat", "hot_end_compat"]


def _as_int(value):
    value = (value or "").strip()
    return int(value) if value else None


def load_material_specs(csv_path, *, overwrite=False):
    """Apply the TDS drying-spec CSV to existing Material rows. Returns a counts dict.

    ``overwrite=False`` (default) only fills fields that are currently NULL; pass
    ``overwrite=True`` to replace already-set values."""
    stats = {"updated": 0, "unchanged": 0, "unmatched": [], "errors": []}
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            name = row["name"].strip()
            mtype = row["material_type"].strip()
            try:
                obj = Material.objects.get(name=name, material_type=mtype)
            except Material.DoesNotExist:
                stats["unmatched"].append(f"{name} {mtype}".strip())
                continue
            except Exception as exc:  # noqa: BLE001 - report, don't crash the batch
                stats["errors"].append((f"{name} {mtype}".strip(), str(exc)))
                continue
            changed = False
            for f in INT_FIELDS:
                want = _as_int(row.get(f))
                if want is None:
                    continue
                if (overwrite or getattr(obj, f) is None) and getattr(obj, f) != want:
                    setattr(obj, f, want)
                    changed = True
            for f in STR_FIELDS:
                want = (row.get(f) or "").strip()
                if not want:
                    continue
                if (overwrite or getattr(obj, f) == "") and getattr(obj, f) != want:
                    setattr(obj, f, want)
                    changed = True
            if changed:
                obj.save(update_fields=INT_FIELDS + STR_FIELDS)
                stats["updated"] += 1
            else:
                stats["unchanged"] += 1
    return stats
