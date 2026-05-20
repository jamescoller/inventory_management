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
- **Database:** SQLite at `inventory_db.sqlite3` — not version-controlled, lives on
  the app LXC (note: a future task is to create a backup of this DB)
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
  `PRINTER_MAC`, `PRINTER_IP`.
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

1. Run `python manage.py check` — catches Django configuration errors.
2. For model changes, confirm a migration exists and is included.
3. For template changes, verify the template renders (check for missing context
   variables or broken block tags).
4. If `requirements.txt` changes, verify the lock is consistent and the image
   will still build.
5. Before suggesting a PR, check `readme.md` and `todo.md` — update them if the
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

## Working from todo.md

`todo.md` is the canonical roadmap. Phases are ordered by priority; within a
phase, bugs come before enhancements. Before starting any phase:

1. Read `todo.md` in full so the complete scope is understood before touching code.
2. Read all affected files in parallel (views, models, forms, admin, settings,
   templates) — map each item to its exact location before writing a single edit.
3. Fix in logical groups that minimise re-reading: model-layer changes first,
   then view-layer, then templates, then config.
4. Syntax-validate every modified Python file with `ast.parse` (Django is not
   installed in this LXC — `manage.py check` requires the full Docker environment).
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

## Environment notes

- Django is **not** installed in this Claude Code LXC. `python3 manage.py check`
  will fail. Use `python3 -c "import ast; ast.parse(open('file.py').read())"` for
  syntax validation. Full checks require SSH + `docker exec` on the app LXC (`.17`).
- The app's env file is `.env_inventory` at `$HOME` on the app LXC (see docker-compose.yml).
- `ast.parse` only catches syntax errors, not runtime `NameError`s from missing
  imports. After replacing wildcards with explicit imports, manually scan for names
  the module uses but doesn't import directly.
