# Ideas & Wireframes — Inventory Manager

A brainstorm companion to [`todo.md`](todo.md). Where `todo.md` is the committed roadmap,
this file is the **idea bank**: features worth doing, UX/visual directions, and ASCII
wireframes/sketches. Items that graduate get a phase in `todo.md`; the rest stay here as
fuel. Grouped: **Quick Wins · UX & Workflow · Visual & Beauty · Data & Features ·
Integrations**. Each idea is tagged `[scheduled: Phase N]`, `[candidate]`, or `[stretch]`.

---

## 0. Quick Wins (high value / low effort)

| Idea | Why | Tag |
|---|---|---|
| Fix the dead search `status` filter | One-line cause; unblocks finding UNKNOWN/lost items | `[scheduled: 11.2]` |
| "Lost & Found" saved search | Recovers the exact audit-recovery use case | `[scheduled: 11.2]` |
| QR labels (alongside Code128) | Phone cameras decode QR ~instantly; Code128 needs a wedge | `[scheduled: 12.3]` |
| PWA "Add to Home Screen" | Manifest+icons already exist; one tap to the scan flow | `[scheduled: 12.3]` |
| Bambu Store "View product" link (SKU) | Trivial; useful on filament pages | `[scheduled: 17.4]` |
| Global mode-aware scan box in navbar | Scan anywhere → item opens / location focuses | `[candidate]` |
| `django-debug-toolbar` already dev-gated; add `nplusone` in dev | Catches the N+1s the audit flagged | `[stretch]` |
| Dark mode toggle (Bootstrap 5.3 `data-bs-theme`) | Cheap; nice for a garage/phone at night | `[candidate]` |

---

## 1. UX & Workflow

### 1.1 Mode-aware global scan box `[candidate]`
One persistent scan input in the navbar. The decoded prefix routes it — no "what mode am I
in?" thinking:
- `INV-###` / QR → open the item page.
- `LOC-###` / unit serial → open the location detail (or focus audit if a session is live).
- bare UPC → "add to inventory" prompt (or, in a receiving session, receive against the PO).

```
 ┌──────────────────────────────────────────────────────────────────────┐
 │  inventory.home   Dashboard  Search  Filament▾  Audit  Receive   [🔍 scan/search…] │
 └──────────────────────────────────────────────────────────────────────┘
        the same box accepts a typed query OR a scanner/camera decode
```

### 1.2 Quick scan-to-move (the daily driver) `[scheduled: 12.2]`
The whole point is **fast, low-effort, phone-only**. Three taps, no audit session.

```
 [1] SCAN ITEM            [2] ITEM CARD                 [3] SCAN / PICK DESTINATION
 ┌───────────────┐        ┌──────────────────────┐      ┌──────────────────────────┐
 │   ( ◎ camera ) │        │  PETG HF · Red        │      │  → AMS RP-1 · slot 3      │
 │                │        │  INV-563   [IN_USE]   │      │  default status: IN_USE   │
 │  point at the  │ ─────► │  @ Dry Storage 2      │ ───► │                          │
 │  INV / QR tag  │        │                       │      │  ⚠ SLOT FULL             │
 │                │        │  [ Move ]  [ Edit ]   │      │  PLA Black (INV-12) here │
 └───────────────┘        │  [ Deplete ] [ Print ] │      │  ┌────────────────────┐  │
                          └──────────────────────┘      │  │ Evict INV-12 & place │  │
                                                         │  │ Pick another slot    │  │
                                                         │  └────────────────────┘  │
                                                         └──────────────────────────┘
```
Status follows the destination's `default_status` automatically (dry storage → STORED,
printer/AMS → IN_USE, dryer → DRYING). The **slot-full prompt** is the new safety behavior.

### 1.3 Location detail + visual slot maps `[scheduled: 12.1]`
"What's here?" at a glance, with AMS/dryer drawn as real slot grids:

```
 LOCATION ▸ AMS RP-1            (ams · 4 slots · unit INV-393)      [ ✎ edit ] [ + scan in ]
 ┌──────────┬──────────┬──────────┬──────────┐
 │  Slot 1  │  Slot 2  │  Slot 3  │  Slot 4  │
 │ PLA Bk   │ PETG Rd  │  —empty— │ ABS Wh   │
 │ INV-12   │ INV-563  │          │ INV-88   │
 │ ████ 72% │ ██   40% │          │ █████ 88%│
 └──────────┴──────────┴──────────┴──────────┘
   3 of 4 slots filled · drying: no

 DRYER ▸ Sunlu S2            (dryer · 4 slots · 55 °C · 2h left)     [ ✎ edit ]
 ┌──────────┬──────────┬──────────┬──────────┐
 │ PLA Mt   │ PETG     │  —empty— │  —empty— │      [▮▮▮▮▮▮░░] 55 °C  ⏱ 2h
 │ 72% DRY  │ 40% DRY  │          │          │
 └──────────┴──────────┴──────────┴──────────┘
```

### 1.4 Unified item timeline `[candidate]`
Today an item's story is scattered: `AuditEvent` (audit-time only), the coming
simple-history (location+status), print jobs, maintenance. Merge into one chronological
"life of this item" panel on the item page:

```
 INV-563 · PETG HF Red                         on hand · 40 %
 ─────────────────────────────────────────────────────────────
  2026-06-09  moved  Dry Storage 2 → AMS RP-1/3   (status → IN_USE)   ⟲ undo
  2026-06-08  print  "bracket_v3.3mf"  -18 g  (X1C #2, 1h12m, ✓)
  2026-06-02  dried  Sunlu S2  (8h @ 55 °C)
  2026-05-30  received  PO-2241 (Bambu)  $20.99   ▸ receipt.pdf
 ─────────────────────────────────────────────────────────────
```
Sources: simple-history (move), PrintJobFilament (print), audit/maintenance, procurement.

### 1.5 Receiving console `[scheduled: 14]`
Mirror the audit console but bound to a PO; the gesture is identical (scan → place →
reconcile), which keeps the muscle memory:

```
 RECEIVING ▸ PO-2241 · Bambu Lab            ordered 2026-05-28 · expected 2026-06-02
 ┌─ scan items as they come out of the box ───────────────────────────────┐
 │  ( ◎ / wedge )  __________________________                              │
 └────────────────────────────────────────────────────────────────────────┘
   Line                         ordered  received  unit$    landing
   PLA Basic Black (1kg)           4        ███ 3   $17.99   Rack A / Shelf 1
   PETG HF Red (1kg)               2        ██  2   $20.99   Rack A / Shelf 1   ✓ done
   M3×8 screws (cost-only)        100       100     $0.04    — (not tracked)    ✓ done
 ─────────────────────────────────────────────────────────────────────────────
   3 of 6 line-units outstanding   [ upload receipt 📎 ]   [ finish & reconcile ]
```

### 1.6 "What can I print right now?" `[stretch]`
Given a target material (e.g. "I need PETG, black, dried"), show in-stock spools that match
and are already DRY/ready, plus where they are. Closes the loop between the filament guide
(what *should* I use) and inventory (what do I *have*, ready to go).

### 1.7 Notifications / alerts `[candidate]`
Low-stock already exists. Add event-driven nudges (HA push via the existing JSON bridge, or
in-app banners): *dryer cycle finished*, *filament left in a printer > N days*, *maintenance
due*, *PO overdue / partially received*. Most become trivial once Phase 16 telemetry lands.

---

## 2. Visual & Beauty

### 2.1 Home / dashboard redesign `[scheduled: 18.3]`
The index page is a button grid; the dashboard is charts + a table. Merge into one
**operations home** with a mobile quick-actions row up top:

```
 ┌─────────────────────────────────────────────────────────────────────┐
 │  [ Scan ]  [ + Receive ]  [ Move ]  [ Audit ]  [ Find ]              │  ← thumb row (mobile)
 ├───────────────┬───────────────┬───────────────┬──────────────────────┤
 │  478 spools   │  $3,140 value │  2 printers   │  ⚠ 3 low · 1 fault    │
 │  on hand      │  at cost      │  printing now │  open items           │
 ├───────────────┴───────────────┴───────────────┴──────────────────────┤
 │  [ filament by material donut ]   [ spend over time ]   [ live printers ] │
 │  Low stock ▸ PLA Basic Black (1 left) · ASA Gray (0) …                 │
 └─────────────────────────────────────────────────────────────────────┘
```

### 2.2 Design tokens + component pass `[scheduled: 18.3]`
- Replace hardcoded chart palettes (`dashboard.html`) and `admin-badges.css` magic colors
  with CSS custom properties (`--status-in-use`, `--family-red`, …). One source of truth;
  enables dark mode for free.
- Standardize the card/table/badge components (currently inline-styled per page).
- Extract the ~435 lines of inline JS to `static/inventory/js/` (search, summary, dashboard)
  — maintainability *and* lets the templates breathe.

### 2.3 Status as a consistent visual language `[candidate]`
Status badges exist in admin; carry the same chip everywhere (search, item page, location
map): NEW (blue) · IN_USE (green) · DRYING (amber) · STORED (slate) · DEPLETED (gray) ·
SOLD (gray) · **UNKNOWN (red, pulsing)** so lost items are visually loud.

### 2.4 Mobile-first polish `[scheduled: 18.3]`
Viewport + Bootstrap grid are already there. Targeted fixes: bulk-action bar wraps instead
of horizontal-scrolling; print-button groups stack; charts get `maintainAspectRatio:false`;
bigger tap targets on the scan flows. The phone is the primary field device — treat it so.

---

## 3. Data & Features

### 3.1 Reliability / rebuy-refund scorecard `[scheduled: 15.1]`
The brief's headline maintenance ask, as a dashboard:

```
 MACHINE RELIABILITY                                   window ▸ [ 1 year ▾ ]
 ┌──────────────┬────────┬─────────┬──────────┬────────┬──────┬────────────┐
 │ Unit (age)   │ Faults │ /month  │ Downtime │ Maint$ │ MTBF │ Verdict    │
 ├──────────────┼────────┼─────────┼──────────┼────────┼──────┼────────────┤
 │ X1C #1 (2y)  │   9    │  0.38   │   14 h   │  $120  │ 41 d │ ⚠ watch    │
 │ X1C #2 (8mo) │   1    │  0.13   │    2 h   │   $18  │  —   │ ✓ keep     │
 │ AMS #3 (1y)  │   5    │  0.42   │    6 h   │   $0   │ 35 d │ ⚠ refund?  │
 │ Sunlu S2(6mo)│   0    │  0.00   │    0 h   │   $0   │  —   │ ✓ keep     │
 └──────────────┴────────┴─────────┴──────────┴────────┴──────┴────────────┘
   Grouped roll-up by model: "X1 Carbon: 0.25 faults/mo across 2 units over 2.7 unit-years"
```

### 3.2 Spend / cost dashboard `[scheduled: 14]`
Once procurement lands: spend over time, by supplier, by material; cost-of-depleted-stock
(what you've burned through); value-on-hand at cost vs catalog. Powered by
`InventoryItem.unit_cost` + cost-only line totals.

### 3.3 Maintenance reminders & service intervals `[candidate]`
Per-model service templates (e.g. "X1C: grease Z-rods every 3 months / 500 h", "wipe AMS
feed gears monthly"). Surfaces "due" items on the home page; checking one logs a
`MaintenanceEvent` automatically.

### 3.4 Hotend / nozzle inventory & history `[scheduled: 15.1]`
Track current nozzle per printer (size/type) + swap history, linked to the `Hardware`
products consumed. Enables "this print needs 0.4 mm but X1C #1 has 0.6 mm mounted" warnings
later, and "how much have I spent on hotends for #1".

### 3.5 Spool-weight & remaining-filament truth `[candidate]`
Spool weight distribution chart (weight × on-hand — data already exists). Longer term, a
"weigh-in" flow (enter measured grams → back-compute `percent_remaining`) for spools the AMS
can't read, complementing MQTT remaining-% for ones it can.

---

## 4. Integrations

### 4.1 Bambu MQTT — the event-driven pivot `[scheduled: 16]`
Full design in [`docs/bambu-mqtt-integration.md`](docs/bambu-mqtt-integration.md). Phased:
read-only telemetry mirror first (live AMS/printer state on dashboards), then trust-gated
auto-sync (RFID → spool serial + remaining %, auto print-jobs, HMS → faults).

```
 LIVE PRINTERS                                                  ⟳ 4s ago
 ┌───────────────── X1C #2 ─────────────────┐  ┌──────── P1S #1 ────────┐
 │  ▶ RUNNING  bracket_v3.3mf      63 %      │  │  ⏸ IDLE                 │
 │  ▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░  layer 142/220     │  │  nozzle 28° bed 24°     │
 │  nozzle 248°  bed 80°   ⏱ 41 min left    │  │  AMS: PLA Wh / PETG Bk  │
 │  AMS RP-1: [PLA Bk][PETG Rd][ — ][ABS Wh]│  │       [ — ][ — ]        │
 │  ⚠ HMS 0300-0100  (none)                 │  │                         │
 └──────────────────────────────────────────┘  └─────────────────────────┘
```

### 4.2 Grafana in Home Assistant `[scheduled: 16.2]`
Reuse the **existing** `scripts/ha_stats_export.py` JSON bridge (read-only SQLite → atomic
JSON → nginx `/ha-stats/` → HA, already on cron). Add a `telemetry.json`; build HA/Grafana
panels for printer hours, utilization, filament burn-down, fault counts. Almost pure config.

### 4.3 Stretch integrations `[stretch]`
- **Bambu Handy parity** lite — the live-printer view above is most of it.
- **HA two-way** — an HA button that triggers "start audit" or surfaces "filament low" as a
  notification (already feasible via the JSON + a webhook).
- **Slicer hand-off** — deep link "open this spool's profile" / annotate a print-job with the
  3MF; only if a real workflow emerges (3MF viewing is backlogged, `#65`).

---

## Appendix — idea → phase ledger
- Scheduled now: 1.2→12.2, 1.3→12.1, 1.5→14, 2.1/2.2/2.4→18, 3.1/3.4→15.1, 3.2→14,
  4.1→16, 4.2→16.2, QR/PWA→12.3, Bambu link→17.4, search fixes→11.2.
- Candidates (next planning): mode-aware scan box, unified item timeline, notifications,
  status visual language, maintenance reminders, weigh-in flow, dark mode.
- Stretch: "what can I print now", Bambu Handy parity, HA two-way, slicer hand-off.
