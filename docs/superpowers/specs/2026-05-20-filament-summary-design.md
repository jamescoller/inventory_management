# Filament Summary — Design Spec

**Date:** 2026-05-20  
**Status:** Approved  
**PRs:** Two sequential PRs — PR 1 (Filament Summary View), PR 2 (ColorFamily Admin Config)

---

## Context

The app has 172 active filament products across 38 material types and hundreds of individual inventory items. There is no view that lets you quickly answer "how many rolls of PETG HF Red do I have?" or "how much PETG have I used this month?" This spec covers two features that address that:

1. A new **Filament Summary** page with material cards and an aggregated detail table.
2. A **ColorFamily admin config** that centralises the hardcoded color family definitions currently scattered across `models.py` and `views.py`.

---

## PR 1 — Filament Summary View

### 1. Data Model Changes

#### `Material` model

| Change | Detail |
|--------|--------|
| Add `material_type` field | `CharField(max_length=50, blank=True, default="")` — stores the subtype/modifier, e.g. `"HF"`, `"CF"`, `"Basic"`, `"Matte"`, `"for ABS"`, `"95A HF"` |
| Repurpose `name` | Becomes the base polymer type only: `"PETG"`, `"PLA"`, `"ABS"`, `"TPU"`, `"PA6"`, `"ASA"`, `"PC"`, `"PAHT"`, `"PET"`, `"PPS"`, `"PVA"`, `"Support"` |
| Unique constraint | Drop `unique=True` from `name`; add `unique_together = [('name', 'material_type')]` |
| Data migration | Split existing compound names (e.g. `"PETG HF"` → `name="PETG"`, `material_type="HF"`). First pass done automatically; edge cases (e.g. `"Support for ABS"`, `"TPU 95A HF"`) reviewed and corrected by James via the bulk admin. |

**First-pass split rules (applied in data migration):**
- `"X Y"` where X is a known base type → `name=X`, `material_type=Y` (e.g. `"PETG HF"`, `"PLA Matte"`, `"PC FR"`)
- `"X-Y"` patterns → `name=X`, `material_type=Y` (e.g. `"ABS-GF"`, `"PLA-CF"`, `"PA6-CF"`)
- Single-word names with no modifier → `name=word`, `material_type=""` (e.g. `"ABS"`, `"PVA"`, `"PC"`)
- `"Support for X"` → `name="Support"`, `material_type="for X"`
- `"TPU 95A HF"` → `name="TPU"`, `material_type="95A HF"`
- `"PA6-GF"` → `name="PA6"`, `material_type="GF"`
- `"PAHT-CF"` → `name="PAHT"`, `material_type="CF"`
- `"ASA Aero"` → `name="ASA"`, `material_type="Aero"`

#### `MaterialAdmin` bulk edit

Add `list_editable = ['name', 'material_type']` to `MaterialAdmin` so James can review and correct the data migration output in one admin table screen.

---

### 2. New View: `FilamentSummaryView`

**URL:** `/filament-summary/`  
**View class:** `FilamentSummaryView(LoginRequiredMixin, TemplateView)`  
**Template:** `inventory/filament_summary.html`  
**Nav:** Add link to main navigation bar

#### Queries (two, on every GET)

**Query 1 — active inventory, aggregated:**
```
InventoryItem
  .filter(status__in=_ACTIVE_STATUSES)
  .filter(product__polymorphic_ctype__model='filament')
  .values(
      'product__filament__material__name',        # base material
      'product__filament__material__material_type', # subtype
      'product__filament__color',
      'product__filament__color_family',
      'product__filament__hex_code',
      'product__filament__weight',
  )
  .annotate(on_hand=Count('id'))
```

**Query 2 — depleted items, last 365 days, aggregated:**
```
InventoryItem
  .filter(status=DEPLETED, date_depleted__gte=now()-365d)
  .filter(product__polymorphic_ctype__model='filament')
  .values(same grouping fields)
  .annotate(depleted_count=Count('id'))
```

Slicing to 7d and 30d windows happens in Python by comparing `date_depleted` against cutoffs — avoids two extra queries.

> **Implementation note:** The deep `product__filament__material__name` traversal through a polymorphic FK may not work cleanly in a `.values()` call. If so, use `Filament.objects` as the base queryset and annotate counts from `inventory_items` (same pattern as `FilamentColorGuideView`), then join the depleted query by matching on `(material_name, material_type, color)` in Python.

#### Context built in view

- `cards` — list of dicts, one per distinct `material.name`, each containing:
  - `name`: base material name
  - `total_on_hand`: sum of active rolls
  - `subtype_count`: distinct `material_type` values
  - `family_swatches`: list of `{family, hex, count}` dicts, sorted by `count` descending, using `COLOR_FAMILY_HEX` for the display hex
- `rows` — aggregated table rows, one per `(material_name, material_type, color)`, each containing:
  - `material_name`, `material_type`, `color`, `color_family`, `hex_code`
  - `on_hand` (active count)
  - `used_7d`, `used_30d`, `used_365d` (depleted counts from query 2)
  - `est_weight_kg` (sum of `on_hand × filament.weight`, approximated since `percent_remaining` may not be accurate yet)
- `grand_total_rolls`, `total_filament_types`, `total_materials` — header stats

#### Template structure

```
filament_summary.html
  extends base.html

  <!-- Header bar: grand_total_rolls / total_filament_types / total_materials -->

  <!-- Card grid (auto-fill, minmax ~145px) -->
  <!-- One card per material.name -->
  <!--   mat-name, mat-count, subtype/family subtitle -->
  <!--   Family swatches: sorted by count desc -->
  <!--     First 8 visible; rest hidden, revealed by "expand" button -->
  <!--     "+N more" button expands card in place; "show less" collapses -->
  <!--     Hover tooltip: "BLUE — 31 rolls" -->
  <!--     Click card → set ?material= filter -->
  <!--     Click swatch → set ?material= + ?color_family= filter -->

  <!-- Filter chip bar -->
  <!--   Active filter chips with ✕ to clear -->
  <!--   Period toggle: 7d / 30d / 1y (switches usage column, no reload) -->
  <!--   Row count label -->

  <!-- DataTables table -->
  <!--   Columns: Material | Subtype | Color (hex dot + name) | Family | On Hand | Used (period) | Est. Weight (kg) -->
  <!--   One row per (material_name, material_type, color) -->
  <!--   All rows rendered server-side; JS data-attributes drive show/hide -->
  <!--   Zero usage shown as "—" not "0" -->
  <!--   DataTables: ordering=true, searching=false, paging=false (all rows visible, JS-filtered) -->
```

#### Client-side filtering (pure JS, no HTMX)

All 172 rows rendered into the DOM with `data-material` and `data-family` attributes. Clicking a card or swatch sets JS variables and shows/hides rows via `display` toggle. Instant — no network round-trip needed at this scale.

Active filter state reflected in the filter chip bar and card `active` CSS class.

Period toggle (7d/30d/1y) swaps which `data-used-Xd` attribute is displayed in the usage column.

---

## PR 2 — ColorFamily Admin Config

### Motivation

`COLOR_FAMILIES` (choices list) is hardcoded in `models.py`. `COLOR_FAMILY_HEX` (display hex dict) is hardcoded in `views.py`. `FAMILY_ORDER` is hardcoded in `views.py`. The Filament admin (`/admin/inventory/filament`) uses the choices for list filtering. The filament color guide page and dashboard charts use `COLOR_FAMILY_HEX`. All of these need to stay in sync when a family is added, renamed, or recolored.

### New Model: `ColorFamily`

```python
class ColorFamily(models.Model):
    name         = models.CharField(max_length=20, unique=True)   # key, e.g. "BLACK"
    display_name = models.CharField(max_length=50)                # e.g. "Black"
    hex_code     = models.CharField(max_length=7)                 # e.g. "#000000"
    order        = models.PositiveSmallIntegerField(default=0)    # display order

    class Meta:
        ordering = ['order', 'name']
        verbose_name = "Color Family"
        verbose_name_plural = "Color Families"
```

### Seed migration

Populate all 12 existing families using current values. Notable overrides from current hardcoded values:
- `BLACK`: `#000000` (currently `#2c3e50` in `COLOR_FAMILY_HEX` — user confirmed it should be true black)

### Admin

`ColorFamilyAdmin` with `list_editable = ['display_name', 'hex_code', 'order']` — edit all families in one screen.

### Replacing hardcoded references

| Location | Current | Replacement |
|----------|---------|-------------|
| `models.py` `Filament.COLOR_FAMILIES` | hardcoded list | `ColorFamily.objects.values_list('name', 'display_name')` |
| `models.py` `Filament.color_family choices=` | `choices=COLOR_FAMILIES` | remove choices constraint (validate in `clean()` against DB if needed) |
| `views.py` `COLOR_FAMILY_HEX` | hardcoded dict | `{cf.name: cf.hex_code for cf in ColorFamily.objects.all()}` |
| `views.py` `FAMILY_ORDER` | hardcoded list | `list(ColorFamily.objects.values_list('name', flat=True))` |
| `admin.py` `FilamentAdmin` list_filter / display | `color_family` choices | dynamic from `ColorFamily.objects.all()` |
| `filament_color_guide.html` | uses `FAMILY_ORDER` from context | same, sourced from DB |
| `dashboard.html` | uses `color_chart_data.colors` | same, sourced from DB |
| `filament_summary.html` (PR 1) | uses `COLOR_FAMILY_HEX` | same, sourced from DB |

### Caching consideration

`ColorFamily` is read on almost every page load and changes rarely. Wrap the DB lookup in `django.core.cache` with a short TTL (5 min) or invalidate on `ColorFamily.save()` via a signal. This avoids repeated queries for a table that almost never changes.

---

## Out of Scope for Both PRs

- Weight-based usage tracking (percent_remaining is unreliable; roll count is primary)
- Filament usage logging / events
- BambuLab API integration
- Any changes to `InventoryItem` status filtering logic
