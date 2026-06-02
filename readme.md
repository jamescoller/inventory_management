[![Deploy to inventory-manager LXC](https://github.com/jamescoller/inventory_management/actions/workflows/deploy.yml/badge.svg?event=push)](https://github.com/jamescoller/inventory_management/actions/workflows/deploy.yml)

## What this is

A Django web application for tracking 3D printer consumables — filament spools,
hardware, printers, AMS units, and drying equipment. Deployed as a Docker Compose
stack (Gunicorn + Nginx) on a Synology NAS. Integrates with a Brother QL label
printer for barcode generation.

---

## Local development

### Prerequisites

- Docker and Docker Compose
- A `.env_inventory` file in your home directory (see Environment below)

### Build and run

```bash
git clone https://github.com/jamescoller/inventory_management
cd inventory_management
docker compose up --build -d
```

Access at `http://localhost:8080`. Migrations and `collectstatic` run automatically
at container start via `entrypoint.sh`.

### Stop

```bash
docker compose down
```

---

## Production deployment

Pushes to `master` trigger an automatic deploy via GitHub Actions on the
self-hosted runner hosted on the NAS. The workflow runs `scripts/deploy.sh`,
which does a hard reset to `origin/master` and rebuilds the Docker Compose stack.

**Live URLs:** `http://inventory.home` (via NGINX + PiHole) or `http://10.10.20.3:8080`

---

## Environment

The app reads configuration from `.env_inventory` (via `python-decouple`).
Required variables:

| Variable | Description |
|---|---|
| `DJANGO_SECRET_KEY` | Django secret key |
| `DEBUG` | `True` / `False` (use `False` in production) |
| `ENABLE_BARCODE_PRINTING` | `True` / `False` — enables Brother QL printing |
| `PRINTER_IP` | IP address of the label printer |

On the NAS the file lives at `$HOME/.env_inventory` and is referenced by `docker-compose.yml`.

---

## Migrations

Migrations are applied automatically by `entrypoint.sh` on container start.
To generate a new migration after a model change:

```bash
docker exec -it <container> python manage.py makemigrations
```

Include the resulting migration file in your PR.

## Locations & inventory audit

The physical storage hierarchy (receiving racks/shelves, dry storage, AMS units +
slots, dryers + slots) is seeded with an idempotent management command:

```bash
docker exec -it <container> python manage.py seed_locations
```

Print each location's `LOC-<id>` label from the Django admin (Locations → "Print
location labels" action). Then run an audit from **Audit** in the nav (`/audit/`):
scan a location barcode, scan the item tags physically present, and finalize — items
left unaccounted-for at visited locations are marked depleted. After first seeding,
link each AMS/dryer slot group to its unit's inventory record via the `unit` field in
the Location admin.
