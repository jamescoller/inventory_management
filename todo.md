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

## Code Audit (completed 2026-05-21)

- [x] **Review complete.** Report: `docs/code-audit-2026-05-21.md`.

Summary of where the audit landed:

- **Backend Python:** healthy after Phases 1–3. Main targets are `FilamentSummaryView.get_context_data()` (split into helpers), `InventoryItem` custom QuerySet, `BaseProductForm` extraction, wiring `InventorySearchView` to `FilterView`.
- **Templates:** the weakest area as expected — ~435 lines of inline JS across `filament_summary.html`, `inventory_search.html`, `dashboard.html`. Extract to `static/inventory/js/`. Plus accessibility quick wins (aria labels, decorative `aria-hidden`).
- **Dependencies:** `pytz`, `six`, `typing_extensions` are pinned but unused — remove. `django-htmx` and `django-filter` are loaded but functionally unused — decide remove-vs-commit. Django 6.0 compatibility is clean (no deprecated APIs).
- **Quick wins** (~30 min): dead-dep removal, one admin N+1, `{% block extra_head %}`, duplicate print CSS, ARIA labels.

Quick wins completed 2026-05-22 (PR: chore/audit-quick-wins). See `docs/audit-quick-wins-2026-05-22.md` for full change log. Decisions made: `django-htmx` Python package removed (htmx CDN kept for Phase 6); `django-filter` removed (wiring FilterView deferred to medium-refactor phase). Implementation PRs follow — see Phase 4 for next steps.

---

## Phase 4 — Quick Wins & Test Foundation

Small, self-contained items plus the test coverage carryover from Phase 3. Ship as a single PR.

### Carryover from Phase 3

- [x] Add `tests.py` basics — round-trip GET per view + `save()` per model, plus targeted form/signup tests. Tests caught two latent bugs fixed in the same PR (see below).

### Cleanup

- [x] Remove barcode printer MAC discovery from `barcode_utils.py`; use only the static IP `10.10.40.2`. *(Already done in Phase 2 / commit `e8466f6`; confirmed no MAC / scapy references remain.)*

### Small Features

- [x] **#38 — Show spool boolean in inventory editor** — `has_spool` is shown as a read-only badge in the Product Details card of `inventory_edit.html` (only when product is a Filament). Added `get_real_instance()` so polymorphic subclass attributes are accessible in the template.
- [x] **#47 — Improve Item ID barcode rendering** — Bumped `initial_module_width_mm` 0.3 → 0.4, `quiet_zone_mm` 2.0 → 3.0, and raised `min_module_width_mm` 0.1 → 0.25 (GS1 Code 128 floor for handheld scanners).

### Bugs surfaced by the test foundation (fixed in same PR)

- [x] **`add_product.html` referenced non-existent URL** `'product_list'` → `NoReverseMatch` on every add-product GET when not coming from inventory. Pointed back-button at `dashboard` instead.
- [x] **Missing migration `0023_alter_material_options`** — Phase 3 added `ordering = ['name', 'material_type']` to `Material.Meta` without generating a migration. Generated now.

### Known limitation (now addressed)

- [x] 3-digit hex codes (e.g. `#F00`) — `get_color_family()` now expands 3-digit hex to 6-digit before slicing. Test added in `ModelSaveTests`. Also fixed pre-existing `InventoryItem` method ordering (DJ012 violations) while touching models.py.

---

## Phase 5 — Filament Selection Guide (Stage 1: Data Foundation)

Spec: `docs/superpowers/specs/2026-05-21-filament-guide-design.md`

Delivers the reference table immediately (useful for James). Lays the data foundation that Stage 2 (Phase 7) and the Haiku data-loading task depend on.

**Status: PR #108 open (feat/phase-5), pending merge + deploy.**

### Model

- [x] Add 10 fields to `Material`: `uv_resistant`, `flexible`, `high_strength`, `heat_resistant`, `food_safe`, `easy_to_print`, `budget_friendly`, `impact_resistant`, `requires_enclosure`, `description`. *(Spec listed 13; `requires_drying`, `drying_temp_c`, `drying_time_hours` were redundant — `drying_required`, `dry_temp_ideal_degC`, `dry_time_hrs` already existed and are reused in the template.)*
- [x] Generate and include migration `0024_material_*` (spec said 0023 but 0023 was taken by Phase 4).

### Admin

- [x] Add `Guide Properties` fieldset to `MaterialAdmin` grouping all new fields.

### View + Template

- [x] Add `FilamentGuideView` (GET, `LoginRequiredMixin`) at `/filament-guide/`.
- [x] Template: reference table via DataTables. Boolean columns render ✓ / —. `requires_enclosure` and `drying_required` use warning colour on ✓. Stage 2 placeholder comment included.
- [x] Add nav link to `navigation.html`.

### Data loading (post-deploy, separate task)

- [ ] Fill in `docs/filament-guide-data.csv` (template committed to repo, 38 rows pre-populated with exact `name`/`material_type` from live DB). Then dispatch Haiku agents to load via Django shell after PR #108 is merged and deployed.

---

## Phase 6 — Barcode & Location System

These items share the same infrastructure and ship together. Camera scanning depends on good barcodes existing first.

- [x] **Detailed location hierarchy** — `Location` gained `kind` (rack/shelf/dry_storage/ams/ams_slot/dryer/dryer_slot/printer), `parent`, `unit` (FK to the physical AMS/dryer InventoryItem), and `slot_index`; `default_status` now nullable for containers. `seed_locations` management command seeds 2 racks×5 shelves + 5 dry storage + 8 AMS×4 slots + 3 dryers×4 slots (72 rows, idempotent). Drying-warning logic now keys off `kind` instead of the hardcoded name. *Migrations 0025/0026.*
- [x] **#48 — Location barcodes (LOC-XXX)** — `LOC-{id}` is decoded by `BarcodeRedirectView` (jumps into the audit console focused there) and the audit scan endpoint; `LocationAdmin` has a "Print location labels" action reusing `generate_and_print_label`.
- [x] **Inventory audit mode** — Scan a location then the item tags present there; reconcile is per-location-immediate. New `UNKNOWN` status (durable via a `save()` sticky-status guard), `AuditSession`/`AuditEvent` models, reconcile state machine in `inventory/audit.py`, console + finalize UI (`/audit/`). Items recorded elsewhere move on scan; unscanned items at a closed location → UNKNOWN; finalize → DEPLETED. Input-agnostic scan endpoint (USB wedge now, camera later). Merged in PR #113 (squash `0b354ef`), deployed; `seed_locations` run on prod 2026-06-06. Remaining manual setup: link the 8 AMS / 3 dryer slot-groups to their unit InventoryItems in admin, add the 2 new dryers, reconcile the old flat shelves against the new rack hierarchy, print `LOC-`/`INV-` labels.
- [x] **Inline add-item during audit** — Scanning a bare-numeric UPC during the walk either mints an `InventoryItem` at the active location (catalog hit; new `AuditEvent.ADDED`, immune to the close-location UNKNOWN sweep) or queues an `AuditUnknownScan` for post-walk review at `/audit/unknowns/`, which hands each into the existing add-product flow (via `pending_inventory` + threaded `unknown_scan_id`) and marks it resolved on item creation. Migration `0027`. Separate follow-up PR off master.
- [x] **Audit field-feedback improvements (June 2026)** — Five fixes from the first real audit walks:
  1. **Mass-reprint INV tags** — search-results bulk-action bar gained a "Reprint tags" button (`BulkReprintLabelsView` at `/bulk-reprint/`) that reprints `INV-XXX` labels for the checked rows. For replacing missing/unreadable tags.
  2. **Undo mistaken adds** — a UPC scanned instead of an INV tag mints an item; the console + finalize page now list "Added this session" items with an Undo/Remove button (`audit.undo_added` → `AuditUndoAddView` at `/audit/undo-add/<id>/`, deletes the item created by the scan).
  3. **Serial-number location scan** — scanning a unit's front-panel serial focuses its location (`audit.resolve_serial`, fallback in `AuditScanView` when `parse_code` rejects). AMS/dryer serials focus the **whole unit** (container expands to all its slots); printer serials focus the single leaf. Requires the slot↔unit `Location.unit` links to be populated.
  4. **Whole-unit auditing** — the audit focus can now be a container; `audit.focus_leaves()` expands it to its assignable slots. Present/move/close all span slots; move-in lands in the lowest slot. Console shows expected/scanned/pending counts; close flash reports "N accounted for, M flagged unknown".
  5. **Keep-unknown at finalize** — per-item "keep unknown" checkbox on the finalize screen leaves a missing item `UNKNOWN` (in limbo) instead of depleting it (default stays deplete). `audit.finalize(keep_unknown_ids=…)`. For things found out of place mid-audit.
  No migrations (reuses existing models/fields).
- [ ] **#49 — Location-based views** — Build views to list all items at a location and edit an item's location from that view. *(Audit console partially covers "items at a location"; a standalone read-only location page is still open.)*
- [ ] **Phone camera barcode scanning** — Integrate `@zxing/browser` JS library; wire a camera-capture modal. The audit scan endpoint is already input-agnostic (a camera JS POST of the decoded code hits the same `/audit/scan/`). Scan LOC-XXX → location page; scan INV-XXX → item page.

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

## Phase 9 — Field-identified fixes & search improvements (June 2026)

*Found during the first real inventory walks/testing. The bugs below affect
day-to-day use and should be picked up ahead of Phases 7–8. File:line refs as of
2026-06-08.*

### Bugs

- [ ] **`/filament-color-guide/` "spools on hand" counts color/SKU groups, not spools** — Header shows ~165 while the Dashboard shows ~478. `FilamentColorGuideView` sets `context["total_filaments"] = len(filaments)` (`views.py:706`), i.e. the number of distinct `Filament` rows with active stock — not the spool count. The true total is already computed lower in the same view as `grand_total_rolls = sum(r["on_hand"] for r in rows)` (`views.py:861`). Fix: drive the header from the sum of active inventory items (≈ `grand_total_rolls`), not the group count. Template renders `{{ total_filaments }} spool…` at `filament_color_guide.html:26,36`.
- [ ] **"Add inventory" hangs when the label printer is unreachable** — Should time out, add the item anyway, and warn that the label didn't print. The item *is* already created and the print call *is* wrapped in try/except with a "Label printing failed" warning (`AddInventoryView`, `views.py:388`), so data is safe. The hang is in `print_label_image` → `BrotherQLBackendNetwork(BROTHER_QL_HOST)` (`barcode_utils.py:356,391`): the TCP socket has **no timeout**, so an unreachable printer blocks the request for the full OS TCP timeout (~1–2 min) before the exception fires. Fix: fail fast — add a short connection timeout / pre-flight reachability probe (socket to `BROTHER_QL_HOST:9100`, ~2 s) in `barcode_utils`; the existing warning then surfaces immediately. Applies to all print sites (add, reprint, bulk, admin actions).
- [ ] **Low-stock alerts flag items that still have rolls (catalog-variant splitting)** — e.g. "out of stock: PLA Basic Black" while a name search shows several rolls. **Mechanism is not UPC-vs-SKU as first suspected:** `_build_low_stock_alerts` already groups by `product__sku` (`views.py:607`), not UPC. The real cause is the *same physical filament existing as multiple `Product`/`Filament` rows with different SKUs* (refill vs with-spool; vendor UPC/SKU churn spawns new Product rows), so one empty SKU variant fires the alert while another variant holds the stock. Fix needs a decision on canonical product identity: group low-stock on a stable key and/or dedupe/merge catalog variants. First step: inspect prod data — are the "PLA Basic Black" variants the same SKU or different SKUs? (`ssh inventory-manager 'docker exec … python manage.py shell'`). Relates to the multi-UPC-per-SKU modelling question generally.

### Enhancements

- [ ] **Hierarchical location search (nav bar + `/search/`, parent → descendants, `LOC-{id}`)** — Search inventory by location, expanding containers to their whole subtree.
    - *Current state:* `/search/` already has a flat Location text filter (`location__name__icontains`, `views.py:200`); the nav-bar single search also ORs `location__name__icontains` (`views.py:187`); a scanned/typed `LOC-<id>` is decoded by `BarcodeRedirectView` and jumps into the **audit console**, not search results.
    - *Wanted:* (1) nav bar searches by location name **and** `LOC-{id}` → list inventory at that location; (2) the `/search/` Location field does the same; (3) **parent → descendant expansion** — searching a container (e.g. "AMS RP-1", a rack, dry storage) returns items in all descendant leaf locations (slots/shelves), not just exact matches.
    - *Approach:* use the existing `Location` hierarchy (`parent`/`children`, `Location.kind`) to collect the matched location's descendant ids, then filter `location_id__in=<subtree>`. Decide how typed `LOC-{id}` in *search* coexists with the audit-console redirect (e.g. only redirect for hardware scans; treat a typed `LOC-` as a search filter).

### Chores

- [ ] **Clear the 16 pre-existing djlint errors in `inventory_search.html`** — Mostly `H021` (inline styles on the sticky bulk-action bar), plus `H014` (extra blank line before `</form>`) and `T003` (unnamed `{% endblock %}`). The template fails the `djlint-django` pre-commit hook at HEAD; PR #120 was committed with `--no-verify` because of this. Fix: extract the inline styles into a CSS block/classes, drop the stray blank line, and name the endblock (`{% endblock content %}`). Config: `pyproject.toml [tool.djlint]`.

---

## Completed Features

- [x] **Bulk inventory editor** — Checkbox selection on Search Inventory page; sticky action bar for bulk status/location/shipment changes. `POST /bulk-update/` (`BulkUpdateView`). JS `Set` as selection source of truth (survives DataTables pagination). Iterates `item.save()` to preserve all side-effects.
- [x] **Filament summary view** — `/filament-summary/` (`FilamentSummaryView`). Material cards sorted by roll count; DataTables with material/subtype/color-family filter dropdowns; period toggle (7d/30d/1y) for usage; `material_type` field on `Material` (migrations 0021/0022).
- [x] **Improved data visualizations** — Dashboard: 3 charts + low-stock alert table with urgency tiers. `/filament-color-guide/` page grouped by color family, printable as PDF.
- [x] **Status-based location assignment** — Implemented in `InventoryItem.save()` via `Location.default_status`.

---

## Backlog

Items with real value but no current phase slot. Revisit during sprint planning.

- [x] **Containers don't auto-start after host reboot** — Root cause: the `nginx` service had no `restart:` policy, so after a host/LXC reboot the daemon brought `web` (`restart: always`) back but left nginx down, making the app unreachable on `:8080`. Set both services to `restart: unless-stopped` in `docker-compose.yml`. Docker daemon confirmed `enabled` on the app LXC, so no systemd change needed. (fix/compose-restart-policy)
- [ ] **Back up the inventory database to the Synology NAS** — The live SQLite DB (`~/inventory_db.sqlite3` on the app LXC `10.10.20.17`, bind-mounted into the `web` container per `docker-compose.yml`) has no backup: single copy, not version-controlled, holds manually-entered data that can't be re-derived. `deploy.sh` doesn't touch the file, but there's no safety net against loss/corruption. **Target: Synology NAS, Volume 1.** Approach: cron a consistent snapshot with SQLite's online backup (`sqlite3 "$DB" ".backup '/tmp/...'"` or `VACUUM INTO`, both safe against a live writer — never `cp` the live file) to a timestamped file, rotate (e.g. keep N daily / M weekly), and land it on Volume 1. Decide the transport: mount an NFS/SMB share on the app LXC and write directly, `rsync`/`scp` to the NAS, or a NAS-side pull (Synology Hyper Backup / scheduled `rsync` from the app LXC) — NAS-side pull avoids storing NAS creds on the LXC. Confirm the NAS share path / IP and credentials before implementing. Optionally verify restores periodically.
- [ ] **`sudo` missing on the app LXC** — `jcoller` is in the `sudo` group but the `sudo` binary isn't installed, and polkit denies `systemctl reboot` for non-root SSH sessions — so Claude Code (and any non-root automation) can't perform privileged ops on `10.10.20.17`. Decide on an approach: install `sudo` with a narrow NOPASSWD rule (e.g. just `systemctl reboot`/`docker`), drive privileged ops from the Proxmox host via `pct exec`/`pct reboot`, or leave manual. Think before granting standing privilege.
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
