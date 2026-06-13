# Phase 16.2 — Telemetry dashboards (HA + Grafana)

Two read-only views of the Bambu printer telemetry. Neither adds writers or new app code;
both consume data the app already produces.

| Surface | Source | Where it lives |
|---------|--------|----------------|
| **Home Assistant** "Printer Fleet" Lovelace dashboard | the **native `bambu_lab` integration** (real-time, MQTT) + `workshop_*` + `inventory_*` sensors | the **`home-assistant-config` repo** (`dashboards/printers.yaml`) — see that repo's PR |
| **Grafana** "Bambu Printer Telemetry" dashboard | the **inventory app's SQLite telemetry tables** (the 16.1 mirror) read directly | `docs/ha/grafana_dashboard.json` (this repo) |

The app's `telemetry.json` export (`scripts/ha_stats_export.py`, served at
`/ha-stats/telemetry.json`, 5-min cron) is **not** consumed by either dashboard: HA already
gets the same data in real time from the native integration, and Grafana reads the DB directly.
`telemetry.json` remains available for any future external consumer; `access_code` is never in it.

---

## Home Assistant dashboard

The dashboard YAML lives in the **`home-assistant-config`** repo, not here (that's how the HA
instance is configured — git → its Actions runner → HA Green). To deploy:

1. Merge the `home-assistant-config` PR (adds `dashboards/printers.yaml` + a
   `lovelace.dashboards:` block in `configuration.yaml`).
2. On the HA host, pull the config (its normal git deploy) and **reload dashboards**
   (Developer Tools → YAML → "Lovelace dashboards", or restart HA).
3. The "Printer Fleet" entry appears in the sidebar.

**Required HACS frontend cards** (already installed in this HA, used by other dashboards):
`mushroom`, `modern-circular-gauge`. (`mini-graph-card`, `flex-table-card`, `auto-entities`,
`button-card` are also present but not required by this dashboard.)

It shows, per printer (H2Dreamy, H2Laser, RuPaul, Scooby Doo): status, progress, remaining time,
nozzle/bed temp, per-AMS humidity, and loaded filament; plus a fleet summary
(printing / AMS-drying / low-stock / in-use / drying / active counts). Every entity reference is
validated against the HA entity registry by the repo's `validate-entities` pre-commit hook.

---

## Grafana dashboard (`grafana_dashboard.json`)

Reads the inventory app's SQLite DB **directly, read-only**, via the SQLite datasource plugin —
giving both the live mirror and `TelemetrySample` history without depending on HA.

### One-time setup
1. **Install the plugin** on the Grafana host:
   `grafana-cli plugins install frser-sqlite-datasource` (then restart Grafana). If Grafana runs
   in Docker, add `GF_INSTALL_PLUGINS=frser-sqlite-datasource` or bake it into the image.
2. **Give Grafana read access to the DB.** The DB is at
   `~/inventory_db_dir/inventory_db.sqlite3` on the app LXC (`10.10.20.17`), in WAL mode. Mount the
   **directory** (so the `-wal`/`-shm` siblings are visible) read-only into wherever Grafana runs —
   e.g. a read-only bind mount, or copy/replicate it. Do **not** mount just the single file.
3. **Add the datasource:** Connections → Data sources → SQLite. Set the path to the mounted
   `inventory_db.sqlite3`. The plugin opens SQLite read-only; WAL reads work fine.
4. **Import the dashboard:** Dashboards → New → Import → upload `grafana_dashboard.json`. When
   prompted, map the `DS_SQLITE` input to the SQLite datasource you just added.

### Panels
- **Printer status (latest)** — table from `inventory_printerstate ⋈ inventory_printerdevice`.
- **AMS humidity (current)** — bar gauge from `inventory_amsunitstate.humidity` per unit.
- **Filament remaining by tray** — bar gauge from `inventory_amschannelstate.remain_pct`
  (`-1`/unknown filtered out).
- **Print progress trend** + **Nozzle/bed temperature trend** — time series from
  `inventory_telemetrysample` (the downsampled history).

### Caveats
- **Humidity has no history.** `TelemetrySample` carries print state only (progress, temps,
  remaining) — not AMS humidity — so humidity is a current-value gauge, not a trend. Adding a
  humidity time-series would require sampling `AMSUnitState` into `TelemetrySample` (future work).
- **Time column.** The trend queries emit `strftime('%s', ts) * 1000 AS time` (epoch ms) and mark
  `timeColumns: ["time"]`. If the plugin version expects seconds, drop the `* 1000`.
- **Units.** AMS `humidity` is shown 0–100; for regular AMS this may be a 1–5 level rather than a
  percent (it's a real % on the AMS-HT dryer). Adjust the panel min/max if your values are 1–5.
- **Freshness.** This is the app's mirror (updated as MQTT messages arrive via the telemetry
  consumer). HA's native entities are the real-time path; this view is the canonical app-side store
  plus history.
