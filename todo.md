# Inventory Management — TODO / Roadmap

Forward work is grouped into **Phases 11–18**, dependency-ordered. Within a phase, bugs
before enhancements. Completed Phases 1–10 are preserved in **[Archive](#archive--completed-phases-110)**
at the bottom. File:line references reflect the codebase as of June 2026.

> **How this roadmap was built:** a 10,000-ft review on 2026-06-09 (see
> [`docs/architecture-review-2026-06-09.md`](docs/architecture-review-2026-06-09.md)).
> Supporting design docs: [workflow & domain](docs/workflow-and-domain-design.md),
> [Bambu MQTT](docs/bambu-mqtt-integration.md), [admin 2.0](docs/admin-2.0.md),
> [filament data pipeline](docs/filament-data-pipeline.md), and brainstorm/wireframes in
> [`ideas.md`](ideas.md).

---

## Where James's 11 initiatives land

| # | Initiative | Phase |
|---|---|---|
| 1 | Filament data (drying/plate/hot-end), guide build, hex fill, color sheets | **17** |
| 2 | Search page redo (filters: location, type, status incl. UNKNOWN) | **11.2** |
| 3 | Phase 6 #49 — location-based views | **12.1** |
| 4 | Phone camera barcode scanning | **12.3** |
| 5 | Phase 10 — item change history | **13** |
| 6 | Back up the inventory DB | **11.1** |
| 7 | Bambu MQTT integration | **16.1 / 16.3** |
| 8 | Grafana dashboard in HA | **16.2** |
| 9 | Bambu Store quick-link (+ price) | **17.4** (price → Trashed) |
| 10 | Printer utilization from Bambu MQ | **15.2** (manual) / **16.3** (auto) |
| 11 | Maintenance tracking (printers/AMS/dryers) | **15.1** |

Plus rework/additions from the review: the `move_to()`/slot-capacity **Foundation** (11.3),
quick scan-to-move (12.2), full **Procurement** (14), print-job log (15.2), filament-page
consolidation + inline-JS extraction (18.2), and the **visual/UX beauty** pass (18.3).

---

## Phase 11 — Safety Net & Search
*Daily-driver priority. Low risk, mostly parallelizable. 11.3 gates Phase 12.*

### 11.1 — Back up the SQLite DB to the NAS  *(item #6)*
- [ ] Cron a **consistent** snapshot (`sqlite3 "$DB" ".backup '…'"` or `VACUUM INTO` — never
  `cp` a live file) → timestamped file, rotate (keep N daily / M weekly), land on **Synology
  Vol 1**.
- [ ] Decide transport: NFS/SMB mount on the app LXC + direct write, `rsync`/`scp`, or a
  NAS-side pull (Hyper Backup) — NAS-side pull avoids storing NAS creds on the LXC.
  **Ask James:** confirm share path / IP / credentials.
- [ ] Optionally verify restores periodically.
- *Why first:* the live DB holds hand-entered data that can't be re-derived; it's the
  prerequisite safety net before Phase 16 adds a sustained writer.

### 11.2 — Search page redo  *(item #2)*
- [x] **Bug — the `status` filter is dead.** The template rendered a `status` text input
  (`inventory_search.html:67`) that `InventorySearchView` never read; the view hardcoded
  `exclude(status=5)` so **DEPLETED/SOLD/UNKNOWN were unfindable**. Fixed: hardcode removed;
  `status` is now a real multi-select. Default view still hides DEPLETED/SOLD noise but keeps
  UNKNOWN — and all three are selectable.
- [x] Real filters: **status** (multi-select, incl. UNKNOWN/SOLD/DEPLETED), **item type**
  (Filament/Printer/AMS/Dryer/Hardware via `product__polymorphic_ctype__model`), **location
  subtree** (reuses the `_expanded_location_ids` / `Location.descendant_ids()` helper),
  date-added range (`date_from`/`date_to`).
- [x] **"Lost & Found" preset** — `?preset=lost_found` → `status=UNKNOWN` ∪ items with no
  location (left at a retired/empty location). One-click button on the search page; serves
  the audit-recovery workflow.
- [x] Implementation: clean Q-objects in a refactored `InventorySearchView` (NO django-filter
  re-added). Status/type choices built from the model. Filtering extracted to a shared
  `_filtered_search_items()` so the Excel export honours the same filters (it had the same
  dead `exclude(status=5)` bug). Inline JS extracted to
  `inventory/static/inventory/js/inventory_search.js`.

### 11.3 — Foundation refactor  *(gates Phase 12; non-behavioral, high blast radius)*
- [x] Extract `inventory/items.py`: `move_to(item, location, *, status=None, …)`,
  `deplete(item, *, reason="")`, `set_status(item, status)` — these **own** the
  `_skip_status_from_location` / sticky-status dance that is currently copy-pasted across
  `audit.py` (214, 253, 291, 391), `BulkUpdateView` (`views.py:582`), admin (`admin.py:387`).
  Keep the model mechanism (`models.py:529–560`); just relocate it so **no view touches the
  flags**.
- [x] Add `Location.capacity` (PositiveSmallInteger, null=unlimited; slots default 1) +
  fold the container/slot rejection (duplicated in `views.py:565`, `audit.py:235`) into the
  one move guard.
- [x] Strong tests — the audit reconcile suite is the canary; a subtle change here can
  silently corrupt reconciliation or re-derive a depleted item's status.

---

## Phase 12 — Quick-Move & Phone Scanning
*The everyday workflow. Depends on 11.3. See wireframes B/C in [`ideas.md`](ideas.md).*

### 12.1 — Location detail page  *(item #3 / Phase 6 #49)*
- [x] Read-only "what's here" list for a location (+ its subtree for containers), reachable
  from a scanned `LOC-` and from search. Inline "edit this item's location" + "edit location".
- [x] AMS/Dryer render as a **slot map** (see 12.x / ideas) showing slot occupancy.

### 12.2 — Quick scan-to-move  *(workflow §3; no audit session)*
- [ ] Phone-first flow: scan item (INV/QR) → item card → scan destination (`LOC-`/serial) →
  `move_to()`; status follows the destination's `default_status`.
- [ ] **Slot-capacity guard (item #3.1):** if the destination slot/unit is full, prompt
  *"what's leaving to make room?"* (evict-and-place vs pick-another).
- [ ] Drying-safety reuse: surface `filament_drying_warning()` on the move (wet filament →
  dry storage blocked; → printer warned).

### 12.3 — Phone camera barcode scanning  *(item #4)*
- [ ] `@zxing/browser` camera modal → POST decoded code to the already input-agnostic
  `/audit/scan/` and the new quick-move endpoint. Scan `LOC-` → location page; `INV-` → item.
- [ ] **Add QR labels alongside Code128** — phone cameras decode QR far more reliably than
  1-D barcodes; keep human-readable text. (Brother QL label template change.)
- [ ] PWA "add to home screen" (manifest + icons already exist) for one-tap field access.

---

## Phase 13 — Item Change History  *(item #5 / Phase 10)*
*Lands right after 11.3 so the `move_to()` chokepoint makes capture complete by construction.*
- [x] `django-simple-history` (≥3.11.0). **Full design + plan already decided** in
  [`docs/item-change-history.md`](docs/item-change-history.md): all-field capture in DB;
  **location+status timeline** on the public item page (via `diff_against(included_fields=…)`);
  admin history + revert (free). No actor tracking in v1 (middleware is a near-free later
  add); start fresh, no backfill.
- [x] New dependency → image rebuild (James accepted the dep gate). Distinct from
  `AuditEvent` (audit-session log) — they coexist.

---

## Phase 14 — Procurement & Receiving  *(full; cost-tracking workflow §1–2)*
*Re-introduces the cost layer deleted with Order/Shipment in Phase 2, properly normalized.
Models in [`docs/workflow-and-domain-design.md`](docs/workflow-and-domain-design.md).*
- [x] Models: `Supplier`, `PurchaseOrder` (+status, ordered/expected dates, shipping, tax),
  `PurchaseOrderLine` (qty ordered/received, `unit_cost`, **`track_individually`** flag —
  False = cost-only consumables like screws), `PurchaseReceipt` (+ **file attachment**,
  inert — see infra bullet), `PurchaseReceiptLine`. *(migration `0029`)*
- [x] **Receiving console** — scan items against a PO → mint `InventoryItem`s into the
  receiving rack via `move_to()` + print `INV-` labels + increment received/reconcile.
  Reuses the input-agnostic scan pattern from `AuditScanView` (`procurement.py` service).
- [x] **Per-item `unit_cost`** on `InventoryItem` (+ `source_line` FK) — what you *paid*
  (varies by sale/bulk), distinct from catalog `Product.price`. Spend reports union
  `Sum(InventoryItem.unit_cost)` (tracked) + cost-only line totals (consumables).
- [x] Reconciliation view (ordered vs received vs outstanding; order totals) + spend report.
- [ ] **Infra (flag, DEFERRED):** `PurchaseReceipt.file` upload needs `MEDIA_ROOT`/`MEDIA_URL`
  (not set today) + an nginx alias + a bind-mounted `media/` volume in `docker-compose.yml`
  (mirror the `ha-stats` mount). The `FileField` is defined but inert; no settings/widget/
  nginx/compose changes were made — James's call.

---

## Phase 15 — Maintenance & Print Logs  *(machine lifecycle; 15.1 ‖ 15.2)*

### 15.1 — Maintenance tracking  *(item #11)*
- [x] `MaintenanceEvent` on the machine `InventoryItem` (kind: fault/repair/part-replace/
  lubricate/clean/calibrate/hotend-swap/firmware/inspect; severity; cost; downtime;
  `hms_code` for the later MQTT link; `part`→Hardware product; `resolved`). Per-printer
  `NozzleConfig` (current nozzle diameter/type + last-swap) for "nozzle size changed".
- [x] **Reliability / "rebuy-or-refund" dashboard** — faults/unit/month, downtime, maint $,
  MTBF, grouped by model (the brief's headline ask: *should I replace / refund / rebuy?*).
- [x] Per-unit maintenance timeline reachable from the item page; admin inline.

### 15.2 — Print-jobs & utilization  *(item #10, manual side)*
- [x] `PrintJob` (printer, file name, start/end, duration, result, source=MANUAL|MQTT) +
  `PrintJobFilament` (spool, AMS slot, grams/% used). Manual entry first.
- [x] Completion decrements `InventoryItem.percent_remaining` → `deplete()` at ~0.
  **Subsumes the `ConsumptionEvent` backlog** — this *is* the consumption log.
- [x] Utilization view: printer hours, job count, success %, kg consumed by material/color.

---

## Phase 16 — Bambu MQTT (phased)  *(items #7/#8/#10-auto; needs 11.1 + WAL infra)*
*Phased per James: **telemetry mirror first**, auto-sync later. Full design in
[`docs/bambu-mqtt-integration.md`](docs/bambu-mqtt-integration.md).*

### 16.1 — Telemetry mirror (read-only)
- [ ] Models: `PrinterDevice` (serial, ip, access_code, optional `item` link),
  `PrinterState` (latest snapshot, upserted), `AMSChannelState` (per slot: tray_uuid/RFID,
  type, color, remaining %), `TelemetrySample` (down-sampled time-series).
- [ ] **MQTT consumer = a 3rd `docker-compose` service** running `manage.py
  run_telemetry_consumer` (`paho-mqtt`, TLS 8883, user `bblp`, per-printer access code,
  topic `device/{serial}/report`). New dep — flag.
- [ ] **Infra (central):** enable **WAL + busy_timeout**; change the compose mount from the
  single `.sqlite3` file to its **containing directory** so `-wal`/`-shm` are shared.
  Down-sample `TelemetrySample` (on-change / interval) to protect SQLite. **Decoupled from
  `InventoryItem` in this phase** (no writes to inventory).

### 16.2 — Grafana / HA dashboard  *(item #8)*
- [ ] Extend the **existing** `scripts/ha_stats_export.py` (already reads SQLite read-only →
  atomic JSON, served by nginx at `/ha-stats/`, cron 5 min) with a `telemetry.json`. HA +
  Grafana panels. Low friction — reuses a proven, deployed pipeline.

### 16.3 — Auto-sync  *(item #7 phase-2, #10-auto; gated on telemetry trusted)*
- [ ] Match AMS `tray_uuid`(RFID) → `InventoryItem.serial_number`; write serial +
  `percent_remaining`. Auto-create `PrintJob`s from MQTT; utilization from MQ. HMS errors →
  open `MaintenanceEvent(kind=FAULT, resolved=False)`.
- [ ] **Trust gate:** dry-run matcher logs *proposed* writes before any are enabled
  (same damage class as the Audit-15 mis-scan, but automated and unattended).

---

## Phase 17 — Filament Data, Guide & Color Sheets  *(item #1; finishes Phase 5/7; item #9)*
*Source files now in repo (`filament_TDS/`, `filament_hex/`, `filament-guide-en.pdf`).
Pipeline in [`docs/filament-data-pipeline.md`](docs/filament-data-pipeline.md). Needs a
dev-time PDF lib (`pypdf`) — not a production image dep.*

- [x] **17.1 TDS → specs (schema + parsers).** Added `build_plate_compat` +
  `hot_end_compat` to `Material` (migration `0028`); `inventory/filament_tds.py` parses
  `filament_TDS/*.pdf` (dev-only `pypdf`) and `parse_filament_tds` writes a **review CSV**
  to gitignored `filament_review/` — no DB writes. Backfilling existing `Material` rows is
  the human-gated next step (review the CSV, then run a loader).
- [ ] **17.2 Hex fill.** Parse `filament_hex/` — **text PDFs** (`pypdf`) and **website-
  screenshot PNGs** (vision/OCR; confirmed readable) → color→hex map → fill missing
  `Filament.hex_code`/`color_family`; seed a color catalog.
- [ ] **17.3 Guide build (Phase 7 picker).** Use `filament-guide-en.pdf` +
  `docs/filament-guide-data.csv` to populate `Material` guide booleans/descriptions, then
  ship the requirements picker (8 checkboxes, JS scoring, match cards) on `/filament-guide/`.
- [ ] **17.4 Color sheets + Bambu Store link (item #9).** Generate printable per-material
  color-reference PDFs (Bambu-style), **especially new ones for the PNG-only types**. Add a
  "View in Bambu Store" link via SKU. *(Live price scraping stays Trashed — no public API.)*

---

## Phase 18 — Visual & Admin Polish

- [ ] **18.1 Admin 2.0** — adopt **`django-unfold`** (Tailwind, responsive, modern dashboard;
  drop-in — existing `list_display`/`fieldsets`/actions/polymorphic/inline code carries over,
  ~2–3 h). Do **last** so it re-skins the *final* admin set (procurement/maintenance/telemetry)
  once. See [`docs/admin-2.0.md`](docs/admin-2.0.md).
- [x] **18.2 Filament-page consolidation + JS extraction** — `/filament/` hub (`FilamentHubView`)
  with mode tabs; the three pages (`/filament-summary/`, `/filament-color-guide/`,
  `/filament-guide/`) keep their own URLs and each carries the shared tab bar (additive,
  reversible). Extracted summary JS (220 lines) → `static/inventory/js/filament_summary.js` and
  dashboard JS (95 lines) → `static/inventory/js/dashboard.js`, both via `{% static %}` with
  server data passed through `json_script`. Search JS (114 lines, `inventory_search.html`)
  deferred to the parallel `feat/search-redo` branch that owns that file.
- [ ] **18.3 Visual beauty pass** — design tokens (replace hardcoded chart/badge colors),
  mobile polish (charts/bulk-bar/print buttons), component consistency, optional dark mode.

---

## Dependency map & parallelization

```
11.1 backup ─┐                         (urgent; gates 16.1 deploy)
11.2 search ─┼─ parallel
18.2 js/consolidate ─┘
11.3 foundation ──► 12.1/12.2/12.3 ──► (quick-move, camera)
                └─► 13 history
14 procurement   (independent; cleaner after 11.3)
15.1 maint ‖ 15.2 jobs   (after 11.3)
16.1 telemetry ──► 16.3 auto-sync     (16.1 needs 11.1 + WAL; 16.3 needs 15.2 target)
   16.1 ──► 16.2 grafana
17 filament data  (needs Phase-5 data; otherwise independent)
18.1 admin-2.0    (LAST among admin-touching work)
```
**Highest-risk:** (1) MQTT SQLite write-concurrency + new process; (2) the `save()` refactor's
blast radius; (3) MQTT auto-sync writing back to real inventory.

---

## New Ideas
- [ ] Expose "status" in the inventory item edit pages `/edit/`
- [ ] Expose full system log in the admin panel; filterable and sortable 

## Fixes 
- [ ] On the `/edit/` pages with hardware (AMS, Printers, Dryers) that have the `Maintenance` option, the button itself for `Maintenance` does not match the styling of the other buttons. 
- [ ] Error on utilization table: `DataTables warning: table id=utilization-table - Incorrect column count. For more information about this error, please see http://datatables.net/tn/18`
- [ ] Error on the print job table: `DataTables warning: table id=print-job-table - Incorrect column count. For more information about this error, please see http://datatables.net/tn/18`
- [ ] Error in the orders table: `DataTables warning: table id=po-table - Incorrect column count. For more information about this error, please see http://datatables.net/tn/18`
- [ ] Fix static image needs that log warnings in the app log:
	- [ ] `django.request WARNING 2026-06-09 18:04:42,262 log 10 137358581200576 Not Found: /favicon.ico`
	- [ ] `django.request WARNING 2026-06-09 18:04:42,280 log 10 137358616917696 Not Found: /apple-touch-icon.png`
	- [ ] `django.request WARNING 2026-06-09 18:04:42,358 log 9 137358616917696 Not Found: /apple-touch-icon-precomposed.png`
	- [ ] 

## Backlog
*Real value, no current phase slot. Revisit during sprint planning.*

- [ ] **`sudo` missing on the app LXC** — `jcoller` is in `sudo` group but the binary isn't
  installed; polkit denies `systemctl reboot` for non-root SSH. Decide: narrow NOPASSWD rule,
  drive privileged ops from the Proxmox host via `pct exec`, or leave manual.
- [ ] **#33 — Excel export** — Fix `InventoryExportView`. Low priority; not regularly used.
- [ ] **#34 — Import order/invoice history** — Largely **superseded by Phase 14** (procurement);
  only the *historical* invoice import remains, and only if bulk back-entry is wanted. Replace
  pandas with openpyxl, relocate to `management/commands/`.
- [ ] **#65 — View 3MF files in web portal** — `three.js` + `Online3DViewer`. Significant JS
  bundle for a household app; revisit if 3MF browsing becomes a real need.
- [ ] **`ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS` from env vars** — Low urgency; only matters
  with a new deployment URL.
- [ ] **HTTPS + `SECURE_*` settings** — Only if the app is ever exposed outside the LAN.

---

## Trashed
*Evaluated and set aside. Kept so they don't get re-proposed.*

- **Reusable app extraction** (`barcode_utils`, `polymorphic_inventory`) — premature abstraction
  for a single-dev household app.
- **Polar/radar charts for filament guide** — impressive but adds cognitive overhead; badge
  chips are more scannable.
- **Sphinx docs + GitHub Pages** — no audience.
- **SQLite → PostgreSQL migration** — no concurrent write pressure *yet*. **Revisit if the
  Phase 16 MQTT writer causes measurable `database is locked` contention** despite WAL.
- **Per-user inventory scoping** — `user` FK deliberately removed in migration 0013.
- **Bambu Store price scraping + HA sale alerts** — no public store API; scraping is fragile.
  The quick-link (17.4) is the right scope.

---
---

# Archive — Completed Phases 1–10

*Preserved for context. Phase-by-phase narrative also lives in `CLAUDE.md`.*

## Phase 1 — Critical Bug Fixes  *(May 2025, PR #79)*
- [x] Search crashed every request — added `import re`.
- [x] Barcode print redirect — `pk=` → `item_id=` (`PrintBarcodeView`, `BarcodeRedirectView`).
- [x] Every new Printer crashed on save — added bed-dim fields to `PrinterForm`.
- [x] Admin dropdowns crashed on null Material — guarded `Filament.__str__`.
- [x] Bulk-update material action — `new_matl` → `material`.
- [x] Hex normalization regex — match the `#`-stripped value.
- [x] Drying warning never fired — `"NEW"` → `self.Status.NEW`.
- [x] `DEBUG` cast — added `cast=bool`.
- [x] Excel export — guarded null `item.location`.
- [x] Deleted orphaned `import_products.py`.
- [x] **Security:** debug toolbar wrapped in `if DEBUG`; stored XSS via chart labels
  (`json_script`) and tooltip HTML (`escape()`); added `LoginRequiredMixin` to 4 views.

## Phase 2 — Dead Code Removal & Cleanup  *(May 2026, PRs #80/#81)*
- [x] Deleted `tables.py` + django-tables2; `FilamentView` + template; **`Order`/`Shipment`
  models** (migration 0020 drops tables); 4 dead templates; dead URL patterns;
  `format_label`/`generate_barcode`; stale printer IP fallback.
- [x] Replaced `from .x import *` in views/forms; wired `signals.py` in `apps.ready()`
  (`post_save`→`pre_save`); converted `depleted`/`in_use`/`sold` to `@property` (cols dropped).
- [x] Hotfix #81: missed transitive import → 502 (the `User` wildcard lesson in CLAUDE.md).

## Phase 3 — Code Quality & Architecture  *(May 2026, PR #82 + #92/#95)*
- [x] Explicit imports in admin; fixed `field`→`fields` typos (Hardware/Dryer/AMS admin);
  `'max_temp"degC'` typo; `display_product_details` reverse-accessor bug; `mark_depleted`
  action iterate+save; `view_log` via `tail -n 200`.
- [x] Hex validation → `clean()` + form; printer dims → `Printer.clean()`; `from_db()`
  `_original_location_id` (no extra SELECT); `BaseAddProductView` mixin; PascalCase CBVs;
  polymorphic UPC lookup; Dashboard N+1 → DB aggregations; consolidated add-product templates;
  `base.html` JS order; `requirements-dev.txt`.
- [x] Filament summary (`/filament-summary/`) + `material_type` (migrations 0021/0022) + card
  sort, hex fixes, filters, period toggle (PRs #92/#95).

## Code Audit  *(2026-05-21 → `docs/code-audit-2026-05-21.md`)*
- [x] Review complete; quick wins landed 2026-05-22 (`docs/audit-quick-wins-2026-05-22.md`).
  Decisions: removed `django-htmx` (CDN kept) and `django-filter` (FilterView wiring deferred —
  **now scheduled in 11.2**). Backend healthy post 1–3; templates are the weakest area
  (~435 lines inline JS — **scheduled in 18.2**).

## Phase 4 — Quick Wins & Test Foundation  *(May 2026, PR #100)*
- [x] `tests.py` round-trip per view + `save()` per model (caught 2 latent bugs); confirmed
  MAC discovery already removed; `has_spool` badge + `get_real_instance()`; barcode render
  params bumped; `add_product.html` `NoReverseMatch` fix; migration `0023`;
  `get_color_family()` 3-digit hex expansion.

## Phase 5 — Filament Selection Guide (Stage 1: Data Foundation)  *(May 2026, PR #108)*
- [x] Added 10 guide fields to `Material` (migration 0024); `MaterialAdmin` Guide fieldset;
  `FilamentGuideView` at `/filament-guide/` (DataTables reference); nav link; CSV template at
  `docs/filament-guide-data.csv`.
- [ ] **Data loading carryover → folded into Phase 17.3** (fill the guide data from
  `filament-guide-en.pdf` + CSV).

## Phase 6 — Barcode & Location System  *(June 2026, PR #113 + follow-ups)*
- [x] **Location hierarchy** — `kind`/`parent`/`unit`/`slot_index`, nullable `default_status`;
  `seed_locations` (72 rows); drying logic keyed off `kind`. Migrations 0025/0026.
- [x] **#48 Location barcodes** (`LOC-`), **audit mode** (`AuditSession`/`AuditEvent`,
  `inventory/audit.py` state machine, `/audit/` console, `UNKNOWN` status + sticky guard),
  **inline add-item** (`AuditUnknownScan`, migration 0027), **field-feedback fixes** (mass
  reprint, undo adds, serial-scan, whole-unit audit, keep-unknown), **`Location.unit` guard**
  (PR #128).
- [x] **#49 location-based views → Phase 12.1.**
- [ ] **Phone camera scanning → Phase 12.3.**
- [ ] *Remaining manual prod setup:* link AMS/dryer slot `unit` FKs, add 2 new dryers,
  reconcile old flat shelves vs new rack hierarchy, print `LOC-`/`INV-` labels.

## Phase 7 — Filament Guide (Stage 2: Requirements Picker)
- [ ] **→ Phase 17.3** (depends on the Phase 17.1/17.3 data load).

## Phase 8 — Data Visualizations
- [ ] Spool weight distribution → fold into 18.3 / filament hub. **Usage-over-time is now
  delivered by Phase 15.2** (`PrintJobFilament` is the consumption log; `ConsumptionEvent`
  no longer needed).

## Phase 9 — Field-identified fixes & search improvements  *(June 2026)*
- [x] `/filament-color-guide/` spool-count fix (PR #121); add-inventory printer-timeout
  fast-fail (PR #122); low-stock false positives (PR #124); hierarchical location search
  (PR #123); djlint cleanup (PRs #125/#127).

## Phase 10 — Item change history  *(approach decided 2026-06-09)*
- [x] **→ Phase 13** (django-simple-history; design in `docs/item-change-history.md`).

## Completed Features
- [x] **Bulk inventory editor** — checkbox select + sticky action bar; `POST /bulk-update/`.
- [x] **Filament summary** — `/filament-summary/` (cards by roll count; DataTables filters;
  period toggle).
- [x] **Improved visualizations** — Dashboard 3 charts + low-stock tiers; `/filament-color-guide/`.
- [x] **Status-based location assignment** — `InventoryItem.save()` via `Location.default_status`.
- [x] **Containers don't auto-start after reboot** — `restart: unless-stopped` on both services.
