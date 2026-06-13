# Phase 17.4 — Color Reference Sheets + Bambu Store Link

**Date:** 2026-06-13
**Status:** Design approved, pending spec review
**Roadmap item:** `todo.md` Phase 17.4 (item #9)

## Goal

Two related deliverables that finish Phase 17:

1. **Per-material color reference sheets** — printable, Bambu-style swatch cards, one per
   `(manufacturer, material, subtype)`, showing every catalog color for that material with
   the colors you own visually flagged.
2. **"View in Store" link** — a per-material deep link to the manufacturer's store
   (product page where a curated slug exists, search URL otherwise), reused on the existing
   color-guide rows (roadmap item #9).

The sheets render the **full manufacturer palette** (a reference card, including colors not
owned), with owned colors marked. Initial data is all Bambu Lab; the model is
manufacturer-aware so Polymaker (and later brands) drop in without code changes.

## Background / why a catalog model now

The color data lives in `docs/filament-colors.csv` (227 Bambu colors), **not** in the DB.
17.2's checklist named "seed a color catalog" but only built the CSV + a (buggy) hex loader.
This phase builds the catalog the sheets need.

Seeding a catalog **sidesteps the `hex_loader.py` matching bug** (color-name-only match with a
silent color-only fallback that over-matches across materials — see the 2026-06-12 prod
investigation): seeding loads the CSV verbatim, and the owned-✓ join uses an **exact**
`(manufacturer, material, subtype, color)` key — the reliable match the loader should have used.

## Non-goals (YAGNI)

- **No live price** (no public Bambu store API — Trashed).
- **No per-color store deep link** — Bambu sells a material as one product with color variants;
  the link lands on the product page, user picks the variant.
- **No downloadable-file endpoint / new PDF dependency** — the browser's "Print → Save as PDF"
  on a print-optimized HTML page covers it. No `reportlab`/`weasyprint`.
- **No per-brand curated slug table yet** — Bambu slugs live on `Material`; other brands fall
  back to search until curation is actually wanted (see Store link below).
- **No change to the existing `hex_loader.py`** here — that's a separate cleanup (tracked in
  `todo.md`); this phase neither runs nor depends on it.

## Data model

### New: `FilamentColor` (migration `0039`)

The color catalog. Decoupled from `Material` so a color is never dropped for lack of a
`Material` row (e.g. PLA Gradient, which may have no Material).

| field | type | purpose |
|-------|------|---------|
| `manufacturer` | `CharField(max_length=100, default="Bambu Lab")` | brand; mirrors `Filament.manufacturer` (free text, same help text) |
| `material_name` | `CharField(max_length=100)` | base polymer, from CSV `material` (e.g. "PLA") |
| `material_type` | `CharField(max_length=50, blank=True, default="")` | subtype, from CSV `material_type` (e.g. "Matte") |
| `color_name` | `CharField(max_length=80)` | from CSV `color_name` |
| `hex_code` | `CharField(max_length=9)` | swatch fill (`#RRGGBB`); start color for gradients |
| `hex_code_2` | `CharField(max_length=9, blank=True, default="")` | set ⇒ gradient swatch (end color) |
| `material` | `ForeignKey(Material, null=True, blank=True, on_delete=SET_NULL)` | resolved at seed time by `(name, type)`; supplies specs + `store_slug` for the header. **Nullable**: a color with no matching Material is still kept. |
| `source` | `CharField(max_length=120, blank=True, default="")` | CSV `source_file`/notes, for provenance |

- `Meta.unique_together = [("manufacturer", "material_name", "material_type", "color_name")]`
- `Meta.ordering = ["manufacturer", "material_name", "material_type", "color_name"]`
- `__str__` → `f"{manufacturer} {material_name} {material_type} — {color_name}"`.
- `clean()`/`save()`: normalize hex like `Filament` does (reuse the `_norm_hex` helper pattern;
  lowercase→`#`-prefixed, validate 3/6 hex digits). Gradient ⇒ both hexes required.

### Changed: `Material.store_slug` (same migration `0039`)

`store_slug = CharField(max_length=120, blank=True, default="")` — the Bambu product-page
slug (e.g. `pla-matte` → `.../products/pla-matte`). Filled by James in admin; blank ⇒ search
fallback. Manufacturer-agnostic `Material` means this is the **Bambu** slug; non-Bambu sheets
search (see Store link).

## Seeding: `seed_filament_colors` management command

`inventory/management/commands/seed_filament_colors.py` (+ logic in `inventory/color_catalog.py`
for testability, mirroring `guide_data.py`/`hex_loader.py` split).

- Reads `docs/filament-colors.csv` by default (`--csv` override).
- **Optional `manufacturer` column**: when absent or blank, defaults to `"Bambu Lab"`. This is
  how Polymaker rows get appended later (same CSV or a second one).
- Idempotent `get_or_create` by `(manufacturer, material_name, material_type, color_name)`;
  updates `hex_code`/`hex_code_2`/`source` on existing rows.
- Resolves the `material` FK by `Material.objects.filter(name__iexact=material_name,
  material_type__iexact=material_type).first()`; leaves null + **reports** when no Material row.
- Output: `created=N updated=N unchanged=N`, then the list of colors whose material had no
  `Material` row. Human-gated (James runs on prod after review), like the other loaders.

## Store link helper: `inventory/store_links.py`

A small, dependency-free helper. **Manufacturer → store config** dict (extensible by one entry):

```python
STORE_CONFIG = {
    "Bambu Lab": {
        "base": "https://us.store.bambulab.com",
        "product": "/products/{slug}",
        "search":  "/search?q={query}",
    },
    "Polymaker": {
        "base": "https://us.polymaker.com",
        "search": "/search?q={query}",   # no product template until slugs are curated
    },
}

def store_url(*, manufacturer, material=None, query=""):
    """Product-page URL when manufacturer matches material.mfr AND material.store_slug
    is set; otherwise the brand's search URL for `query`. None if brand unknown."""
```

- Bambu sheet with a `Material.store_slug` (and `Material.mfr == "Bambu Lab"`) → product page.
- Otherwise → `…/search?q=<material + " " + brand-relevant terms>` (URL-encoded).
- Unknown manufacturer → returns `None`; template hides the button.

Upgrade path (noted, not built): if curated per-brand slugs are wanted, replace the
`Material.store_slug` lookup with a `MaterialStoreLink(manufacturer, name, type, slug)` table.

## Views & URLs

All under the existing filament hub; both carry the `filament_nav.html` tab bar; both
`LoginRequiredMixin`. Group key throughout is `(manufacturer, material_name, material_type)`.

- **`FilamentColorSheetIndexView`** → `/filament/color-sheets/`
  Lists the distinct groups (one card each): manufacturer, material, subtype, total color
  count, "you own N", link to the sheet. Group/own counts via ORM aggregation, not Python loops.

- **`FilamentColorSheetView`** → `/filament/color-sheets/<slug>/`
  `slug = slugify(f"{manufacturer}-{material_name}-{material_type}")` (e.g. `bambu-lab-pla-matte`).
  Resolve by matching the slug against the computed slug of each group (small set; no stored
  slug field needed). 404 if no group matches. Context: the group's `FilamentColor` rows
  (ordered), the resolved `Material` (for header specs + store link), the store URL, and the
  set of owned `(color_name)` for this group with roll counts.

### Owned-✓ join

For the group's `(manufacturer, material_name, material_type)`, owned colors =
`Filament` → `InventoryItem` where:
- `Filament.manufacturer__iexact == manufacturer`,
- `Filament.material.name__iexact == material_name` and `material_type__iexact == material_type`,
- `InventoryItem.status` **in-stock** (exclude DEPLETED/SOLD/UNKNOWN),
grouped by `Filament.color__iexact`, with a roll count. A color is "owned" iff its
case-insensitive name appears in that set. Exact key — no fuzzy color-only matching.

## Templates

- **`filament_color_sheets.html`** — the index grid (Bootstrap cards), tab bar, intro line.
- **`filament_color_sheet.html`** — the print sheet:
  - Header: manufacturer · material · subtype, color/owned counts, key specs from `Material`
    (print temp, drying need/temp), and the "View in Store" button.
  - CSS-grid swatch wall: each swatch = color block + name + hex. **Gradient** colors render a
    `linear-gradient(hex_code, hex_code_2)` block (reuse the existing gradient swatch rendering
    from `filament_color_guide.html`). **Owned** swatches get a double border + ✓ + roll count.
  - `@media print`: hide nav/tab bar/buttons, white background, avoid swatch page-breaks
    (`break-inside: avoid`). A "Print sheet" button triggers `window.print()`.
  - Any inline JS (just the print trigger) kept minimal; no new JS file needed.

### Store link on the color guide (item #9)

`filament_color_guide.html` rows gain a small "Store" link built from the same `store_url`
helper (manufacturer + material + color already present on those rows). Cheap reuse.

## Admin

`FilamentColorAdmin(UnfoldModelAdmin)` (matches the 18.1 unfold base), `@admin.register`:
- `list_display`: a `format_html` color swatch, `manufacturer`, `material_name`,
  `material_type`, `color_name`, `hex_code`, `hex_code_2`, `source`, owned indicator.
- `list_filter`: `manufacturer`, `material_name`, `material_type`.
- `search_fields`: `color_name`, `material_name`, `material_type`.
- `list_editable` on `hex_code`/`hex_code_2` for quick fixes; `autocomplete`/raw-id on `material`.
- Fully editable so James can correct/append colors by hand (the explicit ask).

## Testing (`tests.py`, existing pattern)

- Seed command: idempotency (`created` then `unchanged` on re-run); `manufacturer` default when
  column absent; Material-FK resolution; unmatched-material reporting; gradient row → both hexes.
- Owned-✓ join: an in-stock spool counts; a DEPLETED/SOLD spool does **not**; brand mismatch
  does **not** (Polymaker spool ≠ Bambu sheet).
- Views: index + sheet round-trip GET (200); unknown slug → 404.
- `store_url` helper: Bambu + slug → product URL; Bambu no slug → search; Polymaker → search;
  unknown brand → None.
- `FilamentColor.clean()` hex normalization + gradient validation.

## Migration / deploy notes

- Migration `0039`: add `FilamentColor` + `Material.store_slug`. Additive, no data loss; nightly
  backup is live regardless.
- Auto-deploy runs the migration; **`seed_filament_colors` is human-gated** — James runs it on
  prod after reviewing the CSV (`manage.py seed_filament_colors`), then fills Bambu `store_slug`s
  in admin as desired.
- No new dependencies, no `.env`/compose/nginx changes.
- Add the sheets to `filament_nav.html` and any filament-hub mode list.

## Deferred / follow-ups (out of scope here)

- Curating Polymaker `store_slug`s / a `MaterialStoreLink` table (only if search isn't enough).
- Fixing `hex_loader.py`'s matching + the inaccurate "matches by UPC" note in CLAUDE.md.
- Hand-setting the one real prod gradient (`Ocean to Meadow`) — independent of this phase.
- Appending the Polymaker color CSV rows (data task, James-owned).
