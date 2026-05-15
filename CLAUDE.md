# CLAUDE.md

Project context for Claude Code working on this inventory management repository.

## What this repo is

A Django 4.2 web application for tracking 3D printer consumables — filament spools,
hardware, printers, AMS units, and drying equipment. Deployed as a Docker Compose
stack (Gunicorn + Nginx). The app also integrates with a Brother QL label printer
for barcode generation.

GitHub: https://github.com/jamescoller/inventory_management
Default branch: `master`

## Hardware & topology

- **App host:** Proxmox LXC at `10.10.20.17` — Docker Compose stack, GitHub Actions
  self-hosted runner, and SQLite database all live here. Nothing for this app is on
  the NAS anymore.
- **App URLs:** `http://inventory.home` (via NGINX + PiHole), `http://10.10.20.17:8080`
- **Database:** SQLite at `inventory_db.sqlite3` — not version-controlled, lives on
  the app LXC
- **Claude Code LXC:** Debian 12 on Proxmox at `10.10.20.16` — this is where Claude
  Code runs and where all code editing happens. Not the same machine as the app host.
- **Network:** server VLAN (`10.10.20.x`)
- **Co-located on the same VLAN:**
  - Home Assistant Green (`10.10.20.2`)
  - Proxmox host — Minisforum UM790 Pro, Ryzen 9 7940HS, 32 GB DDR5 (running LXCs)
  - Claude Code LXC (`10.10.20.16`, Debian 12 on Proxmox)
  - App LXC (`10.10.20.17`, Debian 12 on Proxmox)
  - Raspberry Pi 5
  - Mac Mini M2

## Accessing the live app

**Browser** — `http://inventory.home` or `http://10.10.20.3:8080` are reachable
directly from this LXC.

**SSH to NAS** — No alias configured yet in `~/.ssh/config`. The NAS is at
`10.10.20.3`; standard Synology SSH is on port 22. Add an alias before doing
Docker management tasks:
```
Host synology
    HostName 10.10.20.3
    Port     22
    User     james
    IdentityFile ~/.ssh/id_ed25519_github
```

**Docker management on NAS** — Once SSH'd in, the Compose stack lives at
`/volume1/docker/inventory_management`. Use `docker-compose` commands there.

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

- `.env` file is **not** version-controlled (gitignored). On the NAS it is symlinked
  from `/home/runner/.env_shared`.
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
  and `NET_RAW` capabilities in the Docker container.
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

## Environment notes

- Django is **not** installed in this Claude Code LXC. `python3 manage.py check`
  will fail. Use `python3 -c "import ast; ast.parse(open('file.py').read())"` for
  syntax validation. Full checks require SSH + `docker exec` on the NAS.
- The app's env file is `.env_inventory` at `$HOME` on the NAS (see docker-compose.yml).
  CLAUDE.md says `.env_shared` in some places — the compose file is authoritative.
