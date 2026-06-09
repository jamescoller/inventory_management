# Filament Data Pipeline — Design (2026-06-09)

How James's initiative #1 gets built: use the Bambu source files (now in the repo) to (1) fill
`Material` drying/compatibility specs, (2) build out the filament guide, (3) fill missing
`Filament` colors/hex, and (4) generate printable color sheets — especially for the types that
only have website screenshots. Scheduled as **Phase 17**; depends on the Phase 5 schema +
`docs/filament-guide-data.csv`.

---

## 1. Source files (in repo as of commit `885c422`)

| Folder / file | What | Count | Format |
|---|---|---|---|
| `filament_TDS/` | Bambu (+ PolyLite) **Technical Data Sheets** — print temp, **drying temp/time**, **build-plate compat**, **nozzle/hot-end** | ~40 | PDF |
| `filament_hex/` *(text PDFs)* | color→hex tables, machine-readable | ~11 | PDF (extractable text) |
| `filament_hex/` *(PNGs)* | color→hex tables that **only exist as website screenshots** | ~16 | PNG |
| `filament-guide-en.pdf` | the master **Bambu Filament Guide** (properties, use-cases, drying) | 1 | PDF (4.2 MB) |
| `docs/filament-guide-data.csv` | 38 `name,material_type` rows + empty guide columns (Phase 5) | 1 | CSV |

**TDS naming:** some are explicit (`Bambu_PLA_Basic_Technical_Data_Sheet.pdf`,
`Bambu_PETG_Basic…`, `Bambu_ABS…`, TPU 85A/90A, ASA Aero/CF, PLA Wood/Silk/Translucent, PVA,
Support for PLA/ABS, PolyLite ASA); others are UUID-named (`a52afdcc…pdf`) and need a first-page
read to identify the material.

**Hex PNGs** (vision/OCR): ABS_GF, ASA, PA6_GF, PC_FR, PETG_HF, PETG_Translucent, PLA Galaxy,
PLA_Glow, PLA_Marble, PLA_Metal, PLA_Silk, PLA_Sparkle, PLA_Wood, TPU_95A_HF, TPU_for_AMS,
PLA_Basic_Gradient. **Hex text-PDFs** (parser): ABS, PLA_Basic, PLA_Matte, PLA_Tough, TPU_85A,
TPU_90A, PETG-CF, PETG_Basic, PLA-CF, PLA_Silk_Multi-color, PLA_Translucent.

---

## 2. Tooling reality (verified on this LXC, 2026-06-09)
- **No poppler** (`pdftotext`/`pdftoppm` absent) and **no Python PDF lib** (`pypdf`,
  `pdfplumber`, `fitz`, `PyPDF2`, `pdfminer` all missing). **Pillow is present.**
- → **Add `pypdf` to the dev venv** for TDS + text-hex PDF parsing. **This is a dev-time /
  data-load dependency, NOT a production image dep** — the parsing runs once on the dev LXC and
  emits CSV/fixtures; the running Docker app never imports it. (So it goes in
  `requirements-dev.txt` or is `uv pip install`-ed ad-hoc, not `requirements.txt`.)
- **PNG hex tables read cleanly via vision** — confirmed by reading `PETG_HF_Hex.png` (Yellow
  `#FFD00B`, Orange `#F75403`, Green `#00AE42`, … Dark Gray `#515151`). The load step reads each
  PNG and transcribes the color→hex rows; no OCR install needed.

---

## 3. Schema changes — `Material`
Drying spec already exists (`dry_temp_min/max/ideal_degC`, `dry_time_hrs`, `drying_required`,
`models.py:836–842`) and just needs **populating** from the TDS. Add two **new** compatibility
fields:
```
build_plate_compat  CharField(120, blank)   # e.g. "Textured PEI, Engineering, High-Temp"
hot_end_compat      CharField(80, blank)    # e.g. "Stainless OK" / "Hardened steel required"
```
Rationale for `CharField` (vs. M2M to a BuildPlate table): the values are a small, display-only
set read off a TDS; a normalized table is over-engineering for a household app (consistent with
the architecture review's "don't over-normalize" stance). Revisit only if filtering by plate
becomes a real workflow. *(If structured filtering is wanted, a `JSONField` list is the cheaper
middle ground.)* Additive migration; no data migration.

---

## 4. The four deliverables

### 17.1 — TDS → `Material` specs
1. `scripts/parse_tds.py` (dev tool, `pypdf`): for each `filament_TDS/*.pdf`, extract text →
   regex/keyword-scrape **drying temperature, drying time, build-plate list, nozzle/hot-end
   note, print-temp range**; resolve UUID-named files by their first-page title. Emit
   `docs/filament-tds-data.csv` (`name,material_type,dry_temp_ideal_degC,dry_time_hrs,
   build_plate_compat,hot_end_compat,…`) for human review.
2. `manage.py load_material_specs docs/filament-tds-data.csv` — idempotent `update_or_create`
   keyed on `(name, material_type)` (the existing unique constraint, `models.py`), filling only
   blank fields by default (`--overwrite` to force). Mirrors the Phase-5 load pattern.

### 17.2 — Hex → fill `Filament` colors
1. Build one **color map** `{(material, material_type, color_name) → hex}`:
   - text-PDFs via `scripts/parse_hex_pdf.py` (`pypdf`),
   - PNGs transcribed via vision into `docs/filament-hex-from-png.csv`.
   Merge → `docs/filament-colors.csv` (`material,material_type,color,hex_code`).
2. `manage.py load_filament_hex docs/filament-colors.csv` — for matching `Filament` rows with a
   blank/placeholder `hex_code`, set it; `Filament.save()` recomputes `color_family`
   (`get_color_family`, `models.py:159`). Fixes the known "swatch shows white because hex is
   blank" class (todo Phase 3 bug). Also seed a lightweight **color catalog** (optional
   `FilamentColor` reference table or just the CSV) for the picker.

### 17.3 — Guide build (finishes Phase 5/7)
1. Fill `docs/filament-guide-data.csv` (38 rows already stubbed) from `filament-guide-en.pdf`:
   the 9 guide booleans + `description` per material (`uv_resistant`, `flexible`,
   `high_strength`, `heat_resistant`, `food_safe`, `easy_to_print`, `budget_friendly`,
   `impact_resistant`, `requires_enclosure`). Read the guide PDF in sections (it's large —
   chunk it) and transcribe.
2. `manage.py load_guide_data docs/filament-guide-data.csv` (the Phase-5 carryover loader).
3. Ship the **Phase 7 requirements picker** on `/filament-guide/`: 8 checkboxes →
   `json_script` material data → client-side scoring → match cards with met/unmet chips +
   `requires_enclosure`/`drying_required` warning badges. (Spec:
   `docs/superpowers/specs/2026-05-21-filament-guide-design.md`.)

### 17.4 — Color sheets + Bambu Store link
1. `manage.py make_color_sheets` (Pillow — already installed): for each material/subtype,
   render a **printable color-reference sheet** (swatch grid + name + hex), styled like the
   Bambu hex tables. **Priority: generate fresh sheets for the PNG-only types** (so all types
   have a clean PDF, not a website screenshot). Output to `media/color-sheets/` or a
   `docs/color-sheets/` set.
2. **Bambu Store quick-link (item #9):** add a "View in Bambu Store" link on filament product
   pages using the SKU. *(Live price scraping stays Trashed — no public store API; fragile.)*

---

## 5. Execution notes
- Parsing/transcription is **agent-parallelizable** (one agent per material family) — a good
  ultracode fit: fan out TDS/hex extraction, converge to the review CSVs, then run the loaders.
- All loaders are **idempotent** `update_or_create` and **review-gated** (human eyeballs the CSV
  before load) — Bambu occasionally revises a TDS, and scraped/vision data deserves a check.
- No production dependency added; no `.env` change. The only schema change is the two additive
  `Material` fields (§3).
