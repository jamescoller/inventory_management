"""Parse Bambu filament Hex Code Table PDFs into color->hex rows (Phase 17.2).

Dev-time data-extraction tool, **not part of the running app**. Reads the text
``filament_hex/*.pdf`` sheets and emits one row per color for human review before
any load (see the ``parse_filament_hex`` management command). It deliberately makes
no DB writes.

The 16 **screenshot PNGs** in ``filament_hex/`` are website captures that need a
separate vision/OCR pass — this parser handles only the **text PDFs**.

``pypdf`` is imported lazily inside :func:`extract_pdf_text` so this module (and the
pure-text parser) import cleanly in the production app, which never installs
``pypdf``. The parsing logic is unit-tested against committed text fixtures, so the
tests never need ``pypdf`` either.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass

CSV_FIELDS = ["source_file", "material", "color_name", "hex_code"]

# A line like "Hex:#FFFFFF" (optionally "#RRGGBBAA"); spacing/case tolerant.
_HEX_RE = re.compile(r"hex\s*:\s*#?([0-9a-f]{6}(?:[0-9a-f]{2})?)", re.IGNORECASE)
# Header lines that are never a color name.
_SKIP = ("", "bambu lab", "filament hex code table")


@dataclass
class HexRow:
    source_file: str
    material: str
    color_name: str
    hex_code: str

    def as_csv_dict(self) -> dict:
        return asdict(self)


def material_from_filename(path: str) -> str:
    """Best-effort material/subtype from the file name, e.g.
    ``Bambu_PLA_Basic_Hex_Code.pdf`` -> ``PLA Basic``."""
    base = os.path.splitext(os.path.basename(path))[0]
    base = re.sub(r"(?i)bambu", " ", base)
    base = re.sub(r"(?i)hex(\s*code)?(\s*table)?", " ", base.replace("_", " "))
    base = base.replace("(1)", " ")
    return re.sub(r"\s+", " ", base).strip()


def parse_hex_text(text: str, *, source_file: str = "") -> list[HexRow]:
    """Pair each ``Hex:#...`` line with the most recent preceding non-header line
    (the color name). Header/material lines get overwritten by the real color name
    before their hex line, so they never leak into the output."""
    material = material_from_filename(source_file)
    base = os.path.basename(source_file)
    rows: list[HexRow] = []
    prev = ""
    for raw in text.splitlines():
        line = raw.strip()
        match = _HEX_RE.search(line)
        if match and prev:
            rows.append(
                HexRow(
                    source_file=base,
                    material=material,
                    color_name=prev,
                    hex_code="#" + match.group(1).upper(),
                )
            )
            prev = ""
        elif line and line.lower() not in _SKIP and not match:
            prev = line
    return rows


def extract_pdf_text(path: str) -> str:
    import pypdf  # lazy: dev-only dependency, never installed in the prod image

    reader = pypdf.PdfReader(path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def parse_hex_dir(directory: str) -> tuple[list[HexRow], list[tuple[str, str]]]:
    """Parse every text ``*.pdf`` in ``directory`` (sorted). Returns
    ``(rows, errors)``; a single unreadable PDF is recorded, not fatal. PNGs are
    skipped (they need a vision pass)."""
    rows: list[HexRow] = []
    errors: list[tuple[str, str]] = []
    for fname in sorted(os.listdir(directory)):
        if not fname.lower().endswith(".pdf"):
            continue
        path = os.path.join(directory, fname)
        try:
            rows.extend(parse_hex_text(extract_pdf_text(path), source_file=path))
        except Exception as exc:  # noqa: BLE001 - defensive: keep going on bad file
            errors.append((fname, str(exc)))
    return rows, errors
