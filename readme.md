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
left unaccounted-for at visited locations are marked depleted by default. After first
seeding, link each AMS/dryer slot group to its unit's inventory record via the `unit`
field in the Location admin. The `unit` field accepts only physical AMS/dryer/printer
inventory records — linking it to slot contents (a filament roll) is rejected, since
that would make the audit treat the roll as a tracked machine instead of contents.

To set a location you can scan its `LOC-` barcode **or** an AMS/dryer/printer's
front-panel **serial number** — the serial focuses that whole unit and the console
audits all of its slots together (this needs the `unit` links above). The location
card shows how many items are *expected*, *scanned*, and *not yet scanned*, and the
close-location message reports how many were accounted for vs. flagged unknown — handy
for a quick count check.

During the walk you can also scan an **untracked spool's UPC** (its bare-numeric
manufacturer barcode). If that UPC is already in the catalog, a new inventory item is
created at the active location and its `INV-` label prints immediately. If it isn't,
the scan is queued; clear the queue afterward at **Unknown UPCs** (`/audit/unknowns/`),
which hands each one into the normal add-product form (pre-filled with the UPC and
location) and marks it resolved once the item is created. Scanned a UPC by mistake
instead of an INV tag? The console and finalize page list **items added this session**
with an Undo/Remove button.

At finalize, each unaccounted-for item can be left **unknown** ("in limbo") instead of
depleted via a per-row checkbox — useful for something found out of place that you'll
re-shelve after the walk. To track these down later, the **Search** page has a
**Lost & Found** button (one click → every `UNKNOWN` item plus anything with no
location); the search form also filters by status (multi-select, including
depleted/sold/unknown), item type, location subtree, and date-added range.

Missing or unreadable `INV-` tags can be reprinted in bulk: search for the items, tick
the rows, and use the **Reprint tags** button in the selection bar.

## Quick move & phone scanning

For the everyday "this spool now lives here" task without starting a full audit, use
**Move** in the nav (`/move/`): scan an item (`INV-` tag or its QR), then scan the
destination (a `LOC-` barcode or an AMS/dryer/printer **serial**). The item moves via
the shared move service and its status follows the destination's default. If the
destination slot/unit is already full, the page asks **what's leaving to make room** —
deplete the current occupant or rehome it. Wet filament headed for dry storage is
blocked and a printer destination warns, reusing the same drying-safety check as the
rest of the app.

`INV-` and `LOC-` labels now print a **QR code alongside the Code128 barcode** —
phone cameras decode QR far more reliably than 1-D barcodes, and the QR encodes a link
straight to the item/location page. The **Move** and **Audit** scan boxes have an
in-browser **camera scanner** (the camera button next to the input) that decodes
barcodes/QR with the device camera over HTTPS, so a phone works as the scanner with no
extra hardware. The app is an installable **PWA** — "Add to Home Screen" from a phone
browser gives a one-tap field shortcut.

## Print jobs & utilization

Log a print run from **Print Jobs** in the nav (`/print-jobs/`): pick the printer,
enter the file name, start/end (or a duration), and the result, then add one
**filament line per spool** used (grams used is preferred; percent used is the
fallback when the spool's catalog weight is unknown). Saving applies consumption —
each spool's `percent_remaining` is decremented, and a spool that reaches 0% is
marked **depleted** automatically (no separate consumption log; `PrintJobFilament`
*is* the consumption record). MQTT auto-population will write the same tables later.

**Utilization** (`/utilization/`, also linked per-printer from a printer's item
page) aggregates printer hours, job count, success rate, and kg consumed by
material/color — all via DB aggregation.
## Procurement & receiving

Track what you ordered and what you paid. Create a **Supplier** and a **Purchase
Order** (with its lines) in the Django admin, then work it from **Orders** in the nav
(`/purchase-orders/`):

- A PO groups one or more **lines** (one catalog product each, with `qty_ordered`,
  `unit_cost`, and a `track_individually` flag). Tracked lines mint a real inventory
  item per received unit; **cost-only** lines (e.g. bagged screws) never mint items and
  count toward spend only as a line total.
- Open a PO's **Receive** console (`/purchase-orders/<id>/receive/`), pick a receiving
  location, and scan each product's **UPC** (USB wedge or typed). Tracked goods are
  minted into that location via the shared move service, stamped with the
  `unit_cost`/`source_line` from the PO line, and get an `INV-` label printed
  immediately (soft-fails if the printer is down). The PO status advances
  Ordered → Partially received → Received automatically.
- The PO detail page reconciles **ordered vs received vs outstanding** with per-line and
  order totals (subtotal + shipping + tax). The **Spend Report** (`/spend-report/`)
  totals what you actually paid — tracked items' `unit_cost` unioned with cost-only
  lines' received totals — broken out per supplier.

Per-item `unit_cost` is what you *paid* (denormalized onto the item so it survives the
PO being edited or deleted), distinct from the catalog `Product.price` (list /
replacement value).

> **Receipt file upload is not wired yet.** `PurchaseReceipt.attachment` (a `FileField`)
> exists for forward-compatibility but is inert: serving uploads needs `MEDIA_ROOT`/
> `MEDIA_URL`, an nginx alias, and a bind-mounted `media/` volume — none configured
> today.

## Filament guide & requirements picker

**Filament Guide** (`/filament-guide/`) has two modes on the same page:

- **Requirements picker** — base-polymer cards (PLA, PETG, ABS, …) with the
  best-matching subtype surfaced per card. Client-side JS scores each subtype against
  your selected requirements (UV resistant, flexible, high strength, heat resistant,
  easy to print, budget friendly, impact resistant, requires enclosure). EVERYDAY
  materials float to the top; SUPPORT materials are excluded. Selecting no requirements
  shows all materials.

- **Reference table** — full guide data (temperatures, compatibility, boolean
  properties) in a DataTables table, sortable by category.

Guide property data is loaded from `docs/filament-guide-data.csv` via the
`load_guide_data` management command (human-gated — review the CSV first). Hex
color swatches (including gradient support for dual-color filaments) are loaded from
`docs/filament-colors.csv` via `load_filament_hex`.

## Color reference sheets

**Color Sheets** (`/filament/color-sheets/`) renders printable, Bambu-style swatch
cards — one sheet per `(manufacturer, material, subtype)` — showing every catalog
color for that material, with the colors you currently own visually flagged (double
border + ✓ + roll count). Gradient colors render as a `linear-gradient` swatch. Each
sheet is print-optimized (`@media print` hides the nav/buttons); use the browser's
"Print → Save as PDF" to export. A "View in Store" button deep-links to the
manufacturer's product page (Bambu, when a `Material.store_slug` is set) or falls back
to a brand search; the same link also appears on the color-guide rows.

The catalog lives in a `FilamentColor` model, seeded from `docs/filament-colors.csv`
via the `seed_filament_colors` management command (human-gated; idempotent; defaults
the brand to `Bambu Lab` and accepts an optional `manufacturer` CSV column so other
brands drop in without code changes).
