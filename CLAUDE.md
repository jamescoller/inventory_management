# CLAUDE.md

Project context for Claude Code working on this inventory management repository.

## What this repo is

A Django 4.2 web application for tracking 3D printer consumables — filament spools,
hardware, printers, AMS units, and drying equipment. Deployed as a Docker Compose
stack (Gunicorn + Nginx). The app also integrates with a Brother QL-810W label printer
for barcode printing.

GitHub: https://github.com/jamescoller/inventory_management
Default branch: `master`

## Hardware & topology

- **App host:** Proxmox LXC at `10.10.20.17` — Docker Compose stack, GitHub Actions
  self-hosted runner, and SQLite database all live here.
- **App URLs:** `http://inventory.home` (via NGINX + PiHole), `http://10.10.20.17:8080`
- **Database:** SQLite (WAL) at `~/inventory_db_dir/inventory_db.sqlite3` on the app LXC —
  not version-controlled. Nightly backup to the NAS is live (Phase 11.1); see "Database
  location" under Environment notes for the WAL/directory details.
- **Claude Code LXC:** Debian 12 on Proxmox at `10.10.20.16` — this is where Claude
  Code runs and where all code editing happens. This is running on the same physical host as the app.
- **Network:** server VLAN (`10.10.20.x`)
- **Co-located on the same VLAN:**
    - Home Assistant Green (`10.10.20.2`) with its own GitHub Actions runner in a Proxmox LXC (`10.10.20.15`)
  - Proxmox host — Minisforum UM790 Pro, Ryzen 9 7940HS, 32 GB DDR5 (running LXCs)
  - Claude Code LXC (`10.10.20.16`, Debian 12 on Proxmox)
  - App LXC (`10.10.20.17`, Debian 12 on Proxmox)
    - Raspberry Pi 5s
  - Mac Mini M2

## Accessing the live app

**Browser** — `http://inventory.home` or `http://10.10.20.3:8080` are reachable
directly from this LXC.

## CI/CD pipeline

1. Code changes happen in this repo, on the Claude Code LXC (`10.10.20.16`), via Claude Code.
2. Pre-commit hooks run (configured in `.pre-commit-config.yaml`).
3. Push to GitHub. GitHub Actions runs the deploy workflow.
4. The workflow runs on the self-hosted runner on the app LXC (`10.10.20.17`).
5. `scripts/deploy.sh` does a hard reset to `origin/master`, links the env file,
   then runs `docker-compose down && docker-compose up -d --build`.
6. Gunicorn restarts inside the rebuilt container; migrations run at container start
   via `entrypoint.sh`.

**Note:** `master` is the production branch. Pushes to `master` or `release/*` trigger
an automatic deploy to the live NAS instance.

## Environment / secrets

- `.env` file is **not** version-controlled (gitignored).
- Key env vars: `DJANGO_SECRET_KEY`, `DEBUG`, `ENABLE_BARCODE_PRINTING`,
  `PRINTER_IP`.
- Never hardcode secrets. Use `python-decouple`'s `config()` — it reads from `.env`.

## Workflow

1. Create a feature branch: `feat/...`, `fix/...`, `chore/...`, `docs/...`
2. Make changes and validate (see below).
3. Commit with a Conventional Commits message.
4. Push and open a PR against `master`.
5. James reviews and merges. Merge triggers auto-deploy.
6. Squash-merge PRs unless multi-commit history is genuinely useful.

Direct commits to `master` are for trivial changes only (typo fixes, doc tweaks).

## Conventions

- **Django patterns:** Follow standard Django conventions. Use class-based views where
  appropriate; function-based views are fine for simple cases.
- **Models:** Changes require migrations. Always generate migrations with
  `python manage.py makemigrations` and include them in the PR.
- **Templates:** Stored in `inventory/templates/inventory/`. Use `{% extends "inventory/base.html" %}`
  and `{% block %}` tags. HTMX is available for dynamic interactions.
- **Forms:** Use `django-crispy-forms` with the `bootstrap5` pack.
- **Static files:** App-level statics live in `inventory/static/`. Run
  `python manage.py collectstatic` before testing production behavior.
- **Barcode printing:** Controlled by `ENABLE_BARCODE_PRINTING`. The `brother_ql`
  library uses `scapy` for MAC-based printer discovery — this requires `NET_ADMIN`
  and `NET_RAW` capabilities in the Docker container. It is currently implemented with a static IP (`10.10.40.2`).
- **Secrets:** Always use `config("VAR_NAME")` from `python-decouple`, never `os.environ`.

## Branching

- Feature branches: `feat/<short-description>`
- Bug fixes: `fix/<short-description>`
- Chores/deps/CI: `chore/<short-description>`
- Docs: `docs/<short-description>`

Claude Code creates a branch before making changes, commits to it, pushes, and
reports the PR URL. James reviews and merges.

## Commit messages

Follow Conventional Commits. Subject line:
  `<type>: <imperative description>`

Types: `feat`, `fix`, `chore`, `docs`, `refactor`, `perf`, `test`, `ci`

Body (when non-trivial): explain the *why*, not the *what*. The diff shows what;
the message should explain why this change exists.

## Validation before committing

Run from the local venv (`~/.venvs/inventory/bin/python` or after
`source ~/.venvs/inventory/bin/activate`):

1. `python manage.py check` — Django config, model integrity, import-time
   `NameError`s (the kind that previously only surfaced in production).
2. For model changes: `python manage.py makemigrations --dry-run --check` —
   exits non-zero if a migration is missing. Then actually generate it with
   `makemigrations` and include it in the PR.
3. `pre-commit run --files <changed-files>` — runs black, ruff (with `--fix`),
   djlint (templates), shellcheck (shell scripts), trailing-whitespace, and the
   local migrations check. Avoid `--all-files` for normal commits; that's a
   bulk-cleanup activity.
4. For template changes also: visit the live app at `http://inventory.home` or
   `http://10.10.20.17:8080` (reachable from this LXC) to confirm render.
5. For requirements changes: `uv pip install -r requirements.txt -r requirements-dev.txt`
   into `~/.venvs/inventory` to confirm the lock resolves, then verify the Docker
   image will still build (the GitHub Actions runner on the app LXC rebuilds on
   merge to master).
6. For high-confidence verification against the running stack:
   `ssh inventory-manager 'docker exec inventory_management-web-1 python manage.py check'`
   (and `check --deploy` if touching settings/security).
7. Before suggesting a PR, check `readme.md` and `todo.md` — update them if the
   change warrants it.

## Things to ask, not assume

- **Database migrations:** If a migration would alter or drop a column on a
  non-trivial table, flag the data-loss risk before proceeding.
- **`.env` changes:** Any new `config()` call needs a corresponding entry in
  `.env_shared` on the NAS. Flag this explicitly so James can add it.
- **Dependency additions:** New packages mean a longer image build. Confirm before
  adding, especially large packages like `scapy` or `pandas` — those are already
  present but were deliberate additions.
- **`NET_ADMIN` / `NET_RAW` changes:** These Docker capabilities are needed for
  barcode printer discovery. Don't remove them without a replacement strategy.
- **Port / `ALLOWED_HOSTS` changes:** Any new deployment URL needs to be added to
  `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` in `settings.py`.

## Personal context

I'm an engineer; you can be technically dense and skip basic explanations.
Show your reasoning when making a non-obvious tradeoff. When multiple approaches
exist, briefly note the alternatives and why you picked one.

Prefer well-regarded Django patterns over custom workarounds. If the answer is
"use a built-in Django feature," say so.

## Additional requests

Before any PR, review `readme.md` and `todo.md` and determine if either should
also be updated.

At the end of every session, review this CLAUDE.md. If anything learned during
the session would help future sessions — new constraints, corrected assumptions,
better approaches, validated patterns — update it before closing out.

**Always commit and push before ending a session.** No uncommitted or unpushed
work should remain on this LXC. Reason: a SessionStart hook prunes stale local
branches whose upstream is `[gone]` (using `git branch -d`, which refuses
unmerged commits — but only protects against accidents on *that* branch).
Combined with the working tree being on a long-lived feature branch,
uncommitted edits could be lost on a future `git checkout` or branch cleanup.
If a piece of work isn't ready for a PR, at least commit it to its branch and
push (`git push -u origin <branch>`) so the remote has a copy. If there's truly
nothing worth committing, say so explicitly before ending.

**But the hook will NOT clean squash-merged branches.** Because PRs here are
squash-merged by default, the squashed commit has a new SHA and `git branch -d`
sees the original branch as "not fully merged" and refuses it (this is the same
safety that protects unmerged work — the two are inseparable). Net effect:
`[gone]` feature branches pile up locally and the hook never removes them. To
clear them, run the `/clean_gone` skill (force-deletes `[gone]` branches and
their worktrees). Also `git checkout master` after pushing rather than ending a
session parked on the just-merged feature branch — the hook can't delete the
checked-out branch either (and `awk` grabs the `*` marker instead of its name).

## Working from todo.md

`todo.md` is the canonical roadmap. Phases are ordered by priority; within a
phase, bugs come before enhancements. Before starting any phase:

1. Read `todo.md` in full so the complete scope is understood before touching code.
2. Read all affected files in parallel (views, models, forms, admin, settings,
   templates) — map each item to its exact location before writing a single edit.
3. Fix in logical groups that minimise re-reading: model-layer changes first,
   then view-layer, then templates, then config.
4. Validate every modified Python file with `~/.venvs/inventory/bin/python manage.py check`
   (this catches import errors too, not just syntax — see Environment notes).
5. Mark items `[x]` in `todo.md` as they are completed.
6. Open one PR per phase unless a single item is a natural standalone fix.
7. **When replacing wildcard imports (`from .x import *`) with explicit ones,**
   check what the source module itself imports at the top level — those names were
   also available transitively and must be re-imported directly. Example: models.py
   imports `User` from `django.contrib.auth.models`; forms.py used it via the
   wildcard without realising. Missing it caused a `NameError` at startup → 502.

### Phase 1 — what was done (May 2025, PR #79)

All critical bugs and security issues from Phase 1 were fixed in a single PR:

- Added missing `import re` to views.py (search crashed on every request).
- Fixed barcode-redirect kwarg: `pk=` → `item_id=` in two places.
- Added three bed-dimension fields to `PrinterForm` (new Printers crashed on save).
- Guarded `Filament.__str__` against null `material` FK.
- Fixed admin bulk-update action: `new_matl` → `material`.
- Fixed `normalize_hex_code()` regex to match the `#`-stripped value.
- Fixed drying-warning status comparison: string `"NEW"` → `self.Status.NEW`.
- Added `cast=bool` to `config("DEBUG", ...)` (string `"False"` was truthy).
- Guarded `item.location` null in Excel export.
- Deleted orphaned `inventory/import_products.py` (wrong path, removed fields).
- Wrapped `debug_toolbar` in `if DEBUG:` guards in settings.py and urls.py.
- Replaced `{{ chart_data|safe }}` with `json_script` + `JSON.parse` (stored XSS).
- Escaped `serial_number` and `color` via `django.utils.html.escape()` before
  building `tooltip_html` strings (stored XSS in tooltip).
- Added `LoginRequiredMixin` to four unprotected views.

### Phase 2 — what was done (May 2026, PRs #80, #81)

Dead code removal and structural cleanup. Hotfix PR #81 followed immediately
to repair a 502 caused by a missed transitive import (see step 7 above).

- Deleted `tables.py` + removed `django-tables2` from requirements/INSTALLED_APPS.
- Deleted `FilamentView` and `filament_view.html` (no URL route).
- Deleted `Order` and `Shipment` models + admin registrations; migration 0020
  drops their DB tables.
- Deleted 4 dead templates: `bulkadd`, `delete_item`, `search_results`, `movement`.
- Deleted `format_label()` and `generate_barcode()` from `barcode_utils.py`.
- Replaced hardcoded stale printer IP with correct LAN address `10.10.40.2`.
- Removed `numpy` and `pandas` from requirements (no longer needed).
- Replaced `from .models import *` / `from .forms import *` / `from .tables import *`
  in views.py and forms.py with explicit named imports.
- Wired up `inventory.signals` in `apps.py` `ready()`; switched `post_save` →
  `pre_save` to fix old-state read; fixed `StatusChoices` → `Status` typo.
- Converted `depleted`, `in_use`, `sold` from `BooleanField` to `@property`;
  columns dropped in migration 0020; admin `list_filter` updated.
- Added missing `from django.core.exceptions import ValidationError` to admin.py.

### Phase 3 — what was done (May 2026, PR #82)

Code quality and architecture improvements across all layers.

- Replaced `from .models import *` in admin.py with explicit imports + `ContentType`.
- Fixed `field` → `fields` typo in `HardwareAdmin`, `DryerAdmin`, `AMSAdmin` (was silently ignored by Django, showing all fields).
- Fixed `DryerAdmin` bogus field name `'max_temp"degC'` → `'max_temp_degC'`.
- Fixed `display_product_details` in `InventoryItemAdmin` — was using wrong reverse accessors (`product.filament.material`, `product.printer.mfr`) on instances that are already the real subclass; serial number now read from `obj` (InventoryItem) rather than the product.
- Fixed `mark_depleted` admin action to iterate queryset and call `instance.mark_depleted() + save()` — previously used `queryset.update()` which bypassed `save()` and left `date_depleted`/`location` out of sync.
- Fixed `view_log` to use `subprocess + tail -n 200` — previously `f.readlines()[-200:]` read the entire file.
- Moved hex validation from `Filament.save()` into `Filament.clean()` + `FilamentForm.clean_hex_code()` — invalid hex now shows as a form validation error instead of a 500.
- Moved printer dimension validation from `Printer.save()` into `Printer.clean()` — missing dims are now a form error.
- Added `InventoryItem.from_db()` that stores `_original_location_id`; `save()` now compares against it for location-change detection instead of doing an extra `SELECT` on every save.
- Extracted `BaseAddProductView` mixin; 5 `AddXxxView` classes each reduced from ~30 lines to 5 lines.
- Renamed `inventoryEditView` → `InventoryEditView`, `addInventoryView` → `AddInventoryView` (PascalCase).
- Replaced 10-line per-subclass UPC lookup loop with `Product.objects.filter(upc=upc).first()`.
- Replaced `from .views import *` in urls.py with explicit named imports.
- Fixed Dashboard N+1: replaced 3 Python-side table scans with DB aggregations; removed ~70 lines of loop logic.
- Consolidated 5 near-identical add-product templates into `add_product.html` using context vars.
- Fixed `base.html`: moved `{% block extra_scripts %}` after all JS library `<script>` tags; removed duplicate DataTables CSS.
- Created `requirements-dev.txt` (pre-commit, django-debug-toolbar); removed them + setuptools from `requirements.txt`; pinned python-barcode, brother_ql, python-decouple to minimum versions.

### Phase 3 continued — filament summary fixes (May 2026, PRs #92, #95)

- Added `material_type` field to `Material` (migrations 0021/0022 with data migration).
- Added `MaterialAdmin` bulk-edit for `material_type`; fixed `list_display_links`.
- Added `FilamentSummaryView` at `/filament-summary/` — material cards, DataTables, JS filtering, period toggle.
- PR #95 post-ship fixes: card sort by roll count; BLACK hex `#000000`; hex fallback from family; centering; "Color Family" header; period toggle contrast; material/subtype/color-family filter dropdowns with bidirectional sync and chips.

### Phase 4 — what was done (May 2026, PRs #100 + fixes)

Tests foundation + small features. All items from todo.md Phase 4 completed.

- Added `tests.py` with round-trip GET per view + `save()` per model; tests caught two latent bugs.
- Confirmed MAC discovery already removed from `barcode_utils.py` (done in Phase 2).
- Added `has_spool` read-only badge to `inventory_edit.html`; added `get_real_instance()` helper.
- Bumped barcode rendering params: `initial_module_width_mm` 0.3→0.4, `quiet_zone_mm` 2.0→3.0, `min_module_width_mm` 0.1→0.25.
- Fixed `add_product.html` back-button `NoReverseMatch` (pointed at `dashboard`).
- Generated missing migration `0023_alter_material_options`.
- Fixed `get_color_family()` to expand 3-digit hex codes before slicing.

### Phase 5 — what was done (May 2026, PR #108 — MERGED)

Filament Selection Guide Stage 1. Added 10 new fields to `Material` (spec said 13
but `requires_drying`/`drying_temp_c`/`drying_time_hours` were redundant with
existing `drying_required`/`dry_temp_ideal_degC`/`dry_time_hrs`). Migration `0024`.
`MaterialAdmin` gained a Guide Properties fieldset. `FilamentGuideView` at
`/filament-guide/` renders a DataTables reference table; boolean columns ✓/—;
warning colour on `requires_enclosure` and `drying_required`. Nav link added.
CSV template for data loading committed to `docs/filament-guide-data.csv`.

Post-merge: fill CSV with guide data, then dispatch Haiku agents to load via
Django shell. Unblocks Phase 7 (requirements picker).

### Phase 6 — what was done (June 2026, PR #113 — MERGED `0b354ef`, deployed since 2026-06-02)

Detailed location hierarchy + inventory audit mode, shipped together (one PR) to
support a full physical re-inventory.

- `Location` went from flat to typed/hierarchical: added `kind` (`Location.Kind`
  TextChoices: rack/shelf/dry_storage/ams/ams_slot/dryer/dryer_slot/printer),
  `parent` (self-FK), `unit` (FK→`InventoryItem`, `SET_NULL`, links a slot to the
  physical AMS/dryer record), `slot_index`. `default_status` made **nullable**
  (containers carry none). `Location.assignable()` returns leaf kinds only;
  `is_container` property. `is_printer` kept for back-compat.
- `seed_locations` management command (idempotent `get_or_create`): 72 rows —
  2 racks×5 shelves, 5 dry storage, 8 AMS×4 slots, 3 dryers×4 slots. **Slot `unit`
  FKs seeded null on purpose** (no reliable auto-match key for the existing units) —
  linked by hand in the Location admin post-merge; the 2 new dryers added via the
  normal flow.
- `filament_drying_warning()` rewritten to key off `kind` (DRY_STORAGE / PRINTER)
  with `is_printer` kept in an OR fallback, instead of the hardcoded
  `name == "dry storage"`.
- New `InventoryItem.Status.UNKNOWN = 7`, made durable by a **`save()` sticky-status
  guard**: `STICKY_STATUSES = (DEPLETED, SOLD, UNKNOWN)` skip the location→status
  recompute branch. This is a model-level guarantee (not the ad-hoc
  `_skip_status_from_location` flag, which doesn't survive reload) and also fixes a
  latent bug where re-saving a depleted/sold item could reset it to NEW.
- Audit mode: `AuditSession`/`AuditEvent` models; reconcile state machine lives in a
  new **`inventory/audit.py`** service module (not views — keeps views.py lean and
  the logic unit-testable). Views are thin CBVs (`AuditStart/Console/Scan/
  CloseLocation/Finalize/Abandon`) at `/audit/...`. Per-location-immediate reconcile;
  active-location focus is ephemeral in `request.session` (re-scan re-establishes it);
  a `CLOSED` AuditEvent durably marks reconciled locations so close/finalize are
  idempotent. Scan endpoint is input-agnostic (HTMX fragment) — USB wedge now, a
  camera JS POST later hits the same `/audit/scan/`. Unit items (AMS/Dryer/Printer or
  anything referenced by a `Location.unit`) are rejected so they can't be moved into a
  slot.
- `LOC-<id>` decoded by `BarcodeRedirectView` (jumps into the audit console focused
  there); printable via a new `LocationAdmin` "Print location labels" action reusing
  `generate_and_print_label`. Container kinds rejected **server-side** on the
  bulk-move path and the audit scan handler (form queryset filtering alone is
  bypassable). `UNKNOWN` excluded from the manual `MoveItemForm` status dropdown.
- Migrations split: `0025` schema (AddFields + nullable default_status + choices +
  audit models), `0026` RunPython backfill of `kind` from `is_printer`/name
  (case-insensitive, printer-first). `kind` added with `default='shelf'`, so no
  NOT-NULL-without-default trap. Seeding is a management command, never a migration.

Post-merge status (verified against live stack 2026-06-06): `seed_locations` **run on
prod** (25 backfilled flat rows → 97; the 72-row hierarchy now exists). Still pending
(James — needs admin/physical access): link slot `unit` FKs in admin, add the 2 new
dryers, **reconcile the 20 old flat shelves against the 10 new rack-child shelves**
(old flat rows hold current inventory; coexist with the new hierarchy), print
`LOC-`/`INV-` labels, eyeball `/audit/` render.

**Watch when hand-linking slot `unit` FKs:** a slot's `Location.unit` must point at
the physical AMS/dryer/printer's `InventoryItem`, never at slot contents. Anything a
`Location.unit` references is treated as a tracked machine by `audit._is_unit_item`
and becomes un-auditable as contents. AMS SD-1 slots 2–4 were mis-linked to a filament
roll (INV-17) during this manual step — caught in Audit No. 15, fixed in PR #128, which
also added a `Location.clean()` guard rejecting non-unit `unit` FKs at the model layer.

### Phase 6 follow-up — inline add-item during audit (June 2026, separate PR off master)

Lets the audit scan stream handle untracked spools without leaving the console.
Spec/plan in `docs/superpowers/`. Built subagent-driven (TDD, 6 tasks).

- `parse_code` gains a third kind: a **bare-numeric** scan is a UPC (`LOC-`/`INV-`
  keep prefixes — unambiguous). New `audit.add_or_queue_upc(session, location, upc)`:
  catalog hit → create `InventoryItem` at the active location + log new
  `AuditEvent.Action.ADDED`; catalog miss → queue an `AuditUnknownScan` row
  (`get_or_create`, deduped). **Logic in `audit.py`; label printing stays in the
  view** (`AuditScanView`), mirroring `AddInventoryView`.
- `ADDED` folded into `audit.PRESENT_ACTIONS`, so a just-added item is immune to the
  close-location UNKNOWN sweep (used identically in `close_location`, `_audit_context`,
  tally).
- `AuditUnknownScan` model + migration `0027` (additive): partial `UniqueConstraint`
  on `(session, upc, location)` WHERE `not resolved and not dismissed` → race-safe
  open-row dedup; same UPC at two locations = two rows (intended).
- Review page `/audit/unknowns/` (`AuditUnknownsView`/`ResolveView`/`DismissView`,
  login-required, POST mutations). Resolve stashes `pending_inventory` (incl. a
  threaded `unknown_scan_id`) and redirects into the **existing** add-product flow;
  `_resolve_pending_unknown` (matched-product path) + an inline `.update()` (new-product
  path in `BaseAddProductView.form_valid`) mark the scan `resolved` on item creation
  and pop the id. The list is **global/cross-session by design** (cleared after
  finalize, when no session is active — do NOT scope it to the active session).
- UI: "Added" stat card + "Unknown UPCs (N)" badge in the console body; finalize-page
  note when the queue is non-empty; `AuditUnknownScanAdmin`.
- Bug fixed in passing: `BaseAddProductView.form_valid` passed `shipment=None` into a
  non-nullable `CharField` (latent 500 on the add-product-from-inventory flow) →
  `shipment=pending.get("shipment") or ""`.

### Phase 17.2/17.3 — what was done (June 2026, PR #164)

Hex color backfill + filament guide Stage 2 requirements picker. Spec:
`docs/superpowers/specs/2026-06-12-filament-guide-picker-and-data-design.md`; plan:
`docs/superpowers/plans/2026-06-12-filament-guide-picker.md`.

**Schema changes (migrations 0037 + 0038):**
- `Material` (migration `0037`, RunPython backfill): `drying_required` BooleanField →
  `drying_need` CharField (`DryingNeed` TextChoices: `required`/`recommended`/`not_needed`;
  default `required`). `drying_required` kept as a `@property` (True only when
  `drying_need == REQUIRED`) so `filament_drying_warning()`, the admin, and all tests that
  *read* it are untouched — only tests that *write* it via `objects.create()` needed updating
  (replaced `drying_required=True` with `drying_need="required"`). Added `category` field
  (`Material.Category` TextChoices: `EVERYDAY`/`ENGINEERING`/`FLEXIBLE`/`SUPPORT`; SUPPORT
  excluded from the picker). Dropped `food_safe` BooleanField (never populated, not on any
  guide; RunPython backfill not needed — column was always False/null).
- `Filament` (migration `0038`): added `hex_code_2` (second hex for gradient swatches;
  nullable). Gradient rendering: `"GRADIENT"` color_family triggers a CSS linear-gradient
  swatch instead of a solid block; `hex_code` = start, `hex_code_2` = end.

**Two human-gated idempotent loaders:**
- `load_guide_data` — reads `docs/filament-guide-data.csv` (38 rows), updates `Material`
  guide properties (description, booleans, `drying_need`, `category`, etc.). Idempotent
  (`get_or_create` + field update). James runs after reviewing the CSV, then on prod:
  `manage.py migrate && manage.py load_guide_data`.
- `load_guide_data` **was run on prod (2026-06-12, `unchanged=38`)** — the guide picker is live.
- `load_filament_hex` — **RETIRED 2026-06-13, never run on prod.** It matched owned `Filament`
  spools by **color name** (NOT UPC — the CSV has no UPC column), with a narrowing step that
  silently fell back to color-only matching. Because color names collide across materials,
  `--overwrite` would have corrupted ~290 material-specific hexes to make 1 gradient land
  (verified on prod 2026-06-12). Superseded by the Phase 17.4 `FilamentColor` catalog +
  `seed_filament_colors`, which load the CSV verbatim and use an exact `(manufacturer,
  material, subtype, color)` key for the owned-✓ join (no fuzzy color matching).

**Stage 2 requirements picker on `/filament-guide/`:**
- Base-polymer cards: each card surfaces the best-scoring subtype (JS scoring over a
  `json_script` payload, not a server round-trip). EVERYDAY materials get "Everyday
  favorite" prominence styling + float to top. Empty-state band shown when no cards match.
- Category tabs / prominence: SUPPORT excluded entirely from the picker. EVERYDAY
  prominence driven by `material.category == EVERYDAY`.
- Reference table remains on the same page, now grouped by `category` (sort-only via
  DataTables column sort; the rowGroup extension is NOT bundled — a visual-pass item if
  collapsible headers are wanted).
- **Prod deploy checklist** (migrations drop two columns — `food_safe`, and the boolean
  `drying_required` is replaced by `drying_need` — both safe, nightly backup is live):
  `manage.py migrate` + `manage.py load_guide_data`. (The `load_filament_hex` loader was
  retired 2026-06-13; Phase 17.4's `seed_filament_colors` replaces it.)

### Phase 17.4 — what was done (June 2026)

Printable color-reference sheets + manufacturer store links — finishes Phase 17 (item #9).
Spec: `docs/superpowers/specs/2026-06-13-filament-color-sheets-design.md`; plan:
`docs/superpowers/plans/2026-06-13-filament-color-sheets.md`.

- New **`FilamentColor`** catalog (migration `0039`; manufacturer-aware, **decoupled from
  `Material`** so a color is never dropped for lack of a `Material` row). `clean()`/`save()`
  normalize hex like `Filament`; `unique_together` on `(manufacturer, material_name,
  material_type, color_name)`. This is the color catalog 17.2's checklist named but never built —
  the CSV (`docs/filament-colors.csv`, 227 colors) is now loadable into the DB.
- **`seed_filament_colors`** command (logic in `inventory/color_catalog.py` for testability,
  mirroring the `guide_data.py` loader/command split). Idempotent `get_or_create`; **defaults
  brand to `Bambu Lab`** and reads an **optional `manufacturer` CSV column** (so Polymaker rows
  append later with no code change); resolves the `material` FK by `(name, type)` and reports
  colors with no matching `Material`. Human-gated like the other loaders.
- **`Material.store_slug`** (same migration `0039`) + **`inventory/store_links.py`** `store_url()`:
  Bambu product page when `store_slug` is set AND brand matches, brand **search fallback**
  otherwise, `None` for unknown brands (template hides the button). Wired only into
  `FilamentColorSheetView` (`views.py:1399`); the **color-guide row store link is DEFERRED**
  (plan Task 6 Step 4 skipped — `filament_color_guide.html` renders aggregated rows without a
  single `manufacturer`/`material` in scope, so no `store_link` context exists there; the sheet's
  own button already covers the primary need). Deliberately **not** a per-color/per-brand slug
  table yet (YAGNI; upgrade path noted in the spec).
- Views (both `LoginRequiredMixin`, under the filament hub, carry `filament_nav.html`):
  `FilamentColorSheetIndexView` → `/filament/color-sheets/` (group cards, own-counts via ORM
  aggregation) and `FilamentColorSheetView` → `/filament/color-sheets/<slug>/`
  (`slug = slugify(manufacturer-material-subtype)`, resolved against each group's computed slug —
  no stored slug field; 404 on miss). **Owned-✓ join is exact** `(manufacturer, material, subtype,
  color)` over **in-stock** items only (excludes DEPLETED/SOLD/UNKNOWN) — sidesteps the
  color-only over-match bug of the now-retired `hex_loader.py`.
- Print sheet: CSS-grid swatch wall, gradient swatches reused from `filament_color_guide.html`,
  owned swatches get a double border + ✓ + roll count, `@media print` hides nav/buttons
  (`break-inside: avoid`), inline `window.print()` trigger (no new JS file). `FilamentColorAdmin`
  (unfold base) is fully editable so James can correct/append colors by hand.
- **No new dependencies, no `.env`/compose/nginx changes.** Migration `0039` is additive.
  **Prod deploy:** auto-deploy runs `0039`, then human-gated `manage.py seed_filament_colors`
  (227 rows), then optionally fill Bambu `store_slug`s in admin for precise product links.

### Roadmap (rewritten 2026-06-09 — Phases 11–18)

A 10,000-ft review (2026-06-09) replaced the old Phase 5–10 framing with a forward,
dependency-ordered roadmap. **`todo.md` is rewritten** (Phases 11–18 up top; completed
Phases 1–10 archived at the bottom). Brainstorm + ASCII wireframes in `ideas.md`; design
docs under `docs/`: `architecture-review-2026-06-09`, `workflow-and-domain-design`,
`bambu-mqtt-integration`, `admin-2.0`, `filament-data-pipeline`, `db-backup-status`. Landed
via **PR #129** (roadmap/docs) + **PR #130** (backup script); `docs/overnight-build-kickoff.md`
is the agent execution guide. Decisions captured: daily-driver UX + DB backup first; Bambu
MQTT phased (read-only telemetry mirror first, auto-sync later); **FULL procurement**; the top
rework = extract an `inventory/items.py` `move_to()`/`deplete()`/`set_status()` service (the
`_skip_status_from_location` flag dance is copy-pasted across audit/bulk/admin — `models.py:529`).

- **Phase 11.1 DB backup:** ✅ DONE & LIVE (2026-06-09). Transport solved via CIFS-on-host +
  bind-mount (the Plex CT 106 pattern; `uid=101000,gid=101000`); `/mnt/nas-backup` in CT 105 is
  the real Synology share. Restore-verified (641/107/264); nightly cron `0 2 * * *` as `jcoller`.
  Retention: 30 dailies + 12 monthly anchors. See `docs/db-backup-status.md`. **Never re-attempt
  the in-LXC NFS mount.**
- **Phase 6 manual prod setup:** ✅ **DONE** (2026-06-09/10 reconcile, direct prod shell edits,
  each batch backed up first). Dry-storage shelves re-typed `shelf`→`dry_storage` (the mis-typing
  silently bypassed the `kind==DRY_STORAGE` drying guard at `models.py:708`) + renamed/deduped;
  stray `Dryer XX` + empty legacy flat shelves deleted. The "215 lost items" was mostly inactive
  history (147 on a `Receiving` flat shelf + 52 null depleted); only ~68 active, already on correct
  shelves. **All AMS + dryer slot `unit` FKs now linked by serial — AMS 34/34, dryers 14/14, 0
  unlinked.** James's serial data exposed 3 pre-existing errors that were fixed: Dryer 3↔4 links
  swapped, INV-667/668 on the wrong dryer product (DB-04→DB-05 SpacePi X4), and AMS HT-1 mis-linked
  to INV-501 (whose serial is actually HT-2). Created 3 machine items (Dryer 1 INV-676 Creality
  2-slot — container was misnamed "Sunlu S4 Dryer 1"; Dryer 2 INV-677 Sunlu S4; AMS HT-1 INV-678).
  **Lesson: serial is the only reliable machine↔record key** — seed names/slot-counts and hand-set
  links both had errors. Unblocks Phase 16.3 MQTT auto-sync.
- **Phase 17 filament data:** source files are in the repo (`filament_TDS/`, `filament_hex/`,
  `filament-guide-en.pdf`). Parsing needs a **dev-only** `pypdf` (approved; never a prod/image
  dep); the hex screenshot PNGs read via vision. See `docs/filament-data-pipeline.md`.
- **Django upgrade**: ✅ Done — prod on Django 6.0.5 (constraint bump `4d07401`, 2026-05-15).
  6.0 is **not** an LTS (5.2 was the prior LTS) — track the next 6.x LTS for a long-haul pin.

## Environment notes

### Local dev environment on this LXC (Claude Code, `10.10.20.16`)

Set up via PR (May 2026):

- **Python 3.12** managed by [`uv`](https://docs.astral.sh/uv/) — installed at
  `~/.local/share/uv/python/`. The Debian 12 system Python is 3.11, which is too
  old for Django 6.x; `uv` keeps a 3.12 alongside it without touching system
  packages.
- **Project venv** at `~/.venvs/inventory` with `requirements.txt` +
  `requirements-dev.txt` installed. Activate with
  `source ~/.venvs/inventory/bin/activate` or call binaries directly via
  `~/.venvs/inventory/bin/python`.
- **Local `.env`** at the repo root (gitignored) holds a dev-only
  `DJANGO_SECRET_KEY` and `DEBUG=True` so `manage.py check` boots without secrets.
  This file is **separate** from the production env (`~/.env_inventory` on the
  app LXC) — do not copy real secrets here.
- **`pre-commit` hooks** are installed in the local `.git/hooks/`. The full hook
  set: black, ruff (`--fix`), djlint-django, shellcheck, plus existing
  trailing-whitespace / yaml / migrations checks. Config in
  `.pre-commit-config.yaml`; ruff/djlint settings in `pyproject.toml`.
- **SSH alias** `inventory-manager` reaches the app LXC (`10.10.20.17`) — use
  for `docker exec` / `docker logs` against the running stack.

If recreating the venv: `uv venv --python 3.12 ~/.venvs/inventory && uv pip install --python ~/.venvs/inventory/bin/python -r requirements.txt -r requirements-dev.txt`.

### Production env

The app's env file is `.env_inventory` at `$HOME` on the app LXC (see
docker-compose.yml). **It is `root:root` 644 — `jcoller` can read it (the app loads it) but
CANNOT append (no sudo on the app LXC).** So:
- A new **non-secret** `config()` var (e.g. a path) goes in the version-controlled
  `docker-compose.yml` `environment:` block — NOT `.env_inventory`. Example: `SQLITE_DB_PATH`.
- A new **secret** must be added to `~/.env_inventory` by James (root); flag it for him.

### Database location (since Phase 16.1 PR-A, 2026-06-10)

The prod SQLite DB lives at **`~/inventory_db_dir/inventory_db.sqlite3`** on the app LXC (a
**directory** bind-mounted at `/app/db`, so WAL's `-wal`/`-shm` siblings are shareable across
containers). WAL is enabled (`journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000`) via
the `connection_created` receiver in `inventory/db_pragmas.py`. **Any change to the DB
path/layout must also update `scripts/deploy.sh`** — it has its own `[ -f <db> ]` guard that
aborts the deploy (this bit us once: prod-down hotfix `b2e8758`). `backup_db.py` and
`ha_stats_export.py` read this path; `mode=ro` reads of the WAL DB work (the container writes
`-wal`/`-shm` as a jcoller-mapped uid). DB stays SQLite (revisit Postgres only on measurable
lock contention).

### Docker compose services (entrypoint gotcha)

The `Dockerfile` sets **`ENTRYPOINT ["/app/entrypoint.sh"]`**, so a compose **`command:` is
passed as *args* to entrypoint.sh and ignored** (it execs gunicorn regardless). `web` works by
coincidence; the `telemetry` service (Phase 16.1 PR-B, runs `manage.py run_telemetry_consumer`)
had to override **`entrypoint:`**, not `command:` (cost a hotfix `c8ffd98` — it ran a 2nd
gunicorn first). **Any new non-web compose service must override `entrypoint:`.** Note
`docker compose config -q` validates syntax but NOT this — only a real deploy + `docker logs`
check catches it. There are now 3 services: `web` (gunicorn + migrations), `telemetry`
(read-only MQTT consumer, shares the WAL DB dir), `nginx`.
