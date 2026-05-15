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

---

## Phase 4 — Features & Enhancements

### Open GitHub Issues

- [ ] **#47 — Improve Item ID barcode rendering** — INV-XXX barcodes are hard for scanners to read. Investigate `module_width_mm` tuning in `barcode_utils.py`; compare rendered output against a known-good P-touch label. May need to adjust quiet zone or bar height ratio.
- [ ] **#48 — Location barcodes (LOC-XXX)** — Add `barcode` field or auto-generated `LOC-{id}` code to the `Location` model; extend `PrintBarcodeView` to handle location objects; add a print button to the location admin/detail page.
- [ ] **#49 — Location-based views** — `Location` already has `default_status` and `is_printer`. Build views to: list all items at a location, and edit an item's location from that view. Natural companion to #48.
- [ ] **#38 — Show spool boolean in inventory editor** — `Filament.has_spool` exists on the model; add it to `InventoryEditForm.Meta.fields` and the edit template.
- [ ] **#34 — Import order/invoice history** — Fix and relocate `import_products.py` to `management/commands/`. Add `add_arguments` for file path. Consider replacing pandas with openpyxl (already a dependency) to drop the heavy dep.
- [ ] **#33 — Excel export broken** — Fix `InventoryExportView`. *(Also listed in Phase 1)*
- [ ] **#65 — View 3MF files in the web portal** — Use `three.js` + `Online3DViewer` (https://github.com/kovacsv/Online3DViewer). Significant work; consider as a standalone feature branch.

### New Capabilities

- [ ] **Phone camera barcode scanning** — Two approaches:
  - *Browser-based (recommended, no app needed):* Integrate `@zxing/browser` JS library; wire a camera-capture modal to the existing search/inventory flow via HTMX. Works on any phone browser.
  - *Native:* Chrome/Edge Android has a built-in `BarcodeDetector` API (no library) but Safari doesn't support it.
  - Pairs with #48 (location barcodes) — scan a LOC-XXX to pull up a location page, scan an INV-XXX to pull up an item.

- [ ] **BambuLab API integration** — Connect to printers on the local LAN via MQTT (same protocol the HACS `bambu_lab` integration uses). Key data to pull:
  - Current print job and progress
  - AMS slot assignments (which filament spool is loaded in which slot)
  - Temperatures and status
  - *Highest-value automation:* on print completion, auto-update which spool is in which AMS slot and optionally decrement estimated remaining weight.
  - Reference: HACS bambu_lab integration source for the MQTT topic structure.

- [ ] **Improved data visualizations** — Existing dashboard uses Chart.js already. Ideas:
  - Filament usage over time (requires logging consumption events)
  - Stock levels by material/color family with low-stock alerts
  - Spool weight distribution (how much of each color/material is on hand by weight)
  - Printer utilization (requires BambuLab integration)

- [ ] **Status-based location assignment** ✅ *(Already implemented in `InventoryItem.save()` via `Location.default_status` — the original todo item is done)*

### Reusable App Extraction (longer term)

- [ ] **Extract `barcode_utils.py` as a standalone `brother_ql_utils` package** — zero Django coupling, clean public API, useful beyond this project.
- [ ] **Extract polymorphic inventory core** (`Product`, `InventoryItem`, `Location`, `Material`, status-by-location) into a reusable `polymorphic_inventory` app once filament-specific logic is isolated in subclasses.

---

## Aspirational / Backlog

- [ ] Sphinx docs + GitHub Pages deployment *(original todo item — low priority)*
- [ ] Per-user inventory scoping — `user` FK was deliberately removed in migration 0013; fine for single-household use but worth revisiting if multi-user support is wanted.
- [ ] Replace SQLite with PostgreSQL if concurrent write performance becomes a concern.
- [ ] `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` driven by env vars instead of hardcoded.
- [ ] HTTPS + `SECURE_*` Django settings if the app is ever exposed outside the LAN.
