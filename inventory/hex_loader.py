"""Backfill ``Filament.hex_code`` (+ ``hex_code_2``) from the merged color CSV.

Reads ``docs/filament-colors.csv`` (227 Bambu colors: 123 text-PDF parse + 104 vision
pass). Matches existing ``Filament`` spools by color name (case-insensitive), narrowed
by linked ``Material`` name/subtype when the CSV provides them. Only fills BLANK hex by
default. Unmatched rows are reported, never created. Human-gated."""

import csv

from inventory.models import Filament


def load_filament_hex(csv_path, *, overwrite=False):
    stats = {"filled": 0, "skipped_set": 0, "unmatched": []}
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            color = row["color_name"].strip()
            material = row["material"].strip()
            mtype = row["material_type"].strip()
            hex_code = row["hex_code"].strip()
            hex2 = (row.get("hex_code_2") or "").strip()
            if not color or not hex_code:
                continue

            qs = Filament.objects.filter(color__iexact=color)
            if material:
                narrowed = qs.filter(material__name__iexact=material)
                if mtype:
                    narrowed = narrowed.filter(material__material_type__iexact=mtype)
                if narrowed.exists():
                    qs = narrowed

            matches = list(qs)
            if not matches:
                stats["unmatched"].append(f"{material} {mtype} {color}".strip())
                continue
            for fil in matches:
                if fil.hex_code and not overwrite:
                    stats["skipped_set"] += 1
                    continue
                fil.hex_code = hex_code
                fil.hex_code_2 = hex2
                fil.save()  # recomputes color_family (GRADIENT when hex2 set)
                stats["filled"] += 1
    return stats
