# Inline "Add Item" During Inventory Audit — Design

**Date:** 2026-06-06
**Branch context:** builds on `feat/location-system-and-audit-mode` (PR #113, audit mode).
**Status:** Approved design, pending implementation plan.

## Problem

The audit console reconciles *existing* inventory: scan a `LOC-<pk>` to focus a
location, scan `INV-<pk>` tags to confirm/move items, unscanned items at a closed
location become `UNKNOWN`, and finalize depletes the still-`UNKNOWN` set. During a
physical walk the auditor will encounter spools **not yet in inventory** (no
`INV-` tag). Today `parse_code()` only accepts `LOC-`/`INV-`, so an untracked
spool's manufacturer barcode (a bare UPC) raises `Unrecognized code`. The auditor
must leave the console, run the normal add-product flow, and return — a clumsy
context switch mid-walk.

## Goal

Let the same USB-wedge scan stream that drives the audit also handle untracked
items, **without** derailing the walk:

- **UPC already in the catalog** → mint a new `InventoryItem` at the active
  location immediately, print its `INV-` label, count it present.
- **UPC not in the catalog** → capture it to a durable queue (UPC + location) and
  move on. After the walk, a dedicated review page hands each queued UPC into the
  existing add-product flow.

No new-product *form* is embedded in the console. Phone-camera scanning is out of
scope (USB wedge confirmed for this audit).

## Decisions (locked during brainstorming)

- **Scope:** in-catalog UPCs mint immediately; unknown UPCs are queued for
  post-walk review ("in-catalog now, queue unknowns").
- **Scan discrimination:** `LOC-`/`INV-` keep prefixes; a **bare-numeric** scan is
  a UPC. Unambiguous because the prefixed codes never appear as bare digits.
- **Durability:** the unknown-UPC queue is a model, not session state — a
  multi-hour walk survives a reload/crash, matching the rest of the audit design.
- **Logic placement (Approach A):** find-or-queue + item creation live in an
  `audit.py` service; **label printing stays in the view**, mirroring the existing
  `AddInventoryView` split of logic vs. I/O side-effect.
- **Queue cleanup:** a dedicated `/audit/unknowns/` review page, reusing the
  existing `pending_inventory` → add-product handoff.

## Data model

New model `AuditUnknownScan` in `inventory/models.py`:

| Field | Type | Notes |
|---|---|---|
| `session` | FK → `AuditSession`, `CASCADE` | provenance |
| `upc` | `CharField` | the bare-numeric scanned code |
| `location` | FK → `Location`, `SET_NULL`, `null=True` | active location at scan time |
| `created_at` | `DateTimeField(auto_now_add=True)` | |
| `resolved_item` | FK → `InventoryItem`, `SET_NULL`, `null=True` | set when handoff creates the item |
| `resolved` | `BooleanField(default=False)` | |
| `dismissed` | `BooleanField(default=False)` | "not real / mis-scan" escape hatch |

New `AuditEvent.Action` member **`ADDED`** — logs an in-catalog mint so it appears
in the tally and activity feed.

Migration `0027`: additive (one new model + one new choice value). No backfill, no
NOT-NULL-without-default trap.

## Scan flow

### `parse_code()` (audit.py)

Check `LOC-`/`INV-` prefixes first; fall through to bare-numeric → `("upc", code)`.
Non-numeric, non-prefixed input still raises `AuditError`.

```
"LOC-5"   → ("loc", 5)
"INV-12"  → ("item", 12)
"079817…3"→ ("upc", "079817…3")   # bare digits
"garbage" → AuditError
```

### `audit.add_or_queue_upc(session, location, upc)` (new service)

1. `location is None` → `AuditError("Scan a location barcode first.")`.
2. `location.is_container` → `AuditError` (can't add into a rack/AMS shell).
3. `product = Product.objects.filter(upc=upc).first()`
   - **Found** → create `InventoryItem(product=product, location=location)`; status
     from `update_status()` off the location with `_skip_status_from_location=True`
     (assigned explicitly); log `AuditEvent(action=ADDED, item, location)`; return
     `("added", item)`.
   - **Not found** → `get_or_create` an **unresolved, non-dismissed**
     `AuditUnknownScan(session, upc, location)` (dedup); return `("queued", scan)`.

Dedup: re-scanning the same untracked spool at the same `(session, upc, location)`
is a no-op — mirrors the existing present-scan dedup.

### `AuditScanView` dispatch (views.py)

`kind == "upc"` → call the service, then **in the view** print the label on the
`"added"` branch:

```python
if outcome == "added":
    try:
        generate_and_print_barcode(item, mode="unique")
    except Exception as e:
        messages.warning(request, f"Label printing failed: {e}")  # non-fatal
    last_result = ("success", f"Added {item.product.name} (INV-{item.pk}).")
else:  # queued
    last_result = ("warning", f"Unknown UPC {upc} queued for review.")
```

### Present-immunity

Fold `AuditEvent.Action.ADDED` into `PRESENT_ACTIONS` so:
- a freshly-added item renders in `items_here` with the green check, and
- `close_location()`'s UNKNOWN sweep never flags it (it was just added here).

## Review page & handoff

### `AuditUnknownsView` — `GET /audit/unknowns/`, `LoginRequiredMixin`

Lists `AuditUnknownScan` rows where `resolved=False, dismissed=False`: UPC,
location name, scanned-at, and two POST actions per row. **Not** gated on an active
session — these are processed after the walk/finalize.

### Per-row actions (both POST)

- **"Add to inventory"** → `AuditUnknownResolveView`: sets
  `request.session["pending_inventory"] = {"upc": scan.upc, "location_id":
  scan.location_id, "unknown_scan_id": scan.id}` and redirects into the existing
  `add_inventory` / `add_product_choice` chain (the mechanism already at
  `views.py:356`). No new add UI.
- **"Dismiss"** → `dismissed=True`.

### Closing the resolution loop

When an `InventoryItem` is successfully created and
`request.session["pending_inventory"]` carries `unknown_scan_id`, mark that scan
`resolved=True, resolved_item=<item>` and pop the key. Extract a helper
`_resolve_pending_unknown(request, item)` called from **both** existing success
paths that consume `pending_inventory`:

- `AddInventoryView.post` (in-catalog match found) — `views.py:376`
- the product-creation flow that ends in item creation
  (`BaseAddProductView` / `add_product` success)

To avoid a stale id binding to an unrelated later add, pop `unknown_scan_id` on a
fresh `add_inventory` GET.

### Console & finalize surface

- Console/nav: an **"Unknowns (N)"** badge linking to the review page when the
  queue is non-empty.
- `_audit_context` tally gains an `added` count; `audit_body.html` gets an "Added"
  stat card.
- Finalize page: informational note **"N unknown UPCs still queued — review at
  /audit/unknowns/"** when any remain. Does **not** block finalize (queued scans
  aren't `InventoryItem`s; the deplete logic never touches them).

## Edge cases

- **No active location + UPC scan** → `AuditError("Scan a location barcode
  first.")`. No floating inventory.
- **Container active + UPC scan** → rejected server-side.
- **Duplicate untracked spool re-scanned** → `get_or_create` dedup; neutral message.
- **Same UPC at two locations** → two queue rows (different `location`) — correct,
  two physical spools.
- **Bare digits colliding with an `INV-`/`LOC-` number** → impossible; those codes
  always carry their prefix.
- **Queue location later deleted** → `SET_NULL`; row survives, review shows "—".
- **Resolve handoff abandoned** → `unknown_scan_id` lingers in session until the
  next add completes or a fresh `add_inventory` GET pops it; scan stays unresolved
  (safe — re-process worst case).
- **Audit abandoned/finalized with queue non-empty** → queue persists (session FK,
  not session state); review page still works.

## Testing (extends existing 66-test suite)

- `parse_code` UPC classification: bare digits, prefixed codes, garbage.
- `add_or_queue_upc`: in-catalog → item + `ADDED` event + present-immune at close;
  not-in-catalog → queued; dedup; no-active-location raises; container raises.
- `AuditScanView` UPC POST: added vs. queued `last_result`; label-print failure
  non-fatal.
- Review page: lists unresolved-only; dismiss hides; resolve sets
  `pending_inventory`; on item creation marks `resolved` + `resolved_item`.
- Finalize note shows iff queue non-empty; finalize still succeeds.

## Out of scope (YAGNI)

- Phone-camera scanning (USB wedge confirmed).
- Bulk queue operations; inline editing of a queued UPC.
- Any new-product form embedded in the console — unknowns always route through the
  existing add-product flow.

## Files touched (anticipated)

- `inventory/models.py` — `AuditUnknownScan`, `AuditEvent.Action.ADDED`.
- `inventory/migrations/0027_*.py` — additive migration.
- `inventory/audit.py` — `parse_code` UPC kind, `add_or_queue_upc`, `ADDED` in
  `PRESENT_ACTIONS`.
- `inventory/views.py` — `AuditScanView` UPC dispatch + print; `AuditUnknownsView`,
  `AuditUnknownResolveView`; `_resolve_pending_unknown` helper wired into existing
  add success paths; `_audit_context` `added` tally + unknown count.
- `inventory/urls.py` — `/audit/unknowns/`, `/audit/unknowns/<pk>/resolve/`,
  `/audit/unknowns/<pk>/dismiss/` (or a single resolve view handling both actions).
- `inventory/templates/inventory/` — unknowns review template; `audit_body.html`
  "Added" card + "Unknowns (N)" badge; finalize note.
- `inventory/admin.py` — optional `AuditUnknownScanAdmin` for visibility.
- `inventory/tests.py` — new tests per above.

## Dependencies / sequencing note

The audit base (PR #113, commit `0b354ef`) is **already merged to master and
deployed** (since 2026-06-02; master auto-deploys). The live DB has the audit
tables and migrations `0025`/`0026` applied. So this feature is a clean follow-up
PR branched off current `master`, with its migration `0027` stacking on the
deployed `0026`.

**However**, the post-merge prod setup for the audit base has **not** run yet
(verified 2026-06-06 against the live stack): prod has only 25 backfilled flat
`Location` rows (20 shelf / 1 dry_storage / 4 printer) — `seed_locations` never
ran, so the rack/AMS/dryer/slot hierarchy is absent, slot `unit` FKs are unlinked,
the 2 new dryers aren't added, and `LOC-`/`INV-` labels presumably aren't printed.
That setup is the real blocker to *running* the audit and is independent of this
feature.
