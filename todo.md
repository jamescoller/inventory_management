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

- [ ] `tables.py` — `InventoryItemTable` is never used in any view. Remove file and remove `django-tables2` from requirements.
- [ ] `FilamentView` in views.py + `inventory/templates/inventory/filament_view.html` — view crashes on first hit and has no URL route.
- [ ] `Order` and `Shipment` models in models.py — no views, no admin wiring, no foreign keys from live models.
- [ ] `inventory/import_products.py` — see Phase 1. If not fixed, delete.
- [ ] `inventory/templates/inventory/bulkadd.html` — contains a broken `{% url '' %}` and no route.
- [ ] `inventory/templates/inventory/delete_item.html` — URL route commented out in urls.py.
- [ ] `inventory/templates/inventory/search_results.html` — `InventorySearchView` renders `inventory_search.html` instead; this template is never rendered.
- [ ] `inventory/templates/inventory/movement.html` — no view or URL route.
- [ ] Commented-out URL patterns in `inventory/urls.py` (lines 10-12).
- [ ] `format_label` and `generate_barcode` functions in `barcode_utils.py` — in `__all__` but unused anywhere in the project.
- [ ] The hardcoded fallback printer IP `"192.168.68.93"` in `barcode_utils.py:49` — should be `None` and fail loudly rather than targeting a random LAN device.

### Fix `from X import *` antipattern

- [ ] Replace `from .models import *` in views.py with explicit imports.
- [ ] Replace `from .forms import *` in views.py with explicit imports.
- [ ] Replace `from .models import *` in forms.py with explicit imports.

### Wire up or fix signals.py

- [ ] `inventory/apps.py` `ready()` method is a no-op — signals.py is never loaded. Either:
  - Add `import inventory.signals` inside `ready()` and fix the `InventoryItem.StatusChoices` typo (should be `InventoryItem.Status`), OR
  - Delete signals.py if the logging it provides isn't needed.
- [ ] The `post_save` signal in signals.py queries `InventoryItem.objects.get(pk=instance.pk)` to get "old" state — but post_save fires after the save, so it always returns the new state. Switch to `pre_save` or store `__original_status` in `from_db`.

### Redundant boolean fields

- [ ] `depleted`, `in_use`, `sold` on `InventoryItem` are redundant with `status` and can drift if code calls `queryset.update(status=...)` directly (bypassing `save()`). Either remove the boolean fields and derive them as `@property`, or replace all `queryset.update()` calls with per-instance saves.

---

## Phase 3 — Code Quality & Architecture

### Views

- [ ] **Consolidate the 5 Add Product views** — `AddFilamentView`, `AddPrinterView`, `AddDryerView`, `AddHardwareView`, `AddAMSView` are nearly identical (~150 lines). Extract a `BaseAddProductView` mixin; reduce to ~30 lines each.
- [ ] **Fix Dashboard N+1 queries** — `Dashboard.get()` does 3 full Python-side table scans over `InventoryItem`. Replace with `values().annotate(Count(...))` aggregation queries.
- [ ] **Move UPC lookup logic out of `addInventoryView.post()`** — the "try each product subclass" loop is unnecessary; `Product.objects.get(upc=upc)` returns the polymorphic instance directly. Also extract session management for the pending-inventory flow into a helper.
- [ ] **Standardize CBV naming** — `inventoryEditView`, `addInventoryView` should be `InventoryEditView`, `AddInventoryView` (PascalCase per PEP 8).

### Models / Forms

- [ ] **Move hex validation to `Filament.clean()` + `FilamentForm.clean_hex_code()`** so invalid hex shows as a form error instead of a 500.
- [ ] **Move printer dimension validation to `Printer.clean()`** — remove `ValueError` from `Printer.save()`.
- [ ] **Fix `InventoryItem.save()` location-change detection** — the current approach does an extra SELECT on every save. Store `__original_location` in `from_db()` instead.

### Templates

- [ ] **Consolidate the 5 near-identical add-product templates** into one shared partial that accepts a title variable.
- [ ] **Fix JS load order in `base.html`** — jQuery, Bootstrap, Chart.js, HTMX are loaded at the bottom of `<body>` after `{% block content %}`. Inline scripts in child templates race against them. Move to `<head>` with `defer` or use `{% block extra_scripts %}` at the bottom.
- [ ] **Deduplicate DataTables CSS** — loaded twice in base.html (lines 17 and 44).
- [ ] **`in_use_overview.html` and `dry_storage_overview.html`** are heavily duplicated. Extract shared card + tooltip pattern into a partial.

### Admin

- [ ] **Fix `field` → `fields` typo** in `HardwareAdmin`, `DryerAdmin`, `AMSAdmin` (admin.py) — the list is silently ignored and Django shows all fields.
- [ ] **Fix `DryerAdmin.field`** — contains `'max_temp"degC'` (mismatched quotes — valid Python string but not a real field name).
- [ ] **Fix `display_product_details`** (admin.py ~line 287) — accesses `product.printer.serial_number`, `product.serial_number` etc. on models that don't have those fields → `AttributeError`.
- [ ] **Fix `ShipmentAdmin`** — incorrectly extends `ProductChildAdmin` instead of an `OrderChildAdmin`; Shipment is not a child of Product.
- [ ] **Fix `mark_depleted` admin action** — calls `queryset.update(status=...)` which bypasses `save()`, leaving `depleted`, `date_depleted`, `location` out of sync. Iterate and call `instance.mark_depleted()` instead.
- [ ] **Fix `view_log`** (admin.py ~line 358) — reads entire log file into memory to slice the last 200 lines. Use `subprocess` + `tail -n 200` or seek from end.

### Dependencies to clean up (after dead code removal)

- [ ] Remove `numpy` and `pandas` if `import_products.py` is deleted.
- [ ] Remove `django-tables2` if `tables.py` is deleted.
- [ ] Move `pre-commit` and `django-debug-toolbar` to a `requirements-dev.txt`.
- [ ] Pin `python-barcode`, `brother_ql`, `python-decouple` to explicit versions.
- [ ] Remove `setuptools` from app requirements (build tool, not a runtime dep).

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
