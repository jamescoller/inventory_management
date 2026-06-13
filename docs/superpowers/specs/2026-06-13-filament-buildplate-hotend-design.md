# Phase 17.1 (completion) — Build-plate & Hot-end specs

**Date:** 2026-06-13
**Status:** Design approved
**Roadmap:** `todo.md` Phase 17.1 — the remaining "build-plate / hot-end still pending" item.

## Goal

Finish Phase 17.1 by populating and displaying `Material.build_plate_compat` and
`Material.hot_end_compat` (free-text, display-only fields that already exist via migrations
0028/0029). Drying temp/time already shipped (PR #165) via a reviewed CSV + `load_material_specs`;
this extends that same pipeline. **No migration.**

## Approach

Curated CSV + the existing loader (the drying-spec precedent), not live PDF parsing — the TDS
rarely states hot-end, so it can't be parsed reliably. A small parser cleanup clears the known
build-plate spacing artifact for any future re-parse and to seed the review draft.

## Components

### 1. Parser cleanup — `inventory/filament_tds.py` `_extract_build_plate`
PDF text extraction concatenates words (`"TexturedPEIPlate"`). Insert spaces at case boundaries
**before** the existing separator normalization:
- `(?<=[a-z])(?=[A-Z])` → `"TexturedPEI"` → `"Textured PEI"`
- `(?<=[A-Z])(?=[A-Z][a-z])` → `"PEIPlate"` → `"PEI Plate"`

So `"TexturedPEIPlate"` → `"Textured PEI Plate"`. Feeds only the gitignored review CSV (not the
DB); it's a quality fix for the draft + future re-parses.

### 2. Data — `docs/filament-tds-specs.csv`
Add two columns, `build_plate_compat` and `hot_end_compat`, to all 38 rows (header becomes
`name,material_type,dry_temp_ideal_degC,dry_time_hrs,build_plate_compat,hot_end_compat`).
- **build_plate_compat:** from the cleaned parser pass over `filament_TDS/*.pdf`, reviewed.
  Materials with no TDS PDF (e.g. some `Support` variants) → left blank.
- **hot_end_compat:** by rule (the TDS rarely states it) — **"Hardened steel"** when the
  material is abrasive: `material_type` contains `CF`/`GF`, or name/type ∈ {Glow, Metal, Marble,
  Wood, Sparkle, Galaxy}; otherwise **"Standard"**. Committed for James to review before the
  prod load.

### 3. Loader — `inventory/material_specs.py`
Add `STR_FIELDS = ["build_plate_compat", "hot_end_compat"]`. Fill **blank-only** by default
(current value `""` → set from CSV; `overwrite=True` replaces). Critically, extend the save to
`update_fields=INT_FIELDS + STR_FIELDS` (the current `update_fields=INT_FIELDS` would silently
drop string writes). Drying values untouched on a prod re-run. Unmatched/blank handling unchanged.

### 4. Display — `inventory/templates/inventory/filament_guide.html`
Add **Build Plate** and **Hot End** columns to the reference DataTables table (`#filament-guide-table`),
both header (`<th>`) and body (`<td>`), keeping header/body column counts equal (14 → 16) to avoid
the known DataTables "Incorrect column count" bug. Show the value or a muted `—` when blank. Picker
cards and color-sheet headers are **not** touched (per the approved scope).

## Testing
- Parser: `_extract_build_plate` turns a `"...TexturedPEIPlate..."`-style blob into spaced
  `"Textured PEI Plate"`; existing extraction still works.
- Loader: fills a blank `build_plate_compat`/`hot_end_compat`; leaves an already-set value alone
  (blank-only); `overwrite=True` replaces; drying ints still load; unmatched rows reported.
- View: `/filament-guide/` renders the two new column headers and a material's values.

## Deploy (human-gated)
Auto-deploy needs no migration. James re-runs `manage.py load_material_specs` on prod after
reviewing the extended CSV — idempotent, blank-only, fills the two new fields without touching
the already-loaded drying temps.

## Non-goals
- No new parser reliance for hot-end (rule-based curation instead).
- No picker-card or color-sheet display (scope-limited to the guide table).
- No new model fields / migration.
