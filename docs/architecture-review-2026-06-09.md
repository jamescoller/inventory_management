# Architecture Review — 2026-06-09

A 10,000-ft review of the inventory app after Phases 1–10. Goal: name what's solid, what got
"slapped on" and should be reworked with hindsight, and what's missing for the intended
workflow. Findings carry `file:line` refs. The resulting work is sequenced in
[`../todo.md`](../todo.md) (Phases 11–18).

---

## 1. What's solid (keep, and copy the pattern)

- **Catalog vs. instance split is correct.** Polymorphic `Product` (Filament/Printer/AMS/
  Dryer/Hardware, `models.py:12–431`) describes *what exists*; concrete `InventoryItem`
  (`models.py:434–658`) is *what you physically own*. This is the right shape and should not
  be "simplified" away.
- **The audit subsystem is genuinely well-built.** A service module (`inventory/audit.py`)
  holding a state machine + pure functions, with **thin CBVs** that call it
  (`AuditScanView` → `audit.scan_item`, `views.py:1353`), and an **append-only `AuditEvent`**
  log. It's idempotent (CLOSED markers), input-agnostic (`/audit/scan/` takes wedge or future
  camera POST), and unit-testable. **This is the template every new subsystem should follow**
  (procurement, maintenance, print-jobs, telemetry all get their own `*.py` service module).
- **Hierarchical `Location`** with `kind`/`parent`/`unit`/`slot_index` and `descendant_ids()`
  (`models.py:660–793`) is a strong model for the physical world, and the `Location.unit`
  guard added in PR #128 (`Location.clean()`) shows the right instinct (validate at the model
  layer, not just the admin form).
- Phases 1–10 paid down real debt (dead code, wildcard imports, N+1s, XSS, a test foundation).

---

## 2. What got "slapped on" — rework candidates (highest leverage first)

### 2.1 The status/location coupling is fragile — extract a move service ⭐ top priority
`InventoryItem.save()` (`models.py:529–560`) auto-derives `status` from
`location.default_status` whenever the location changes, **unless** status is in
`STICKY_STATUSES = (DEPLETED, SOLD, UNKNOWN)` (`models.py:515`). Two transient instance flags
drive it: `_skip_status_from_location` (set by callers that already chose a status) and
`_original_location_id` (set in `from_db()`, `models.py:562`).

The problem isn't the mechanism — it's that **every writer must remember the flag**, and the
knowledge is copy-pasted:
- `audit.py:214, 253, 291, 391`
- `BulkUpdateView` (`views.py:582`)
- `InventoryItemAdmin.mark_depleted` (`admin.py:387`)

There is **no `move_to()` service**. Any new move/deplete path (quick-move, receiving,
print-job completion) becomes the next copy of the dance — and the first on a fast,
fat-fingered mobile path, which is exactly the failure class that motivated item-change-history
(`docs/item-change-history.md`).

**Recommendation (Phase 11.3):** extract `inventory/items.py`:
```
move_to(item, location, *, status=None, skip_drying_check=False) -> Result
deplete(item, *, reason="")        # wraps mark_depleted()+flag+save()
set_status(item, status)           # the one place that sets _skip_status_from_location
```
Keep the model-level guard (it's a sound guarantee, `models.py:533`); just make the flags an
*implementation detail of `items.py`* that no view sets directly. Bonus: it's the single
chokepoint that makes simple-history capture complete (Phase 13) and the home for
slot-capacity (below).

### 2.2 No slot-capacity concept
`Dryer.num_slots` / `AMS.num_slots` exist on the catalog (`models.py:336, 369`) but nothing
stops a 5th roll going into a 4-slot dryer. Container/slot rejection is itself duplicated
(`views.py:565`, `audit.py:235`). **Recommendation (11.3):** add `Location.capacity` and fold
both the capacity check and the container rejection into `move_to()`'s single guard. This is a
hard prerequisite for trustworthy scan-to-move into slots (Phase 12.2).

### 2.3 The search page's `status` filter is a dead field 🐛
`inventory_search.html:67` renders a `status` text input that `InventorySearchView` (`views.py:183–250`)
**never reads**. The base queryset also hardcodes `exclude(status=5)` (DEPLETED), so
**DEPLETED/SOLD/UNKNOWN items are literally unfindable**. There is also no way to filter by
**item type** (the polymorphic subclass is available as `product__polymorphic_ctype__model`,
used in the dashboard at `views.py:922`, but not exposed in search). This is the direct cause
of "I can't find my lost/UNKNOWN items." **Recommendation (Phase 11.2):** real status (incl.
UNKNOWN) + item-type + location-subtree filters; a "Lost & Found" preset.

### 2.4 Three overlapping filament pages
`/filament-summary/` (`FilamentSummaryView`, a **155-line** `get_context_data` + **220 lines**
of inline JS, `views.py:748–903`), `/filament-color-guide/` (`views.py:713`), and
`/filament-guide/` (`views.py:905`) overlap heavily (color × material × usage × spec).
**Recommendation (Phase 18.2):** one filament hub with modes/tabs; move the client-side
filtering server-side or into a static JS module.

### 2.5 ~435 lines of inline JavaScript, zero JS files
`inventory_search.html` (114), `filament_summary.html` (220), `dashboard.html` (95). Nothing
under `static/inventory/js/`. The code audit flagged this; it's a maintainability tax and an
accessibility/CSP liability. **Recommendation (18.2):** extract to `static/inventory/js/`,
pass context via `json_script`.

### 2.6 Drying logic coupled to `InventoryItem`
`InventoryItem.filament_drying_warning()` (`models.py:602–657`) reaches
`self.product.filament.material.drying_required` (`models.py:636`) — it only applies to
Filament, relies on polymorphic casting, and double-checks `location.kind == PRINTER or
location.is_printer` (`models.py:632`). **Recommendation:** move into a Filament/Material-aware
validator (callable from `move_to()`); drop the legacy `is_printer` boolean (`models.py:736`)
once `kind` is trusted.

### 2.7 `Material` guide-fields mix spec with UX metadata
Phase 5 bolted 9 booleans (`uv_resistant`, `flexible`, …, `requires_enclosure`,
`models.py:848–858`) onto `Material`, which otherwise holds *spec* (temps, drying). It works
and is fine to leave, but **flag**: if guide attributes keep growing, move them to a
`MaterialGuide` 1:1 (or tags) so adding one isn't a schema migration. Not urgent.

### 2.8 Smaller items
- `Location.is_printer` legacy boolean — remove after `kind` is trusted (2.6).
- `InventoryItemInline` on the Product admin (`admin.py`) lets you edit instance state from
  the catalog page — conceptually muddled; instance state belongs on `InventoryItemAdmin`.
- Audit "active location" is ephemeral in `request.session`; a lost session orphans focus
  (DB is fine). Minor; could move to `AuditSession`.

---

## 3. Missing subsystems for the intended workflow

None of these exist today; all are greenfield (designed in
[`workflow-and-domain-design.md`](workflow-and-domain-design.md)):

| Gap | Evidence | Phase |
|---|---|---|
| Order / cost / supplier | `Order`/`Shipment` deleted in migration 0020 (Phase 2); only a free-text `shipment` field remains | 14 |
| Maintenance (parts, lube, faults, hotend swaps) | no model references machine upkeep | 15.1 |
| Print-jobs / utilization / consumption | no job record; `percent_remaining` is manual | 15.2 |
| Live telemetry (AMS RFID, remaining %, printer state) | app is WSGI request/response only | 16 |
| Slot capacity | `num_slots` is catalog-only | 11.3 |

---

## 4. What we deliberately keep (don't re-litigate)
- **django-polymorphic** for Product — correct for heterogeneous catalog with shared identity.
- **SQLite** — no concurrent-write pressure *today*. Revisit **only** if Phase 16's MQTT
  writer causes measurable `database is locked` contention despite WAL (it's in `todo.md`
  Trashed with that explicit trigger).
- **The audit subsystem's design** — it's the reference, not a refactor target.
- **The transient-flag status mechanism** — relocated into `items.py` (2.1), not redesigned.

---

## 5. Effort ledger
- **Small / high-leverage:** 2.1 move service, 2.2 slot capacity, 2.3 search fix (Phases 11–12).
- **Medium:** 2.4 filament consolidation, 2.5 JS extraction (Phase 18).
- **Low-urgency / flag-only:** 2.6 drying validator + `is_printer` removal, 2.7 Material guide
  split, 2.8 admin inline cleanup.
