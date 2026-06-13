# Phase 16.2 — Telemetry Dashboards (HA Lovelace + Grafana)

**Date:** 2026-06-13
**Status:** Design approved (direction); spec for review
**Roadmap:** `todo.md` Phase 16.2 — Grafana / HA dashboard.

## Context / what's already done

- **Repo read-path is complete + live:** `scripts/ha_stats_export.py` already exports
  `telemetry.json` (PR #144), served at `http://10.10.20.17:8080/ha-stats/telemetry.json`,
  refreshed by the 5-minute cron. Verified live (4 printers, AMS humidity/trays, access_code
  excluded).
- **HA already has native real-time Bambu telemetry:** the `bambu_lab` HACS integration exposes
  per-printer entities (`sensor.<prefix>_print_status`, `_remaining_time`, `_nozzle_temperature`,
  `_ams_<n>_humidity`/`_temperature`/`_tray_*`, `binary_sensor.<prefix>_ams_<n>_drying`/`_active`).
  `packages/workshop.yaml` also defines **aggregate** sensors: `sensor.workshop_<printer>_ams_status`
  (tray/temp/humidity/drying attrs), `_print_cost_estimate`, `_cost_today`/`_monthly`, and fleet
  `binary_sensor.workshop_any_printer_printing` / `workshop_any_ams_drying`. `packages/inventory.yaml`
  defines `sensor.inventory_stats` (+ `inventory_low_stock_alerts`, per-printer per-slot stock).

**Therefore:** do **not** add REST sensors off `telemetry.json` — that would duplicate the native,
real-time entities and be staler (5-min cron). 16.2's remaining deliverable is **two dashboards**
on existing data.

## Deliverables (two repos)

### A. Home Assistant — `home-assistant-config` repo (a PR there)
- **`dashboards/printers.yaml`** — a "Printer Fleet" Lovelace dashboard (YAML mode), built ONLY on
  existing entities (native `bambu_lab` + `workshop_*` aggregates + `inventory_*`). No new sensors.
  - **Fleet summary** section: `binary_sensor.workshop_any_printer_printing`,
    `workshop_any_ams_drying`, `sensor.inventory_low_stock_alerts`, `inventory_drying`.
  - **Per-printer** section ×4 (H2Dreamy `h2d_0948ad532400186`, H2Laser `h2d_0948cd531200537`,
    RuPaul `x1c_00m09d461201098`, Scooby Doo `x1c_00m09d460801722` — note Scooby's irregular `_2`
    AMS suffixes, RuPaul's `rupaul_*` aliases): print_status, remaining_time, print-cost estimate;
    AMS humidity via `custom:modern-circular-gauge` per unit; drying badge from the `*_drying`
    binary sensors; trays/filament from `workshop_<printer>_ams_status` attrs (or raw `_ams_<n>_tray_*`);
    inventory stock from the `inventory-<printer>-ams*-s*` sensors.
  - Cards limited to confirmed-installed HACS types: `custom:mushroom-title-card`,
    `mushroom-template-card`, `mushroom-entity-card`, `modern-circular-gauge`, `mini-graph-card`,
    plus core `grid`/`vertical-stack`/`horizontal-stack`/`conditional`.
  - **yamllint-clean:** block style only (no `{k: v}` flow mappings — yamllint forbids non-empty
    flow maps), ≤200-char lines, 2-space indent, comment spacing. Must pass the repo's pre-commit
    (`check-yaml`, `yamllint`, `validate-entities` against real entity_ids) and the CI HA config check.
- **`configuration.yaml`** — register the dashboard under `lovelace.dashboards:` (mirror the existing
  blocks): `dashboard-printers` → `mode: yaml`, `filename: dashboards/printers.yaml`,
  `title: "Printer Fleet"`, `icon: mdi:printer-3d`, `show_in_sidebar: true`, `require_admin: false`.

### B. Grafana — `inventory_management` repo (`docs/ha/`)
- **`docs/ha/grafana_dashboard.json`** — Grafana dashboard, `frser-sqlite-datasource`, templated
  `${DS_SQLITE}` (mapped on import). Panels:
  - **Printer status** (table): `inventory_printerstate` ⋈ `inventory_printerdevice` —
    name, gcode_state, mc_percent, remaining_min, nozzle_temp, bed_temp, subtask_name, updated_at.
  - **AMS humidity** (bar gauge): `inventory_amsunitstate` (device⋈) humidity per unit — current value.
  - **Filament remaining** (bar gauge): `inventory_amschannelstate.remain_pct` per tray, `remain_pct >= 0`,
    labelled `name AMS<idx>/tray<idx> (tray_type)`.
  - **Print trend** (time series): `inventory_telemetrysample` over `ts` — `mc_percent`, `nozzle_temp`,
    `bed_temp` (humidity has no history — `TelemetrySample` doesn't carry it; documented).
  - Time column SQL emits `ts`/`updated_at`; README notes the plugin's time-format setting (ISO vs epoch).
- **`docs/ha/README.md`** — setup:
  - HA: the dashboard lives in the `home-assistant-config` repo (PR); `git pull` on the HA host /
    its Actions runner deploys it; reload dashboards. Lists the required HACS cards.
  - Grafana: install `frser-sqlite-datasource`; add a **read-only** SQLite datasource pointing at the
    WAL DB (`~/inventory_db_dir/inventory_db.sqlite3` — must be readable by Grafana, e.g. a read-only
    bind mount; open `?mode=ro`); import `grafana_dashboard.json`; map `${DS_SQLITE}`.
  - Caveats: humidity is current-value only (no trend); `telemetry.json` is a 5-min cron (HA's native
    entities are the real-time path — this Grafana view is the inventory app's canonical mirror +
    history); `access_code` is never exposed.

## Delivery
Two PRs: one to `home-assistant-config` (dashboard + registration), one to `inventory_management`
(`docs/ha/` + todo/CLAUDE updates). Both `feat/` branches; James reviews/merges each.

## Validation (no automated tests — config artifacts)
- HA YAML: run the HA repo's `pre-commit` (yamllint + check-yaml + validate-entities) on the changed
  files; every entity_id used must be a real one (sourced from `workshop.yaml`/`inventory.yaml`
  ground truth). Do NOT invent entities.
- Grafana JSON: `python -c "json.load(...)"` parse + schema sanity (panels/targets/datasource var).
- An adversarial review pass (entity_ids real, SQL columns match the telemetry models, cards installed,
  yamllint rules honored).
- **Honest limit:** cannot be rendered/imported in your HA or Grafana from here — these are
  lint/parse-validated, ground-truth-wired starting points you import and tweak.

## Non-goals
- No new HA REST sensors (native + workshop aggregates already cover it).
- No changes to `ha_stats_export.py` / the export cron (read-path is done).
- No inventory↔tray RFID join (that's 16.3 auto-sync).
- No humidity history (not in `TelemetrySample`).
