# Phase 16.3 — Spool-sync dry-run matcher (design)

**Date:** 2026-06-21
**Status:** design, pending review
**Scope:** the read-only "trust gate" first slice of Phase 16.3 (Bambu MQTT auto-sync).
Produces *proposed* writes only — **zero inventory writes**. The live write-back
(`--apply`), auto-`PrintJob` creation, and HMS→`MaintenanceEvent` are explicitly out of
scope and land in a later session once this report is consistently correct.

Supersedes the one-line sketch in `docs/bambu-mqtt-integration.md` §5, which assumed
`serial_number` already held RFID tags. Live data (below) showed it doesn't yet — this
feature is what populates them.

---

## 1. Problem & evidence

The goal of 16.3 is to let the AMS's own readings update inventory: which spool is in
which slot, and how much is left. Before designing, the live stack was probed read-only
(2026-06-21). Findings that shaped the design:

- **`serial_number` is blank on all 488 filament `InventoryItem`s.** RFID→serial matching
  has 0 coverage *today*; the first sync must *learn* the tags. (`serial_number = RFID
  tray UUID` is the intended convention — the field was seeded for exactly this.)
- **The AMS↔unit bridge is deterministic via hardware serial.** Bambu's `get_version`
  command returns a `module[]` list where each AMS module's `sn` matches an existing
  `AMS InventoryItem.serial_number` exactly. Verified on all 4 printers:
  - AMS-Lite (Scooby Doo, RuPaul): modules named `ams/{index}`.
  - H2D (H2Dreamy, H2Laser): modules named `n3f/{index}` (AMS 2 Pro) and `n3s/128`
    (AMS-HT). The `{index}` is the telemetry `ams_index`.
  - A module is an AMS iff its name matches `^(ams|n3f|n3s)/(\d+)$`. Serials are **static**
    (change only on a physical AMS swap), so a single `get_version` per run suffices.
- **`tray_index` (0-based) → `Location.slot_index` (1-based):** `slot_index = tray_index + 1`.
  Confirmed against seeded slot data.
- **Not all rolls are Bambu.** Non-Bambu rolls (Polymaker ASA, currently loaded in
  H2Laser `ams2`) report **no RFID**: `tray_uuid` all-zeros, `remain = -1`, but
  `tray_type`/`tray_color` are set (manually in the AMS). Empty slots report all fields
  null/blank. So an all-zeros UUID is **ambiguous** between "empty" and "non-Bambu roll"
  and must be disambiguated by whether `tray_type`/`tray_color` are present.

`AMSChannelState` (the telemetry mirror) already captures `tray_uuid`, `tray_type`,
`color_hex`, `remain_pct` — enough to classify every tray. The only datum it does *not*
hold is the AMS hardware serial (it lives in `get_version`, not the `print` stream).

---

## 2. Approach

A management command, `sync_spools`, that:

1. Pulls the AMS hardware serials live via a one-shot `get_version` per enabled
   `PrinterDevice` (the deterministic bridge). The telemetry **consumer is left
   untouched this session**; promoting `get_version` capture into the consumer is the
   go-live step.
2. Reads tray state from the existing `AMSChannelState` mirror.
3. Resolves each occupied tray to the inventory spool in the corresponding slot,
   cross-checks color, and emits **proposed** writes + flags.
4. Writes a timestamped JSON artifact to a gitignored `telemetry_review/` dir (mirrors
   the 17.x review-CSV precedent) plus a human-readable stdout summary.

Matching is **deterministic** (serial bridge + physical slot). Color/type are a
confidence signal — they confirm or flag a match, they never *make* one. The design
flags rather than guesses on any ambiguity (the same damage class as the Audit-15
mis-scan, but unattended — gate it hard).

### Module layout

- **`inventory/spool_sync.py`** — pure-ish matcher logic. Public entry:
  `build_report(ams_serial_map) -> SyncReport`. Reads `AMSChannelState` + inventory from
  the ORM; takes the `{(device_id, ams_index): ams_serial}` bridge as its one external
  input (so tests inject it without MQTT). No network, no writes. This is the unit-tested
  surface.
- **`inventory/management/commands/sync_spools.py`** — thin I/O wrapper: fetch the bridge
  via `get_version`, call `build_report`, write the artifact, print the summary. Defaults
  to dry-run. `--apply` exists but raises `CommandError("live writes not enabled (16.3
  go-live)")` — forward-compatible interface, no enabled risk.
- **`inventory/bambu_mqtt.py`** (small helper) — `fetch_ams_serials(device) -> dict` and
  `fetch_ams_serials_all(devices)`: connect (paho, TLS 8883, `bblp` + `access_code`),
  send `get_version`, parse `info.module` for `^(ams|n3f|n3s)/(\d+)$`, return
  `{ams_index: sn}`. Reuses the exact connection params the consumer uses. Read-only
  (subscribe + a benign `get_version` request).
- **`telemetry_review/`** — gitignored output dir.

---

## 3. Matching algorithm (`build_report`)

For each enabled `PrinterDevice`, for each of its `AMSChannelState` rows:

### 3.1 Classify the tray
- **EMPTY** — `tray_type` blank **and** `color_hex` blank → skip (no spool).
- **BAMBU** — `tray_uuid` present and not the all-zeros placeholder (the 32-char
  `00000000000000000000000000000000`).
- **NON_BAMBU** — `tray_uuid` blank/all-zeros **but** `tray_type` or `color_hex` set.

### 3.2 Bridge → slot → spool
- AMS unit = `InventoryItem` whose `serial_number == ams_serial_map[(device_id,
  ams_index)]`. If the `ams_index` isn't in the map (no `get_version` module / probe
  failed) → category `UNMAPPED_AMS`, flag.
- slot `Location` = `kind=ams_slot`, `unit=<ams item>`, `slot_index = tray_index + 1`.
  Missing slot → `NO_SLOT`, flag.
- spool = in-stock `InventoryItem` in that slot (exclude `STICKY_STATUSES`:
  DEPLETED/SOLD/UNKNOWN). Exactly one expected (1:1). **>1 in-stock item in a slot** →
  category `SLOT_OVERFILLED`, flag, propose nothing (the 1:1 assumption is violated and
  must be reconciled by hand first).

### 3.3 Categorize & propose
Color compare: normalize both (strip `#`, lowercase, telemetry `RRGGBBAA` → first 6) vs
the spool product's `hex_code`. Material compare: telemetry `tray_type` token vs the
spool's material name/type (lenient contains, advisory only).

| Tray | Spool in slot | Color | Category | Proposed write |
|---|---|---|---|---|
| BAMBU | yes | ✓ | `MATCH` | `serial_number = tray_uuid` (if blank) + `percent_remaining = remain` (if `remain ≥ 0` & differs) |
| BAMBU | yes | ✗ | `COLOR_MISMATCH` (flag) | none — verify the inv-item |
| BAMBU | no | — | `MISSING_ITEM` (flag) | none |
| NON_BAMBU | yes | ✓ | `NON_BAMBU_OK` | none (no RFID to learn; `remain = -1` → no percent) |
| NON_BAMBU | yes | ✗ | `COLOR_MISMATCH` (flag) | none |
| NON_BAMBU | no | — | `MISSING_ITEM` (flag) | none |
| any | yes, but `serial_number` already set to a *different* value | — | `SERIAL_CONFLICT` (flag) | none — never overwrite |
| EMPTY | yes (item sits in slot) | — | `INVENTORY_ONLY` (flag) | none — inventory says occupied, AMS says empty |
| any (`ams_index` unmapped) | — | — | `UNMAPPED_AMS` (flag) | none |

`remain = -1` always withholds the percent proposal regardless of category.

### 3.4 SyncReport shape
```
SyncReport(
  generated_at, devices=[...], ams_bridge={device: {ams_index: {serial, item_id, matched}}},
  proposals=[ {device, ams_index, tray_index, tray_uuid, item_id, item_label,
               write_serial, write_percent_from, write_percent_to,
               material_match, color_telemetry, color_inventory, color_match} ],
  flags=[ {category, device, ams_index, tray_index, detail, item_id?} ],
  counts={match, non_bambu_ok, color_mismatch, missing_item, inventory_only,
          serial_conflict, unmapped_ams, slot_overfilled, empty_skipped},
)
```

---

## 4. Output

- **Artifact:** `telemetry_review/spool-sync-<ISO8601>.json` — the full `SyncReport`
  serialized. Reviewable per-run, diffable across runs. (`datetime.now()` is fine — real
  command runtime.)
- **Stdout:** counts banner, then the proposed-writes table, then the flags grouped by
  category. Exit 0 always (a dry-run "finding" is not a failure).

---

## 5. Error handling

- A printer unreachable / `get_version` times out → its `ams_index`es are absent from the
  map → those trays land in `UNMAPPED_AMS` with a clear note; other printers still
  reported. Never crash on one printer.
- No `AMSChannelState` rows at all (consumer down) → report it with per-device
  `last_seen_at`; exit 0.
- AMS item with no slot Locations → `NO_SLOT` flag.
- One malformed tray row never aborts the run.

---

## 6. Testing

Seeded from the real 2026-06-21 snapshot (sanitized into a fixture under the test dir),
so the suite exercises the genuine topology, plus hand-built synthetic edges:

- **Bambu match** — color agrees → `MATCH` with both proposed writes; `serial_number`
  blank precondition honored.
- **Offset** — `tray_index 0` resolves `slot_index 1`.
- **Non-Bambu present** — all-zeros uuid + `ASA`/color set + `remain -1` → `NON_BAMBU_OK`,
  **no** proposed write (the Polymaker case).
- **Empty vs non-Bambu** — all-blank tray → `empty_skipped`; not mistaken for a roll.
- **Color mismatch** — `COLOR_MISMATCH` flag, no write (the Polymaker-green vs inventory
  case from live data).
- **Missing item** — occupied tray, empty slot → `MISSING_ITEM`.
- **Inventory-only** — spool in slot, tray empty → `INVENTORY_ONLY`.
- **Serial conflict** — spool already has a different serial → `SERIAL_CONFLICT`, no
  overwrite.
- **Unmapped ams_index** — serial map missing an index → `UNMAPPED_AMS`.
- **Color normalization** — `RRGGBBAA` (8) vs `hex_code` (6), with/without `#`.
- **No-writes invariant** — after `build_report`, the DB is byte-for-byte unchanged
  (`serial_number` still blank, `percent_remaining` untouched across all items).

TDD: write each case first, then the matcher.

---

## 7. Out of scope (→ 16.3 go-live, later session)

- Any real write (`--apply` is blocked).
- Promoting `get_version` capture into the telemetry consumer + an `AMSUnitState.serial`
  field (the durable bridge; tonight uses a runtime probe).
- Auto `PrintJob` creation from `gcode_state` transitions; HMS → `MaintenanceEvent`.
- The H2D **external spool** (`ext` module / virtual tray) — not an AMS slot; deferred.
- The flip-to-live trust switch.

---

## 8. Notable consequences

- Once spools carry tray-UUID serials, `audit.resolve_serial` (which matches serials
  across *all* items) will resolve a scanned tray UUID to that spool's slot. Harmless,
  arguably useful, but recorded here.
- Prod risk for this slice is **zero-write by construction**; the DB backup (Phase 11.1,
  verified live 2026-06-21) is the safety net for the eventual `--apply`, not this.
