# Phase 16.3 — Spool-sync reconciliation page (design)

**Date:** 2026-06-21
**Status:** design, approved (pending spec review)
**Scope:** A live, staff-facing web page that renders the spool-sync per-slot comparison
(inventory vs. Bambu AMS telemetry) and lets the user resolve each discrepancy **one at a
time, git-merge style** — choosing which side is authoritative. This is the **interactive
write surface** for Phase 16.3: it crosses the trust gate, but only via per-item,
human-clicked writes (never a blanket apply).

Builds on the merged dry-run matcher (`inventory/spool_sync.py`, `inventory/bambu_mqtt.py`,
`sync_spools`; PR #174). The read-only `sync_spools` command stays as-is for CLI/diff use;
this page is the interactive companion.

---

## 1. Problem & evidence

The dry-run matcher works (prod-verified 2026-06-21: bridge 10/10, 11 matches, 6
color-mismatch, 8 missing-item, 3 inventory-only, 3 slot-overfilled). But its only output is
a JSON artifact in the telemetry container's ephemeral `/tmp` + a stdout summary — there is
**no durable place to view it and no way to act on it**. Reviewing means SSH + `docker exec`
+ a file copy.

What the user actually wants: open a page, see every slot with INV vs MQTT side by side
(material + color swatch), and click to resolve each mismatch — like resolving merge
conflicts. The resolution is **not** always "trust the printer": real cases from live data —

- **Non-Bambu rolls (Polymaker ASA on H2Laser):** the AMS color was set by hand and is wrong;
  **inventory is correct** → keep INV.
- **Near-miss colors (e.g. RuPaul `#f55a74` vs `#f5547c`):** same color, the hex drifted;
  the user decides whether the hex genuinely changed (take MQTT) or it's noise (keep INV).
- **Inventory-only slots:** a roll physically in the AMS that the Bambu system never
  registered; **inventory is correct**, the AMS just doesn't see it → acknowledge.
- **Bambu RFID matches:** the printer read a real tag; **learn it** (write the serial +
  remaining %).

So the page is a two-way reconciler with a memory of "I decided INV is right here," not a
one-way printer→inventory sync.

---

## 2. Approach

An **HTMX per-row reconciliation table** at `/spool-sync/` (login-required, matching the rest
of the app). Each AMS slot is a row; resolving one fires an HTMX POST that performs the write
(or records an acknowledgment) and swaps just that row back, now in its resolved state.

Three decisions locked during brainstorming:

1. **v1 = the safe subset.** Resolutions that are a single field-write or an acknowledgment
   are handled inline: `MATCH`→learn serial/percent, `COLOR_MISMATCH`→keep-INV or take-MQTT,
   `INVENTORY_ONLY`→acknowledge. `MISSING_ITEM` and `SLOT_OVERFILLED` render as read-only rows
   that link to the existing add-item / bulk-move flows (their fixes need whole sub-flows).
2. **Per-value acknowledgments.** When the user decides INV is authoritative (a no-write
   resolution), it is remembered **against the specific MQTT value dismissed**, so the row
   drops off "needs attention" but **re-surfaces if the printer later reports a different
   value** (a genuine spool swap).
3. **Cached bridge + manual refresh.** AMS hardware serials are static, so the `get_version`
   bridge is cached in the DB. The page loads instantly from cache; a "Refresh from printers"
   button runs the live MQTT probe on demand (HTMX, ~10 s). The telemetry consumer is **not**
   modified in v1.

### Module layout

- **`inventory/spool_sync.py`** (extend) — add `build_slot_views(bridge, resolutions)`, the
  per-slot view builder, and refactor so categorization lives in **one** place (see §4). Pure
  read.
- **`inventory/spool_sync_actions.py`** (new) — the write/acknowledge service: `learn`,
  `take_mqtt_color`, `keep_inv`, `acknowledge_inventory_only`, `refresh_bridge`. Each is
  guarded and minimal; the only code in the feature that writes.
- **`inventory/models.py`** (extend) — two additive models (§3).
- **`inventory/views.py`** (extend) — `SpoolSyncView` (GET), `SpoolSyncActionView` (POST,
  HTMX), `RefreshBridgeView` (POST, HTMX).
- **Templates** — `spool_sync.html` + `_spool_sync_row.html`; nav link in `navigation.html`.

---

## 3. Data model (one additive migration)

### `AMSBridgeEntry` — cached get_version bridge
```
device      FK PrinterDevice (CASCADE)
ams_index   PositiveSmallIntegerField
ams_serial  CharField(max_length=100)
updated_at  DateTimeField(auto_now=True)
Meta.unique_together = ("device", "ams_index")
```
- Populated only by `refresh_bridge()` (the refresh button), via `update_or_create` per
  `(device, ams_index)`.
- `bridge_map()` helper returns `{(device_id, ams_index): ams_serial}` — the exact shape
  `build_report` / `build_slot_views` already consume, so the page feeds the cached bridge in
  the same way the command feeds the live one.
- A printer unreachable during refresh leaves its existing entries **stale, not deleted**
  (better than dropping a known-good serial); the refresh summary reports which printers
  answered.

### `SpoolSyncResolution` — per-value acknowledgment (the "keep INV" memory)
```
item        FK InventoryItem (CASCADE)
device      FK PrinterDevice (CASCADE)
ams_index   PositiveSmallIntegerField
tray_index  PositiveSmallIntegerField
category    CharField(choices=COLOR_MISMATCH|INVENTORY_ONLY)
acked_value CharField(max_length=32)   # normalized MQTT value dismissed
created_by  FK User (SET_NULL, null=True)
created_at  DateTimeField(auto_now_add=True)
Meta.unique_together = ("item", "category", "acked_value")
```
- `acked_value` is the value that was dismissed: for `COLOR_MISMATCH`, `normalize_hex(color_hex)`
  (e.g. `"057748"`); for `INVENTORY_ONLY`, the sentinel `"EMPTY"`.
- **Suppression rule (in `build_slot_views`):** a row is marked `resolved` iff a
  `SpoolSyncResolution` exists with matching `(item_id, category, acked_value == current MQTT
  value)`. Because the match is against the **current** value, a changed MQTT reading produces
  no match and the row re-surfaces. The acknowledgment travels with the item (keyed on
  `item_id`, not slot), which is the intended semantics ("this spool's INV color is fine").
- `unique_together` makes the acknowledge action idempotent (`get_or_create`).

No changes to existing models; both tables are additive. Migration is additive only.

---

## 4. Matcher refactor — one categorization, two consumers

Today `build_report` walks each `AMSChannelState` row and appends to `proposals`/`flags`. To
avoid a second copy of the branch ladder (the page needs the same categories), extract the
per-slot walk into a generator:

- **`_iter_slots(bridge)`** yields one `SlotView` per `AMSChannelState` row (ordered device
  name → ams_index → tray_index), carrying: `device_name`, `ams_serial` (or `None` if
  unmapped), `ams_index`, `tray_index`, `slot_index` (= `tray_index + 1`), `category`,
  `inv` (list of `{item_id, label, material, hex}` — multiple for overfilled), `mqtt`
  (`{type, hex, remain, uuid, kind}` or `None`), and the proposed write for a `MATCH`
  (`serial`, `percent_from`, `percent_to`). Reuses `classify_tray` / `resolve_ams_item` /
  `slot_for` / `spools_in_slot` / `filament_of` / `normalize_hex` — unchanged.
- **`build_report(bridge)`** is refactored to consume `_iter_slots` and derive
  `counts`/`proposals`/`flags` from it. Its public output (the `SyncReport` shape, the 10
  count keys, the no-write invariant) is **unchanged** — the existing 12 tests must still
  pass.
- **`build_slot_views(bridge, resolutions)`** consumes `_iter_slots`, attaches the `resolved`
  flag (per §3 suppression) and the available actions per category, and returns the ordered
  rows the page renders.

This keeps the dry-run command and the page on a single categorization implementation — the
drift risk flagged in the dry-run review is eliminated.

---

## 5. Action service (`spool_sync_actions.py`)

Every function is called only from a login-required POST view, re-checks current state inside
`transaction.atomic()`, and returns enough for the view to re-render the row. **No blanket
apply.**

| Action | Category | Effect | Guards |
|---|---|---|---|
| `learn(item, ch)` | MATCH | Set `serial_number = ch.tray_uuid` **if blank**; set `percent_remaining = ch.remain_pct` if `remain_pct ≥ 0` and differs; `item.save()` | Never overwrites a non-blank serial that differs (returns a conflict result instead of writing); writing serial/percent doesn't touch location, so the `save()` sticky-status guard is unaffected |
| `take_mqtt_color(item, mqtt_hex)` | COLOR_MISMATCH | `fil = filament_of(item)`; `fil.hex_code = "#" + mqtt_hex`; `fil.full_clean()`; `fil.save()` | `full_clean()` runs `Filament.clean()` → `normalize_hex_code()`, so an invalid hex raises `ValidationError` surfaced as a row error (won't happen with real MQTT hex, but guarded) |
| `keep_inv(item, ch, user)` | COLOR_MISMATCH | `get_or_create` `SpoolSyncResolution(item, COLOR_MISMATCH, acked_value=normalize_hex(ch.color_hex))` | No inventory write |
| `acknowledge_inventory_only(item, ch, user)` | INVENTORY_ONLY | `get_or_create` `SpoolSyncResolution(item, INVENTORY_ONLY, acked_value="EMPTY")` | No inventory write |
| `refresh_bridge()` | — | `fetch_ams_serials_all(enabled devices)` → `update_or_create` `AMSBridgeEntry` per `(device, ams_index)` | One unreachable printer (probe returns `{}`) never aborts the batch; returns `(updated_count, answered_printers, total_printers)` for the toast |

If a row's precondition no longer holds when the action arrives (the item moved, the MQTT
value changed, another tab already resolved it), the action makes **no write** and the view
returns the freshly recomputed row showing the new state — stale clicks are safe.

---

## 6. Views, URLs, templates

All views are `LoginRequiredMixin` (the app's convention; there is no separate staff role).

- **`SpoolSyncView`** GET → `/spool-sync/` (`name="spool_sync"`). Loads the cached bridge
  (`bridge_map()`), the open `SpoolSyncResolution`s, and calls `build_slot_views`. Renders
  `spool_sync.html`: rows grouped by printer → AMS (with serial), split into **Needs
  attention** (actionable: pending `MATCH` writes, un-acked `COLOR_MISMATCH`, `MISSING_ITEM`,
  `SLOT_OVERFILLED`, un-acked `INVENTORY_ONLY`) and a collapsible **OK** section (already-synced
  matches, acknowledged rows, `NON_BAMBU_OK`, empty slots). If the bridge cache is empty, a
  banner prompts "Refresh from printers".
- **`RefreshBridgeView`** POST → `/spool-sync/refresh/` (HTMX). Calls `refresh_bridge()`,
  re-renders the table body, shows a toast (`Refreshed N serials from M/4 printers`). A spinner
  covers the ~10 s probe.
- **`SpoolSyncActionView`** POST → `/spool-sync/action/` (HTMX). Body carries `action`
  (`learn`|`take_color`|`keep_inv`|`ack`) + the row key (`device_id`, `ams_index`,
  `tray_index`, `item_id`). Dispatches to the matching service function, then returns the
  single re-rendered `_spool_sync_row.html` fragment (the row swaps in place via
  `hx-swap="outerHTML"`).

Templates: `spool_sync.html` (extends `base.html`, includes `navigation.html`) and
`_spool_sync_row.html` (the `<tr>` fragment, reused by GET and every POST). Swatch + category
badge styling is lifted from the report renderer already built. A nav link "Spool Sync" is
added to `navigation.html`.

### Full category coverage & the attention/OK split

`build_slot_views` assigns every row a `needs_attention` boolean so the template's split is
unambiguous. **Each of the matcher's 10 categories** maps to exactly one treatment:

| Category | v1 action | Section |
|---|---|---|
| `match` (pending write) | **Learn** button | Needs attention |
| `match` (nothing to write / already synced) | none | OK |
| `color_mismatch` (not acked) | **Keep INV** / **Take MQTT** | Needs attention |
| `color_mismatch` (acked, value unchanged) | none (resolved) | OK |
| `inventory_only` (not acked) | **Acknowledge** | Needs attention |
| `inventory_only` (acked, still empty) | none (resolved) | OK |
| `missing_item` | read-only + link to add-item | Needs attention |
| `slot_overfilled` | read-only + link to bulk-move | Needs attention |
| `serial_conflict` | **read-only, no v1 write** (never auto-overwrite a differing serial; human investigates) | Needs attention |
| `unmapped_ams` | read-only + "Refresh from printers" hint (the bridge is missing/stale) | Needs attention |
| `missing_slot` | read-only (AMS unit has no slot `Location` — a config fix in the Location admin) | Needs attention |
| `non_bambu_ok` | none (printer color matches, no RFID to learn) | OK |
| `empty_skipped` | none | OK |

Rule: `needs_attention = (row has a pending action OR is an unresolved discrepancy) AND not
resolved`. The "OK" section is collapsed by default with a count.

---

## 7. Error handling & safety

- **Trust gate:** every write is per-item and human-clicked; there is no "apply all". Serial
  is never overwritten on conflict; hex is validated via the model's own `clean()`. The nightly
  DB backup (Phase 11.1) is the net.
- **Stale actions:** re-checked inside the action; a no-longer-valid click writes nothing and
  returns the current row.
- **Refresh failure:** unreachable printer → stale-but-present cache + an honest toast; never a
  500.
- **Polymorphism:** `filament_of` / `resolve_ams_item` use `get_real_instance()` — never
  `select_related("product")` (the documented gotcha).
- **Idempotency:** acknowledgments via `get_or_create`; learn/take-color converge to a clean
  match so re-clicking is a no-op.

---

## 8. Testing (TDD)

- **`build_slot_views`** — categories correct per slot; `resolved` suppression hides an acked
  `COLOR_MISMATCH`/`INVENTORY_ONLY`; a **changed** MQTT value re-surfaces it; overfilled slot
  lists all items.
- **`_iter_slots` / `build_report` parity** — the existing 12 dry-run tests still pass after
  the refactor (no behavior change to `SyncReport`).
- **Actions** — `learn` writes serial (only when blank) + percent (only when ≥0 & differs) and
  refuses a conflicting serial; `take_mqtt_color` writes a validated hex and rejects an invalid
  one; `keep_inv` / `acknowledge` create exactly one resolution (idempotent); `refresh_bridge`
  upserts entries from a **mocked** `fetch_ams_serials_all` and reports the printer count.
- **Views** — GET renders and splits attention/OK; each HTMX POST returns the swapped row in
  the expected post-state; login is required (anonymous → redirect); a stale action writes
  nothing.

Networking (`fetch_ams_serials_all`) is mocked in tests, as in the dry-run suite.

---

## 9. Out of scope (v1)

- `MISSING_ITEM` create-spool sub-flow and `SLOT_OVERFILLED` redistribution UI (read-only rows
  with links to existing flows this round).
- Auto-`PrintJob` creation, HMS→`MaintenanceEvent`.
- The blanket `--apply` command path (the page is the write surface; `sync_spools` stays
  dry-run).
- Promoting `get_version` capture into the telemetry consumer + a durable `AMSUnitState.serial`
  (spec §7 of the dry-run design) — the cached `AMSBridgeEntry` + manual refresh covers v1; the
  consumer-integrated bridge remains the eventual go-live step.

---

## 10. Notable consequences

- This is the first feature that **writes** to inventory from telemetry. The per-item,
  human-in-the-loop design is deliberately the opposite of an unattended sync — the same
  damage class as the Audit-15 mis-scan is gated by a human click per write.
- Once spools carry tray-UUID serials (via `learn`), `audit.resolve_serial` will resolve a
  scanned tray UUID to that spool — harmless, arguably useful (noted in the dry-run spec too).
- `build_report` gains a refactor (extract `_iter_slots`); its public contract is unchanged, so
  the dry-run command and its tests are unaffected.
