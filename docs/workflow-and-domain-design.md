# Workflow & Domain Design — 2026-06-09

Maps James's intended end-to-end workflow against the current system, then specifies the new
domain models that close the gaps (procurement, maintenance, print-jobs). Telemetry is in its
own doc ([`bambu-mqtt-integration.md`](bambu-mqtt-integration.md)). Phasing in
[`../todo.md`](../todo.md).

> **Design rule:** every new subsystem copies the audit pattern — a service module
> (`procurement.py`, `maintenance.py`, `printjobs.py`) holding the logic, with thin CBVs that
> call it. State mutations to `InventoryItem` go through the Phase-11.3 `items.move_to()` /
> `items.deplete()` service, never ad-hoc `save()` + flags.

---

## 1. The intended loop vs. today

**order → receive → move/swap → use (print) → deplete → maintain**

| Stage | Today | Gap | Phase |
|---|---|---|---|
| **Order / cost** | Nothing (Order/Shipment deleted). Free-text `shipment` only. | Full procurement: PO, supplier, lines, per-item cost. | 14 |
| **Receive / tag / shelve** | `AddInventoryView` + label, not order-linked. | Receiving console bound to a PO; reconcile qty; cost-only consumables. | 14 |
| **Move / swap (phone)** | Only inside an audit session; the edit page is a slow form. | Quick scan-to-move; status follows location; slot-capacity confirm. | 12 |
| **Slot limits** | None — a 5th roll fits a 4-slot dryer. | `Location.capacity` + evict-to-make-room. | 11.3 / 12.2 |
| **Use (print)** | Untracked. | `PrintJob` + per-spool consumption. | 15.2 (manual) / 16.3 (auto) |
| **Deplete** | Manual `mark_depleted()`. | Auto-decrement `percent_remaining` on job completion. | 15.2 |
| **AMS RFID / remaining %** | Manual. | MQTT auto-sync writes serial + remaining %. | 16.3 |
| **Maintain** | Nothing. | Maintenance log + reliability/rebuy analytics. | 15.1 |
| **Trace / undo a move** | Only `AuditEvent`, audit-time only. | simple-history all-field; location+status timeline. | 13 |

### Not covered by the 11 items (idea candidates, see `ideas.md`)
Notifications (dryer-done, filament-left-in-printer, maintenance-due, PO overdue); a **unified
item timeline** (audit + history + jobs + maintenance in one panel); spool→empty→refill as an
explicit staging state (James tracks the *filament*, not the empty spool — so "depleted" is the
terminal state and the empty spool is intentionally untracked); **"what can I print now"**
(match a material need to in-stock, dried spools).

---

## 2. `InventoryItem` lifecycle (status state machine)

Statuses today: `NEW=1, IN_USE=2, DRYING=3, STORED=4, DEPLETED=5, SOLD=6, UNKNOWN=7`
(`models.py:503`). Most transitions are **driven by location** via `default_status`; sticky
statuses opt out.

```
                 receive
            ─────────────────►  NEW ──move→ (location.default_status)
                                  │            ├─ dryer slot   → DRYING
                                  │            ├─ AMS/printer   → IN_USE
                                  │            └─ shelf/storage → STORED
   (any active)  ──print used up──┴──────────────────────────────► DEPLETED ⟂ (sticky)
   (any active)  ──sold──────────────────────────────────────────► SOLD     ⟂ (sticky)
   (audit: not found at a closed location)  ─────────────────────► UNKNOWN   ⟂ (sticky)
            UNKNOWN ──re-scanned during audit──► (revived to location status)
            UNKNOWN ──finalize (default)───────► DEPLETED
```
`STICKY_STATUSES = (DEPLETED, SOLD, UNKNOWN)` are never overwritten by a location move; this is
the model-level guarantee the Phase-11.3 service must preserve.

---

## 3. Procurement (full) — Phase 14

Service `inventory/procurement.py`. Re-introduces the cost layer deleted in Phase 2, normalized.

### Models (Django field types)
```
Supplier
  name CharField(200, unique) · website URLField(blank) · account_ref CharField(100, blank)
  notes TextField(blank)

PurchaseOrder
  supplier FK(Supplier, PROTECT, related_name="orders")
  order_ref CharField(120, blank)        # store order/confirmation #
  status PositiveSmallInteger(choices: DRAFT/ORDERED/PARTIAL/RECEIVED/CANCELLED, default DRAFT)
  ordered_at DateField(null) · expected_at DateField(null)
  shipping_cost Decimal(8,2, default 0) · tax Decimal(8,2, default 0) · currency CharField(3, "USD")
  notes TextField(blank) · created_at auto_now_add · last_modified auto_now

PurchaseOrderLine
  order FK(PurchaseOrder, CASCADE, related_name="lines")
  product FK(Product, PROTECT, related_name="po_lines")   # polymorphic base
  description CharField(255, blank)        # snapshot for odd/off-catalog items
  qty_ordered PositiveInteger(default 1) · qty_received PositiveInteger(default 0)
  unit_cost Decimal(8,2)                   # per-unit price PAID
  track_individually Boolean(default True) # False = cost-only consumable (screws)
  # property line_total = qty_ordered * unit_cost

PurchaseReceipt                            # a receiving event (supports partials)
  order FK(PurchaseOrder, CASCADE, related_name="receipts")
  received_at DateTime(default now) · received_by FK(User, SET_NULL, null)
  attachment FileField(upload_to="receipts/%Y/%m/", null)   # the confirmation/receipt file
  notes TextField(blank)

PurchaseReceiptLine
  receipt FK(PurchaseReceipt, CASCADE, related_name="lines")
  order_line FK(PurchaseOrderLine, PROTECT, related_name="receipt_lines")
  qty_received PositiveInteger
```

### Per-item cost — where it lives, and why
Add to `InventoryItem`: `unit_cost Decimal(8,2, null)` and
`source_line FK(PurchaseOrderLine, SET_NULL, null)`.
- `Product.price` (`models.py:43`) is the **catalog list price** (what the dashboard sums at
  `views.py:930`) — i.e. replacement value, not what you paid. Spend reporting needs **what you
  paid**, which varies per purchase. So `unit_cost` is **denormalized onto the item** at receive
  time (copied from `source_line.unit_cost`). The FK is kept for drill-back but is `SET_NULL` so
  deleting a PO never erases cost history.
- **Cost-only consumables** (`track_individually=False`) mint **no** `InventoryItem`; their spend
  lives only on the line. Spend reports therefore **union** `Sum(InventoryItem.unit_cost)`
  (tracked goods) + `Sum(line_total)` for cost-only lines.

### Receiving flow (connects to inventory)
`procurement.receive_scan(receipt, upc, location)` — the audit `add_or_queue_upc` gesture, bound
to a PO:
1. Resolve `Product` by UPC (`Product.objects.filter(upc=upc).first()`, polymorphic → real
   instance, same as `views.py:378`).
2. Find the matching open `PurchaseOrderLine` (product match, `qty_received < qty_ordered`);
   ambiguity → `ProcurementError`.
3. If `track_individually`: `items.move_to(new InventoryItem, receiving_rack)` + print `INV-`
   label (`generate_and_print_barcode`) + stamp `unit_cost`/`source_line` + bump both received
   counters.
4. Else (screws): bump `qty_received` only; optionally bump catalog `Hardware.qty`.
5. Recompute PO status (all lines full → RECEIVED, some → PARTIAL).

### Views / admin / infra
- `procurement.py`: `receive_scan`, `open_lines_for`, `reconcile`, `recompute_po_status`.
- CBVs: PO list/detail/create/update, **ReceivingConsole** (+ `ReceivingScan`, mirrors
  `AuditScanView`), receipt upload. Admin: all five models, `PurchaseOrderLine` inline.
- **Infra (flag):** `FileField` needs `MEDIA_ROOT`/`MEDIA_URL` (absent today), an nginx alias,
  and a bind-mounted `media/` volume in `docker-compose.yml` (mirror the `ha-stats` mount).
- Migration: purely additive (5 tables + 2 nullable columns on `InventoryItem`). No data migration.

---

## 4. Maintenance — Phase 15.1

Service `inventory/maintenance.py`. Attaches to **the machine's `InventoryItem`** (the only
stable identity for "this specific physical unit"), resolved from a scanned serial via the same
`Location.unit` traversal `audit.resolve_serial` already uses (`audit.py:102`).

### Models
```
MaintenanceEvent
  unit FK(InventoryItem, CASCADE, related_name="maintenance_events")
  kind PositiveSmallInteger(FAULT/REPAIR/PART_REPLACE/LUBRICATE/CLEAN/CALIBRATE/
                            HOTEND_SWAP/FIRMWARE/INSPECT/OTHER)
  severity PositiveSmallInteger(INFO/MINOR/MAJOR/CRITICAL, default INFO)
  occurred_at DateTime(default now) · title CharField(200) · detail TextField(blank)
  part FK(Product, SET_NULL, null, related_name="maintenance_uses")     # Hardware product used
  part_item FK(InventoryItem, SET_NULL, null, related_name="installed_as") # the tracked part, if any
  cost Decimal(8,2, null) · downtime_hours Decimal(6,2, null)
  hms_code CharField(32, blank)        # Bambu HMS error code — populated by MQTT later
  resolved Boolean(default True)       # False = open fault
  created_at auto_now_add

NozzleConfig                            # current hot-end state per printer (for "nozzle changed")
  printer OneToOne(InventoryItem, CASCADE, related_name="nozzle_config")
  nozzle_diameter_mm Decimal(3,2, null)  # 0.40 / 0.60 …
  nozzle_type CharField(50, blank)       # hardened steel, etc.
  hotend_changed_at DateTime(null)
```
**Hotend swap** writes both: a `MaintenanceEvent(kind=HOTEND_SWAP, part=<hotend Hardware>)`
(the *history*) and a `NozzleConfig` update (the *current state*, needed by print-jobs /
slicer-mismatch checks). Mirrors the audit split of append-only log vs. live state. Consumable
parts FK the polymorphic `Product` → naturally a `Hardware` (`HardwareType.PARTS`); if the part
was itself received, `part_item` links the consumed `InventoryItem` (cost from procurement).

### The "rebuy / refund?" analytics (headline ask)
- Per-unit fault trend: `MaintenanceEvent.filter(unit=X, kind=FAULT, occurred_at__range=…)`
  bucketed by month.
- Cross-model comparison: join `MaintenanceEvent → InventoryItem.product`, filter by
  `polymorphic_ctype` + the subclass `model` (`Printer.model`, `models.py:260`), normalize by
  unit-count and age (`InventoryItem.date_added`). → faults/month, downtime, maint $, MTBF, a
  "rebuy score." Rendered by `MaintenanceSummaryView` (wireframe 3.1 in `ideas.md`).
- HMS link (Phase 16.3): the telemetry consumer opens `MaintenanceEvent(kind=FAULT,
  hms_code=…, resolved=False)` on a new HMS error. `hms_code` exists from day one so no schema
  change when MQTT arrives — only a new writer.

### Service / views
`maintenance.py`: `log_event`, `open_fault`, `resolve_fault`, `swap_hotend(printer, nozzle_mm,
part=…)`, `unit_summary`, `model_reliability`. CBVs: `UnitMaintenanceView` (per-machine timeline
from the item page), `MaintenanceLogCreateView`, `MaintenanceSummaryView`. Admin inline under
`InventoryItemAdmin`. Additive migration; `NozzleConfig` lazily created.

---

## 5. Print-jobs & utilization — Phase 15.2

Service `inventory/printjobs.py`. Manual-entry first; MQTT auto-populates the same tables later
(`source` enum distinguishes them, useful while building trust in the MQTT path).

### Models
```
PrintJob
  printer FK(InventoryItem, PROTECT, related_name="print_jobs")
  name CharField(255, blank)            # gcode/3mf file
  started_at DateTime(null) · ended_at DateTime(null) · duration_s PositiveInteger(null)
  result PositiveSmallInteger(SUCCESS/FAILED/CANCELLED/PARTIAL, default SUCCESS)
  source PositiveSmallInteger(MANUAL/MQTT, default MANUAL)
  telemetry_task_id CharField(64, blank)  # Bambu subtask id — dedup key for auto-ingest
  notes TextField(blank) · created_at auto_now_add

PrintJobFilament                         # 0..N spools per job (multi-color via AMS)
  job FK(PrintJob, CASCADE, related_name="filaments")
  item FK(InventoryItem, PROTECT, related_name="print_uses")   # the spool
  ams_slot FK(Location, SET_NULL, null)   # which slot it drew from (→ unit via Location.unit)
  grams_used Decimal(7,2, null) · percent_used Decimal(5,2, null)
```

### Completion → decrement / deplete
`printjobs.complete_job(job)` — for each `PrintJobFilament`:
1. `delta_pct = grams_used / (Filament.weight*1000) * 100` if grams known, else `percent_used`.
2. `item.percent_remaining = max(0, item.percent_remaining - delta_pct)` (`models.py:498`).
3. If ≤ ~0 → `items.deplete(item, reason="print")` (the Phase-11.3 primitive, which owns the
   sticky-status flag dance — the strongest argument for doing 11.3 first).

This **subsumes the `ConsumptionEvent` backlog**: `PrintJobFilament` *is* the consumption log,
with attribution to a job; depletion timestamps already feed `_build_low_stock_alerts`
(`views.py:621`) and `FilamentSummaryView` (`views.py:748`) for free.

### Utilization
`printjobs.printer_utilization(printer, since)`: hours (`Sum(duration_s)`), job count, success
rate, kg consumed (`Sum(grams_used)` grouped by material/color via existing `Filament`
dimensions). `UtilizationView` → per-printer cards + time series (the backlog "Printer
utilization chart," unblocked). Admin inline `PrintJobFilament` under `PrintJob`.

---

## 6. Cross-cutting notes
- **One depletion/move primitive** (Phase 11.3) serves receiving (3), maintenance part-consume
  (4), and print completion (5) — extract it once.
- **Serial→unit resolution** (`audit.resolve_serial`) is reused by maintenance and telemetry —
  do not duplicate.
- **Migrations** for §3–5 are additive; the only infra touches are procurement's media volume
  and telemetry's WAL/dir-mount (telemetry doc). Both are flagged per the CLAUDE.md gate.
