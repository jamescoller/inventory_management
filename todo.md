# Inventory Management — TODO / Roadmap

Items are grouped by phase. Within each phase, bugs before enhancements.
File:line references reflect the codebase as of May 2026.

---

## Phase 1 — Critical Bug Fixes

These are confirmed crashes or security holes in currently-reachable code.

### Bugs

- [x] **Search crashes on every request** — added `import re` to views.py.
- [x] **Barcode print redirect broken** — fixed kwarg from `pk=` to `item_id=` in `PrintBarcodeView.post` and `BarcodeRedirectView.get`.
- [x] **Every new Printer crashes on save** — added `bed_length_mm`, `bed_width_mm`, `max_height_mm` to `PrinterForm.Meta.fields`.
- [x] **Admin dropdowns crash when any Filament has no Material** — added null guard in `Filament.__str__`.
- [x] **Bulk update material admin action broken** — changed `queryset.update(new_matl=material)` to `queryset.update(material=material)`.
- [x] **Hex code normalization silently broken** — fixed regex in `normalize_hex_code()` to match stripped (no-`#`) value.
- [x] **Filament drying warning never fires** — changed `self.status == "NEW"` to `self.status == self.Status.NEW`.
- [x] **Fix `DEBUG` env var cast** — added `cast=bool` to `config("DEBUG", ...)`.
- [x] **Excel export broken** — fixed `item.location.name` crash when location is None.
- [x] **`import_products.py` is orphaned and broken** — deleted. `numpy`/`pandas` removal deferred to Phase 3.

### Security

- [x] **Debug toolbar exposed in production** — wrapped `debug_toolbar` in `if DEBUG:` guards in `settings.py` (INSTALLED_APPS + MIDDLEWARE) and `urls.py`.
- [x] **Stored XSS via chart labels** — replaced `{{ filament_chart_data.labels|safe }}` / `{{ filament_chart_data.data|safe }}` with `json_script` filter + `JSON.parse` in dashboard.html.
- [x] **Stored XSS via tooltip HTML** — run `serial_number` and `color` through `django.utils.html.escape()` before building `tooltip_html` in both `InUseOverviewView` and `DryStorageOverviewView`.
- [x] **Missing `LoginRequiredMixin`** — added to `PrintBarcodeView`, `BarcodeRedirectView`, `InUseOverviewView`, `DryStorageOverviewView`.

---

## Phase 2 — Dead Code Removal & Cleanup

Safe to delete without any user-visible impact.

### Delete entirely

- [x] `tables.py` — deleted; `django-tables2` removed from requirements and INSTALLED_APPS.
- [x] `FilamentView` in views.py + `filament_view.html` — deleted.
- [x] `Order` and `Shipment` models — deleted from models.py and admin.py; migration 0020 drops their DB tables.
- [x] `inventory/import_products.py` — deleted in Phase 1.
- [x] `inventory/templates/inventory/bulkadd.html` — deleted.
- [x] `inventory/templates/inventory/delete_item.html` — deleted.
- [x] `inventory/templates/inventory/search_results.html` — deleted.
- [x] `inventory/templates/inventory/movement.html` — deleted.
- [x] Commented-out URL patterns in `inventory/urls.py` — removed.
- [x] `format_label` and `generate_barcode` in `barcode_utils.py` — deleted and removed from `__all__`.
- [x] Hardcoded fallback printer IP `"192.168.68.93"` — replaced with correct LAN address `"10.10.40.2"`.

### Fix `from X import *` antipattern

- [x] Replace `from .models import *` in views.py with explicit imports.
- [x] Replace `from .forms import *` in views.py with explicit imports.
- [x] Replace `from .models import *` in forms.py with explicit imports.

### Wire up or fix signals.py

- [x] `inventory/apps.py` `ready()` now imports `inventory.signals`.
- [x] Fixed `StatusChoices` typo → `Status`; switched from `post_save` to `pre_save` so old state is read from DB before the write.

### Redundant boolean fields

- [x] `depleted`, `in_use`, `sold` converted to `@property` on `InventoryItem`; DB columns dropped in migration 0020; admin `list_filter` updated.

---

## Phase 3 — Code Quality & Architecture

### Views

- [x] **Consolidate the 5 Add Product views** — extracted `BaseAddProductView` mixin; each of the 5 subclasses is now ~5 lines.
- [x] **Fix Dashboard N+1 queries** — replaced Python-side table scans with `values().annotate(Count(...))` DB aggregations.
- [x] **Move UPC lookup logic out of `AddInventoryView.post()`** — replaced 10-line subclass loop with `Product.objects.filter(upc=upc).first()` (polymorphic queryset returns real instance directly).
- [x] **Standardize CBV naming** — `inventoryEditView` → `InventoryEditView`, `addInventoryView` → `AddInventoryView`.

### Models / Forms

- [x] **Move hex validation to `Filament.clean()` + `FilamentForm.clean_hex_code()`** — invalid hex now shows as a form field error instead of a 500.
- [x] **Move printer dimension validation to `Printer.clean()`** — removed `ValueError` from `Printer.save()`.
- [x] **Fix `InventoryItem.save()` location-change detection** — added `from_db()` to store `_original_location_id`; `save()` compares against it instead of doing an extra SELECT.

### Templates

- [x] **Consolidate the 5 near-identical add-product templates** — replaced with single `add_product.html` that uses `{{ form_title }}` / `{{ submit_label }}` context vars.
- [x] **Fix JS load order in `base.html`** — moved all JS library `<script>` tags before `{% block extra_scripts %}` so child template scripts always have jQuery/Bootstrap/Chart.js available.
- [x] **Deduplicate DataTables CSS** — removed duplicate `<link>` (was in both `<head>` and after content block).
- [x] **`in_use_overview.html` and `dry_storage_overview.html`** — extracted shared filament card body into `includes/filament_item_body.html` (show_name/show_location flags); tooltip init into `includes/tooltip_init.html`.

### Admin

- [x] **Fix `field` → `fields` typo** in `HardwareAdmin`, `DryerAdmin`, `AMSAdmin`.
- [x] **Fix `DryerAdmin.field`** — corrected `'max_temp"degC'` → `'max_temp_degC'`.
- [x] **Fix `display_product_details`** — fixed wrong reverse-accessor patterns; serial number now read from `obj` (InventoryItem) not from the product subclass.
- [x] **Fix `ShipmentAdmin`** — already deleted in Phase 2 along with the Shipment model.
- [x] **Fix `mark_depleted` admin action** — now iterates queryset and calls `instance.mark_depleted(); instance.save()` so `date_depleted` and `location` are kept in sync.
- [x] **Fix `view_log`** — replaced `f.readlines()[-200:]` (reads whole file) with `subprocess + tail -n 200`.

### Dependencies to clean up (after dead code removal)

- [x] Remove `numpy` and `pandas` — done in Phase 2 (import_products.py deleted).
- [x] Remove `django-tables2` — done in Phase 2 (tables.py deleted).
- [x] Move `pre-commit` and `django-debug-toolbar` to a `requirements-dev.txt`.
- [x] Pin `python-barcode`, `brother_ql`, `python-decouple` to explicit minimum versions.
- [x] Remove `setuptools` from app requirements.

### Tests

- [ ] Add `tests.py` basics — at minimum one round-trip per view and one `save()` per model. The number of latent bugs caught by the analysis above suggests zero test coverage currently.

### Bugs

- [x] On view (`FilamentSummaryView`):
  - [x] Material cards at the top of the page are sorted alphabetically by material name, instead of by the number of filament rolls in the inventory.
  - [x] Color of the black swatches in the filament cards is approximately `#2c3e50` instead of `#000000`.
  - [x] ** Enhancement: ** Center the filament cards and the totals cards on the page instead of having them flush to the left.
  - [x] Missing filters for `subtype` on the table. This can be added just above the table on the left side. Add filters for material and color family here as well.
  - [x] In the table, change the word `family` to `color family` in the column headers.
  - [x] On the used filters (`7d`, `30d`, `1y`), the selected filter is shown by removing the border of the button. This is hard to see. Leave the border on and instead invert the colors of the font and background of the button.
  - [x] Some colors, such as `TPU 95A HF` show the color written Black, but the color swatch is White. This could be due to the color hex not being written in the individual DB entries. Investigate and fix.
---

## Phase 4 — Quick Wins & Test Foundation

Small, self-contained items plus the test coverage carryover from Phase 3. Ship as a single PR.

### Carryover from Phase 3

- [ ] Add `tests.py` basics — at minimum one round-trip per view and one `save()` per model. *(Moved from Phase 3; must be done before Phase 5+ features to establish a safety net.)*

### Cleanup

- [ ] Remove barcode printer MAC discovery from `barcode_utils.py`; use only the static IP `10.10.40.2`.

### Small Features

- [ ] **#38 — Show spool boolean in inventory editor** — `Filament.has_spool` exists on the model; add it to `InventoryEditForm.Meta.fields` and the edit template.
- [ ] **#47 — Improve Item ID barcode rendering** — INV-XXX barcodes are hard for scanners to read. Investigate `module_width_mm` tuning in `barcode_utils.py`; compare rendered output against a known-good P-touch label. May need to adjust quiet zone or bar height ratio.

---

## Phase 5 — Filament Selection Guide (Stage 1: Data Foundation)

Spec: `docs/superpowers/specs/2026-05-21-filament-guide-design.md`

Delivers the reference table immediately (useful for James). Lays the data foundation that Stage 2 (Phase 7) and the Haiku data-loading task depend on.

### Model

- [ ] Add 13 fields to `Material`: `uv_resistant`, `flexible`, `high_strength`, `heat_resistant`, `food_safe`, `easy_to_print`, `budget_friendly`, `impact_resistant`, `requires_enclosure`, `requires_drying`, `drying_temp_c`, `drying_time_hours`, `description`.
- [ ] Generate and include migration `0023_material_guide_fields`.

### Admin

- [ ] Add `Guide Properties` fieldset to `MaterialAdmin` grouping all new fields.

### View + Template

- [ ] Add `FilamentGuideView` (GET, `LoginRequiredMixin`) at `/filament-guide/`.
- [ ] Template: reference table via DataTables. Boolean columns render ✓ / —. `requires_enclosure` and `requires_drying` use warning colour on ✓. Include placeholder comment for Stage 2 picker.
- [ ] Add nav link to `navigation.html`.

### Data loading (post-deploy, separate task)

- [ ] After Stage 1 is deployed to the app host, dispatch Haiku agents with James's filament documentation to populate the new fields for all existing `Material` rows via Django shell. *(Not part of the implementation PR — runs after deploy.)*

---

## Phase 6 — Barcode & Location System

These three items share the same infrastructure and ship together. Camera scanning depends on good barcodes existing first.

- [ ] **#48 — Location barcodes (LOC-XXX)** — Add auto-generated `LOC-{id}` code to the `Location` model; extend `PrintBarcodeView` to handle location objects; add a print button to the location admin/detail page.
- [ ] **#49 — Location-based views** — `Location` already has `default_status` and `is_printer`. Build views to list all items at a location and edit an item's location from that view.
- [ ] **Phone camera barcode scanning** — Integrate `@zxing/browser` JS library; wire a camera-capture modal to the existing search/inventory flow via HTMX. Works on any phone browser without a native app. Scan LOC-XXX → location page; scan INV-XXX → item page.

---

## Phase 7 — Filament Selection Guide (Stage 2: Requirements Picker)

Spec: `docs/superpowers/specs/2026-05-21-filament-guide-design.md`

*Depends on Phase 5 data loading being complete.*

- [ ] Add requirements picker above the reference table on `/filament-guide/`: 8 checkboxes with Bootstrap tooltips, no page reload.
- [ ] Embed all `Material` guide data as a `json_script` block (same XSS-safe pattern as dashboard charts).
- [ ] JS scoring: count satisfied requirements per material. Perfect matches (score = 1.0) highlighted with star badge at top. Partial matches (≥ 0.5) ranked below with per-requirement met/unmet chips (✓ green / ✗ muted). Poor matches (< 0.5) hidden behind a "Show all" toggle.
- [ ] Warning badges on result cards: `requires_enclosure` (red), `requires_drying` with temp/time (amber).

---

## Phase 8 — Data Visualizations

*Spool weight distribution is self-contained. Filament usage over time requires a new consumption event log — design that data model before starting.*

- [ ] **Spool weight distribution** — chart showing how much filament (by weight) is on hand per color/material. Data is already available via `Filament.weight` × `on_hand` count.
- [ ] **Filament usage over time** — requires adding a `ConsumptionEvent` log (recorded when an item is marked depleted). Design the model before implementing the chart.

---

## Completed Features

- [x] **Bulk inventory editor** — Checkbox selection on Search Inventory page; sticky action bar for bulk status/location/shipment changes. `POST /bulk-update/` (`BulkUpdateView`). JS `Set` as selection source of truth (survives DataTables pagination). Iterates `item.save()` to preserve all side-effects.
- [x] **Filament summary view** — `/filament-summary/` (`FilamentSummaryView`). Material cards sorted by roll count; DataTables with material/subtype/color-family filter dropdowns; period toggle (7d/30d/1y) for usage; `material_type` field on `Material` (migrations 0021/0022).
- [x] **Improved data visualizations** — Dashboard: 3 charts + low-stock alert table with urgency tiers. `/filament-color-guide/` page grouped by color family, printable as PDF.
- [x] **Status-based location assignment** — Implemented in `InventoryItem.save()` via `Location.default_status`.

---

## Backlog

Items with real value but no current phase slot. Revisit during sprint planning.

- [ ] **#33 — Excel export** — Fix `InventoryExportView`. Low priority; not regularly used.
- [ ] **#34 — Import order/invoice history** — Relocate to `management/commands/`; replace pandas with openpyxl. Only worth doing if invoice imports are a regular workflow.
- [ ] **#65 — View 3MF files in web portal** — `three.js` + `Online3DViewer`. Significant JS bundle for a household app; revisit if 3MF browsing becomes a real workflow need.
- [ ] **BambuLab MQTT integration** — Connect to printers on local LAN (same protocol as HACS `bambu_lab`). Pull AMS slot assignments, print progress, temperatures. Auto-update spool tracking on print completion. High value but changes app from manual to event-driven — requires dedicated design session before any implementation.
- [ ] **HA/Grafana dashboard** — Expose DB visualizations in a Home Assistant dashboard via Grafana. Mostly infrastructure/configuration work. Revisit after BambuLab integration.
- [ ] **Bambu Store quick-link** — Add a "View in Bambu Store" link on filament product pages using the SKU. Trivial to add; the price scraping / HA alert scope from the original idea is backlog.
- [ ] **Printer utilization chart** — Blocked on BambuLab integration.
- [ ] **`ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS` from env vars** — Low urgency; only matters if the app gains a new deployment URL.
- [ ] **HTTPS + `SECURE_*` settings** — Only needed if the app is ever exposed outside the LAN.

---

## Trashed

Ideas that were evaluated and set aside. Kept here for context so they don't get re-proposed.

- **Reusable app extraction** (`barcode_utils` package, `polymorphic_inventory` app) — Premature abstraction for a single-developer household app. No other projects consuming these; the extraction cost outweighs any benefit at current scale.
- **Polar/radar charts for filament guide** — Visually impressive (Bambu Lab uses them) but adds cognitive overhead without improving decisions. Per-requirement badge chips are more scannable for this use case.
- **Sphinx docs + GitHub Pages** — No audience; the codebase is self-explanatory for a solo project.
- **SQLite → PostgreSQL migration** — No concurrent write pressure currently. Revisit only if write contention becomes measurable.
- **Per-user inventory scoping** — `user` FK deliberately removed in migration 0013. Fine for single-household use; only revisit if multi-user support is explicitly needed.
- **Bambu Store price scraping + HA sale alerts** — Bambu has no public store API; scraping is fragile by nature. The quick-link (backlog) is the right scope.
