# Overnight Build — Agent Kickoff

Execution guide for an autonomous overnight run that turns the Phase 11–18 roadmap
([`../todo.md`](../todo.md)) into **ready-to-review PRs**. Aligns with the standing prefs:
*solo overnight execution of independent items → PRs; **defer anything needing a decision**;
subagent-driven for separable tasks.*

> **How the next session should use this:** point agents here, have each take one **GREEN**
> item below, work it to a PR (TDD where noted), and **skip every RED** item. One PR per item.

---

## Preconditions (do first)
1. **Merge PR #129 (roadmap/docs) and #130 (backup script)** so `master` has the rewritten
   `todo.md`, `ideas.md`, the design docs, and the updated `CLAUDE.md`. Agents read these.
2. Venv: `source ~/.venvs/inventory/bin/activate` (or `~/.venvs/inventory/bin/python`).
3. Per-item loop (from `CLAUDE.md` "Working from todo.md"):
   - Branch (`feat/…`, `refactor/…`); read the item's design doc + the affected files in parallel.
   - `~/.venvs/inventory/bin/python manage.py check`; for model changes
     `makemigrations` (+ `--dry-run --check`); add/extend `tests.py`; `pre-commit run --files …`.
   - Conventional Commit, push, open PR, **mark the `todo.md` item `[x]` in the same PR.**
   - One PR per item. Do **not** merge — James reviews.

---

## GREEN — build solo overnight (independent, design settled, no decisions, no prod infra)

| Item | Branch | Design ref | Notes |
|---|---|---|---|
| **11.3 Foundation** — `inventory/items.py` `move_to()`/`deplete()`/`set_status()` + `Location.capacity` | `feat/move-service` | architecture-review §2.1–2.2; workflow-and-domain §2 | **TDD mandatory** — the audit reconcile suite is the canary; preserve the `_skip_status_from_location`/sticky-status semantics, just relocate them. **Build this first** (12.1 builds on it). |
| **11.2 Search redo** — status (incl. UNKNOWN/SOLD/DEPLETED) + item-type + location-subtree filters; "Lost & Found" preset; kill the dead `status` field | `feat/search-redo` | architecture-review §2.3; todo 11.2; `ideas.md` wireframe A | Independent. Re-add `django-filter` `FilterView` or clean Q-objects; extract the 114 lines of inline JS. |
| **13 Item change history** — `django-simple-history`; location+status timeline on the item page; admin history/revert | `feat/item-history` | `docs/item-change-history.md` (fully decided) | New dep (accepted). Touches `models.py` (registration) — minor overlap risk with 11.3; rebase the later PR. |
| **18.2 Filament hub + JS extraction** — merge the 3 filament pages; move ~435 lines inline JS to `static/inventory/js/` | `refactor/filament-hub-js` | architecture-review §2.4–2.5 | Pure refactor, no behaviour change. Independent. |
| **12.1 Location detail page** — read-only "what's here" + inline edit; AMS/dryer slot map | `feat/location-detail` | todo 12.1; `ideas.md` wireframe C | Uses `Location.descendant_ids()`. Assumes 11.3's `move_to()` for the edit path — note the dep in the PR if 11.3 isn't merged yet. |

**Parallel-safe set with no cross-deps:** 11.2, 13, 18.2 (and 11.3 as the foundation). 12.1
prefers 11.3 merged first.

---

## YELLOW — build the code, defer the deploy/data/decision

| Item | Build now | Defer |
|---|---|---|
| **15.1 Maintenance** (`MaintenanceEvent`, `NozzleConfig`, reliability view) | models + admin + view + tests | nothing — fully buildable (workflow-and-domain §4) |
| **15.2 Print-jobs** (`PrintJob`, `PrintJobFilament`, utilization view) | models + admin + manual-entry view + tests | auto-population (that's Phase 16.3). Uses 11.3 `deplete()`. (workflow-and-domain §5) |
| **14 Procurement** | the models + admin + reconcile/spend views (workflow-and-domain §3) | **receipt file upload** until James adds the `media/` volume + `MEDIA_ROOT` (infra) |
| **17.1 Filament schema + loaders** | add `build_plate_compat`/`hot_end_compat` fields + the `pypdf` parsers writing **review CSVs** | **do NOT bulk-load to prod** — the data is review-gated (filament-data-pipeline §4) |

---

## RED — DEFER (needs a James decision, credentials, or blocked infra)
- **11.1 backup deploy** — blocked on the CIFS-on-host mount (James, host-side; `docs/db-backup-status.md`).
- **16 Bambu MQTT (all of it)** — needs printer serials/IPs/access codes + WAL + DB-directory
  bind-mount. Don't start.
- **16.2 Grafana/HA** — depends on 16.1.
- **18.1 admin 2.0 (`django-unfold`)** — sequence **last**, after the new admins exist; adds a dep.
- **Phase 6 prod cleanup** — link AMS/dryer slot `unit` FKs, reconcile the 215 items on 18 legacy
  flat shelves, delete the stray "Dryer XX". Physical/admin work for James (verified incomplete
  2026-06-09).
- Anything needing `.env` / `NET_ADMIN` / Docker-capability / port / `ALLOWED_HOSTS` changes.

---

## Hard rules & gotchas
- **Don't touch prod infra or the live DB.** No `docker-compose`/`.env`/host changes; no
  privileged ops (the app LXC has **no sudo** — `[[no-sudo-on-app-lxc]]`).
- **Don't re-attempt the NFS backup mount** — it's blocked by design; the fix is host-side CIFS.
- New dependency? Only the pre-approved ones (`django-simple-history` for 13, dev-only `pypdf`
  for 17). Anything else → **defer and flag**, per the CLAUDE.md dependency gate.
- Validate import-time errors with `manage.py check` (a missed transitive import = 502 in prod;
  see CLAUDE.md step 7). Wildcard-import replacements: re-import transitive names.
- Keep PRs small and reviewable; explain the *why* in the commit body.
