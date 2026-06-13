"""Parse Bambu / PolyLite filament Technical Data Sheets (TDS) into structured rows.

This is a **dev-time data-extraction tool**, not part of the running app. It reads
the PDF TDS files committed under ``filament_TDS/`` and scrapes the few fields the
inventory app cares about — drying temperature/time, build-plate compatibility,
hot-end/nozzle compatibility, and the print-temperature range — emitting one
structured row per sheet for human review (see ``parse_filament_tds`` management
command).

Design notes:

* PDF text extraction is messy and the sheets are not perfectly consistent
  (whitespace gets collapsed, ``°C`` may or may not have spaces, the drying time
  may read ``8 h`` / ``8 hours`` / ``8-12h``, and the build-plate row is labelled
  either "Bed Type" or "Build Plate Type"). The parser is therefore **defensive**:
  it extracts what is reliably present and leaves anything ambiguous **blank**
  rather than guessing. The whole point of Phase 17.1 is to produce a review CSV a
  human verifies before any load.
* ``pypdf`` is imported lazily inside :func:`extract_pdf_text` so this module (and
  the pure-text parser :func:`parse_tds_text`) imports cleanly in the production
  app, which never has ``pypdf`` installed. The parsing logic is unit-tested
  against committed text fixtures, so the tests never need ``pypdf`` either.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field

# The ordered set of columns written to the review CSV. Keeping it here keeps the
# parser and the management command in lockstep.
CSV_FIELDS = [
    "source_file",
    "name",
    "material_type",
    "mfr",
    "dry_temp_ideal_degC",
    "dry_time_hrs",
    "build_plate_compat",
    "hot_end_compat",
    "print_temp_min_degC",
    "print_temp_max_degC",
    "notes",
]


@dataclass
class TdsRow:
    """One parsed TDS sheet. Unknown fields stay at their empty default."""

    source_file: str = ""
    name: str = ""
    material_type: str = ""
    mfr: str = ""
    dry_temp_ideal_degC: int | None = None
    dry_time_hrs: int | None = None
    build_plate_compat: str = ""
    hot_end_compat: str = ""
    print_temp_min_degC: int | None = None
    print_temp_max_degC: int | None = None
    notes: str = ""

    def as_csv_dict(self) -> dict:
        """Flatten to the CSV column set, rendering ``None`` as empty string."""
        d = asdict(self)
        return {k: ("" if d.get(k) is None else d.get(k)) for k in CSV_FIELDS}


# --- text normalisation -----------------------------------------------------

# Some sheets glue words together when the PDF is extracted ("DryingSettings",
# "BedType", "NozzleTemperature"). We do not blindly de-glue (that risks mangling
# real content); instead each field regex tolerates an optional space.
_DEGREE = r"[°˚]?\s*C"  # the degree mark is inconsistent / sometimes dropped


def _norm(text: str) -> str:
    """Collapse newlines and runs of whitespace to single spaces."""
    return re.sub(r"\s+", " ", text.replace(" ", " ")).strip()


# --- individual field extractors -------------------------------------------

# "Drying Settings before Printing  Blast Drying Oven: 50 °C，8 h"
# Tolerates: collapsed "DryingSettings"; ASCII or fullwidth comma; "h"/"hours";
# a range like "8 -12h" (we take the first number); optional "Blast Drying Oven:".
_DRY_RE = re.compile(
    r"Drying\s*Settings\s*before\s*Printing"
    r".*?"  # skip "Blast Drying Oven:" etc.
    r"(\d{2,3})\s*" + _DEGREE + r"\s*[，,、]?\s*"  # temperature
    r"(\d{1,3})\s*(?:-\s*\d{1,3}\s*)?(?:h\b|hour)",  # time (first of a range)
    re.IGNORECASE,
)


def _extract_drying(text: str):
    m = _DRY_RE.search(text)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


# Build-plate row: labelled "Bed Type" or "Build Plate Type". The value runs until
# the next known "Subjects" label in the printing-settings table.
_BED_RE = re.compile(
    r"(?:Build\s*Plate\s*Type|Bed\s*Type)\s+"
    r"(.+?)"
    r"\s*(?:Bed\s*Surface|Build\s*Plate\s*Surface|Surface\s*Preparation"
    r"|Bed\s*Temperature|Cooling\s*Fan|Glue|Printing\s*Speed)",
    re.IGNORECASE,
)


def _extract_build_plate(text: str) -> str:
    m = _BED_RE.search(text)
    if not m:
        return ""
    val = _norm(m.group(1))
    # PDF text extraction concatenates words ("TexturedPEIPlate"); re-insert
    # spaces at case boundaries before normalizing separators.
    val = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", val)
    val = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", val)
    # Normalise separators to a comma list and de-dupe internal double spaces.
    val = re.sub(r"\s*/\s*", ", ", val)
    val = re.sub(r"\s+or\s+", ", ", val, flags=re.IGNORECASE)
    val = re.sub(r"\s+", " ", val)
    # collapse repeated commas / trailing punctuation
    val = re.sub(r"\s*,\s*", ", ", val).strip(" ,")
    return val


# Hot-end / nozzle hardness. Bambu TDS only rarely states this explicitly; we ONLY
# record it when a real recommendation phrase is present, otherwise blank (per the
# "don't guess" rule). A bare "wear resistance" in marketing copy is not a match.
_HOTEND_RE = re.compile(
    r"(hardened\s+steel(?:\s+nozzle)?(?:\s+(?:is\s+)?(?:required|recommended))?"
    r"|wear[-\s]?resist\w*\s+nozzle"
    r"|(?:steel|hardened)\s+nozzle\s+(?:is\s+)?(?:required|recommended))",
    re.IGNORECASE,
)


def _extract_hot_end(text: str) -> str:
    m = _HOTEND_RE.search(text)
    if not m:
        return ""
    return _norm(m.group(1))


# Nozzle/print temperature range, e.g. "Nozzle Temperature 190 - 230 °C".
_TEMP_RE = re.compile(
    r"Nozzle\s*Temperature\s+(\d{2,3})\s*-\s*(\d{2,3})\s*" + _DEGREE,
    re.IGNORECASE,
)


def _extract_print_temp(text: str):
    m = _TEMP_RE.search(text)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


# --- title / material-name extraction --------------------------------------

# Generic noise we never want to treat as a material name (header/version lines).
_TITLE_NOISE = re.compile(r"^(?:V\d|Technical\s+Data\s+Sheet|Bambu\s+Filament)", re.I)

# A material-name candidate is a short line of letters/digits/dashes/spaces and a
# few trailing markers like "+" (e.g. "PLA Basic", "ABS-CF", "PLA Tough+").
_NAME_OK = re.compile(r"^[A-Za-z][A-Za-z0-9 +/\-]{0,40}$")


def _extract_title(raw_text: str) -> str:
    """The material name: the first sensible line after 'Technical Data Sheet'.

    Falls back to "" if nothing plausible is found (caller fills from filename).
    """
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    has_header = any(
        re.search(r"Technical\s+Data\s+Sheet", line, re.I) for line in lines
    )

    seen_tds = not has_header  # no header -> scan from the top for a name line
    for line in lines:
        if not seen_tds:
            if re.search(r"Technical\s+Data\s+Sheet", line, re.I):
                seen_tds = True
            continue
        # first non-noise line after the TDS header (or from the top, headerless)
        if _TITLE_NOISE.match(line):
            continue
        if line.startswith(("•", "·")):
            # A bullet before any name (header case) means the layout is unusual;
            # give up so the caller falls back to the filename.
            return "" if has_header else ""
        if _NAME_OK.match(line):
            return line
        # In the header case, the line right after the header should be the name;
        # if it is not name-shaped, bail to the filename fallback. In the
        # headerless case, keep scanning for a name-shaped line.
        if has_header:
            return ""
    return ""


# Known manufacturer hints derived from the filename / title.
def _guess_mfr(source_file: str, title: str) -> str:
    blob = f"{source_file} {title}".lower()
    if "polylite" in blob or "polymaker" in blob:
        return "Polymaker"
    return "Bambu Lab"


def _split_name_and_type(title: str) -> tuple[str, str]:
    """Split a TDS title into (base polymer name, subtype modifier).

    Mirrors the ``Material`` convention: ``name`` is the base polymer (e.g. "PLA",
    "PETG", "ABS"); ``material_type`` is the subtype ("Basic", "CF", "HF", "Matte",
    "Silk+"…). Conservative: if the first token is not a recognised polymer family,
    the whole title becomes ``name`` and the subtype is blank.
    """
    title = title.strip()
    if not title:
        return "", ""
    # "ABS-CF" / "PLA-CF" / "PA6-CF" -> base "ABS"/"PLA"/"PA6", subtype "CF"
    m = re.match(r"^([A-Za-z][A-Za-z0-9]*)-([A-Za-z0-9]+)$", title)
    if m:
        return m.group(1).upper(), m.group(2).upper()
    parts = title.split()
    head = parts[0]
    polymer_families = {
        "PLA",
        "PETG",
        "ABS",
        "ASA",
        "TPU",
        "PVA",
        "PC",
        "PA",
        "PA6",
        "PAHT",
        "PET",
        "PPA",
        "PPS",
    }
    if head.upper() in polymer_families and len(parts) > 1:
        return head.upper(), " ".join(parts[1:])
    return title, ""


# --- public API -------------------------------------------------------------


def parse_tds_text(text: str, *, source_file: str = "") -> TdsRow:
    """Parse already-extracted TDS text into a :class:`TdsRow`.

    Pure function — no PDF dependency. ``text`` is the concatenation of every
    page's extracted text (newlines preserved so the title line can be found).
    """
    title = _extract_title(text)
    if not title and source_file:
        # Fall back to a filename-derived title for differently-formatted sheets
        # (e.g. PolyLite, whose header puts the version where the name should be).
        stem = os.path.splitext(os.path.basename(source_file))[0]
        if not re.fullmatch(r"[0-9a-f]{32}", stem):  # skip UUID names
            cleaned = re.sub(
                r"(?i)_?technical_?data_?sheet.*$", "", stem.replace("_", " ")
            )
            cleaned = re.sub(r"(?i)\bTDS\b.*$", "", cleaned)
            cleaned = re.sub(r"(?i)\bEN\b.*$", "", cleaned).strip(" -")
            title = _norm(cleaned)

    name, mtype = _split_name_and_type(title)
    flat = _norm(text)

    dry_temp, dry_time = _extract_drying(flat)
    tmin, tmax = _extract_print_temp(flat)

    return TdsRow(
        source_file=os.path.basename(source_file) if source_file else "",
        name=name,
        material_type=mtype,
        mfr=_guess_mfr(source_file, title),
        dry_temp_ideal_degC=dry_temp,
        dry_time_hrs=dry_time,
        build_plate_compat=_extract_build_plate(flat),
        hot_end_compat=_extract_hot_end(flat),
        print_temp_min_degC=tmin,
        print_temp_max_degC=tmax,
    )


def extract_pdf_text(path: str) -> str:
    """Return the concatenated text of every page in ``path``.

    Imports ``pypdf`` lazily so this module imports without it (the prod app never
    installs ``pypdf``). Raises a clear error if ``pypdf`` is missing.
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - exercised only without pypdf
        raise RuntimeError(
            "pypdf is required to read TDS PDFs. It is a dev-only dependency: "
            "install it with `uv pip install --python <venv> pypdf` "
            "(it lives in requirements-dev.txt, never requirements.txt)."
        ) from exc

    reader = PdfReader(path)
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def parse_tds_file(path: str) -> TdsRow:
    """Read and parse a single TDS PDF into a :class:`TdsRow`."""
    return parse_tds_text(extract_pdf_text(path), source_file=path)


@dataclass
class ParseReport:
    """Aggregate result of parsing a directory: rows plus any per-file errors."""

    rows: list = field(default_factory=list)
    errors: list = field(default_factory=list)  # list[(filename, message)]


def parse_tds_dir(directory: str) -> ParseReport:
    """Parse every ``*.pdf`` in ``directory`` (sorted), collecting per-file errors.

    A single unreadable PDF does not abort the run — it is recorded in
    ``report.errors`` and the rest are still parsed.
    """
    report = ParseReport()
    for fname in sorted(os.listdir(directory)):
        if not fname.lower().endswith(".pdf"):
            continue
        path = os.path.join(directory, fname)
        try:
            report.rows.append(parse_tds_file(path))
        except Exception as exc:  # noqa: BLE001 - defensive: keep going
            report.errors.append((fname, str(exc)))
    return report
