# Bambu MQTT Integration — Design (2026-06-09)

The "dedicated design session" the backlog asked for. Bambu MQTT flips the app from manual to
**event-driven** and is the largest architectural bet in the roadmap, so it's **phased**:
read-only **telemetry mirror first** (16.1/16.2), trust-gated **auto-sync later** (16.3).
Phasing in [`../todo.md`](../todo.md); domain context in
[`workflow-and-domain-design.md`](workflow-and-domain-design.md).

---

## 1. What Bambu printers expose (local MQTT)
Each printer runs a **local MQTT broker** (same source HA's `bambu_lab` HACS integration uses):
- **Transport:** TLS on **port 8883**, username **`bblp`**, password = the printer's
  **per-device access code** (Settings → network), self-signed cert.
- **Identity:** the device **serial** (Settings → device).
- **Report topic:** `device/{serial}/report` — JSON pushed on change + on request.
- **Request topic:** `device/{serial}/request` — send `pushall` once on connect to get a full
  snapshot, then deltas arrive.

### Fields we care about (from `report.print` and `report.ams`)
| Path | Meaning | Lands in |
|---|---|---|
| `print.gcode_state` | RUNNING / IDLE / PAUSE / FINISH / FAILED | `PrinterState.gcode_state` |
| `print.mc_percent` | progress % | `PrinterState.mc_percent` |
| `print.layer_num` / `total_layer_num` | layer counters | `PrinterState.layer_num/total_layers` |
| `print.nozzle_temper` / `nozzle_target_temper` | hot-end temps | `PrinterState.nozzle_temp/target` |
| `print.bed_temper` / `bed_target_temper` | bed temps | `PrinterState.bed_temp/target` |
| `print.mc_remaining_time` | minutes left | `PrinterState.remaining_min` |
| `print.subtask_name` / `gcode_file` | current file | `PrinterState.subtask_name`, `PrintJob.name` |
| `print.task_id` / `subtask_id` | job identity | `PrintJob.telemetry_task_id` (dedup) |
| `print.hms[]` | active HMS error codes | `PrinterState.hms_codes` → `MaintenanceEvent` |
| `ams.ams[i].tray[j].tray_uuid` | **RFID/tray UUID** | `AMSChannelState.tray_uuid` ← phase-2 join key |
| `ams.ams[i].tray[j].tray_info_idx` | Bambu filament id | `AMSChannelState.tray_info_idx` |
| `ams.ams[i].tray[j].tray_type` / `tray_color` | material / `#RRGGBBAA` | `AMSChannelState.tray_type/color_hex` |
| `ams.ams[i].tray[j].remain` | remaining % (−1 = unknown) | `AMSChannelState.remaining_pct` |

---

## 2. Phase 16.1 — telemetry mirror (read-only)

**Decoupled from `InventoryItem` in this phase** — the consumer writes only its own tables.
No spool sync, no risk to real inventory. Models (full field lists in the domain doc / architect
design):
- `PrinterDevice` — registry/config: `serial (unique)`, `ip_address`, `access_code`,
  `model_name`, **optional** `item FK(InventoryItem, SET_NULL, null)` (curated machine link,
  filled by hand — never guessed), `enabled`, `last_seen_at`.
- `PrinterState` — **latest** snapshot, `OneToOne(PrinterDevice)`, upserted each message.
- `AMSChannelState` — **latest** per `(device, ams_index, tray_index)` (`unique_together`),
  upserted. Carries `tray_uuid` (the phase-2 RFID join key) from day one.
- `TelemetrySample` — **append-only** down-sampled time-series for trends (Grafana).

**Latest vs history split:** `PrinterState`/`AMSChannelState` are cheap single-row reads for the
dashboard; `TelemetrySample` is the trend store. **Down-sample** samples (write on state
transition or every N seconds, not every message) — this is the single most important
write-volume decision for SQLite health.

### Where the consumer lives — process model
The app is **WSGI-only** (`entrypoint.sh`, gunicorn). MQTT needs a **persistent connection**,
incompatible with request/response workers. **Recommendation: a separate container running a
Django management command.**
```
# docker-compose.yml — add a 3rd service
telemetry:
  build: .
  command: ["python", "manage.py", "run_telemetry_consumer"]
  restart: unless-stopped
  volumes:
    - ${HOME}/inventory_db_dir:/app/db      # ⚠ DIRECTORY mount (see §3)
  env_file: [ ${HOME}/.env_inventory ]
```
`run_telemetry_consumer` = a `paho-mqtt` loop: connect per `PrinterDevice` (TLS 8883, `bblp` +
access code), subscribe `device/{serial}/report`, send `pushall`, parse → upsert via the Django
ORM. **Why a management command:** reuses the ORM/models/settings (no second DB layer), deploys
via the existing `docker-compose up -d --build`, and is `restart: unless-stopped` like the
others. (Rejected: supervisor-in-web — couples gunicorn lifecycle; non-Django service —
duplicates the model layer.)

`paho-mqtt` is a new dependency — **flag the dep gate** (pure-Python, small).

---

## 3. SQLite under a sustained writer — the central risk & mitigation

Today: **no WAL** (`settings.py` DATABASES is bare, `journal_mode=delete` default), the DB is a
**single bind-mounted file** (`docker-compose.yml`: `${HOME}/inventory_db.sqlite3:/app/...`),
and the MQTT consumer would be the **first sustained concurrent writer** alongside gunicorn's
workers. Mishandled, this yields intermittent `database is locked` → 500s.

**Mitigations (do all):**
1. **Enable WAL + busy_timeout** via a `connection_created` init (`PRAGMA journal_mode=WAL;
   PRAGMA busy_timeout=5000;`) or `OPTIONS={"timeout":5, "init_command":...}`. WAL lets the
   web app and the read-only HA exporter read concurrently with the writer.
2. **Bind-mount the DB *directory*, not the file.** WAL creates `-wal`/`-shm` siblings that
   **must be shared across containers** — so all services mount `${HOME}/inventory_db_dir/`
   (containing `inventory_db.sqlite3`), not the single file. *This is a compose + deploy change
   to call out explicitly; the backup script (Phase 11.1) and `ha_stats_export.py` paths update
   too.*
3. **Single throttled writer.** The consumer is the only telemetry writer: batch upserts,
   debounce per device, persist `TelemetrySample` only on change/interval, keep transactions
   short.
4. **Fallback (don't pre-build):** if contention appears despite WAL, add an in-process
   `queue.Queue` → single writer thread draining in batches. WAL + single-writer-process +
   down-sampling is very likely sufficient for a handful of home printers. (Postgres stays
   Trashed until contention is *measurable*.)

**Secrets:** per-printer access codes should live in `.env_inventory` keyed by serial (consumer
reads at startup) per the CLAUDE.md `config()` rule, not committed; `PrinterDevice.access_code`
is for dev/non-secret use. **Flag the `.env` touch.**

**Do [DB backup] (Phase 11.1) and the WAL/dir-mount spike BEFORE the first prod deploy of the
consumer.**

---

## 4. Phase 16.2 — Grafana / Home Assistant read path

**Reuse the existing, deployed bridge.** `scripts/ha_stats_export.py` already reads SQLite
**read-only** (no Django) and writes atomic JSON to `~/ha-stats/inventory_stats.json`, served by
nginx at `/ha-stats/` (mounted `:ro` in `docker-compose.yml`), on a 5-minute cron. **Add a
sibling `telemetry.json`** (latest `PrinterState` + `AMSChannelState`) the same way.
- **HA** ingests the JSON trivially (RESTful sensors) → entities for printer state, progress,
  temps, AMS slots.
- **Grafana** panels read from HA (or, for `TelemetrySample` trends, point Grafana's SQLite
  datasource at the WAL DB read-only). Printer hours, utilization, filament burn-down, fault
  counts.
This is the lowest-friction option and reuses a proven pattern; a Prometheus `/metrics`
endpoint is possible but heavier than needed at household scale (defer).

---

## 5. Phase 16.3 — auto-sync (trust-gated)

Only after telemetry is **trusted**. Adds a matcher `telemetry/sync.py` — **no schema change**
(the join keys were captured in 16.1):
- **Spool sync:** match `AMSChannelState.tray_uuid` (RFID) → `InventoryItem.serial_number`
  (`models.py:488`); on match, write `serial_number` (if blank) + `percent_remaining` via
  `items` service. Match the machine via `PrinterDevice.serial` → `Location.unit` →
  the AMS/printer `InventoryItem` (the `audit.resolve_serial` traversal).
- **Auto print-jobs:** on `gcode_state` RUNNING→FINISH with a `task_id`, create/close a
  `PrintJob(source=MQTT, telemetry_task_id=…)` + `PrintJobFilament` from the AMS slots used;
  `complete_job` decrements/depletes.
- **Faults:** a new `print.hms[]` code opens `MaintenanceEvent(kind=FAULT, hms_code=…,
  resolved=False)` on the unit.

**Trust gate (enforce):** a **dry-run matcher** logs *proposed* writes (RFID→item, decrement,
deplete) without applying them, for a manual reconciliation period. Only flip to live writes once
the proposed log is consistently correct. Rationale: auto-writes are the same damage class as the
Audit-No.15 mis-scan (`docs/item-change-history.md`) — but automated and unattended. Gate it
hard.

---

## 6. Open questions for James
- Printer serials + access codes (for `PrinterDevice` seed / `.env`).
- AMS↔machine `Location.unit` links must be populated (the Phase-6 manual setup) before serial
  focus + auto-sync work.
- Confirm the DB-directory bind-mount migration window (brief downtime to move the file + add
  `-wal`/`-shm`).
