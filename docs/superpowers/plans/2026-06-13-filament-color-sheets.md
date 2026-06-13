# Phase 17.4 — Color Reference Sheets + Bambu Store Link — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a manufacturer-aware `FilamentColor` catalog seeded from `docs/filament-colors.csv`, render printable per-material color-reference sheets (owned colors flagged), and add a slug-or-search "View in Store" link.

**Architecture:** New `FilamentColor` model (decoupled from `Material` via a nullable FK) is the catalog. A human-gated `seed_filament_colors` command loads the CSV. Two `LoginRequiredMixin` template views render an index + per-`(manufacturer, material, subtype)` print sheet; owned colors come from an exact-key SQL join against in-stock `Filament` spools. A dependency-free `store_links` helper resolves the store URL.

**Tech Stack:** Django 6.0, SQLite, Bootstrap 5, django-unfold (admin), Django `TestCase`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-06-13-filament-color-sheets-design.md`

**Conventions:**
- Run Python via `~/.venvs/inventory/bin/python`.
- Tests live in `inventory/tests.py`; run a class with
  `~/.venvs/inventory/bin/python manage.py test inventory.tests.<ClassName> -v 2`.
- Validate after Python edits: `~/.venvs/inventory/bin/python manage.py check`.
- Commit per task. Branch is already `feat/filament-color-sheets`.

---

### Task 1: `FilamentColor` model + `Material.store_slug` + migration

**Files:**
- Modify: `inventory/models.py` (add `store_slug` to `Material` ~line 1015; add `FilamentColor` after `Material`, ~line 1046)
- Create (generated): `inventory/migrations/0039_filamentcolor_material_store_slug.py`
- Test: `inventory/tests.py` (append `FilamentColorModelTests`)

- [ ] **Step 1: Add `store_slug` to `Material`**

In `inventory/models.py`, inside `class Material`, after the `description` field (~line 1015):

```python
    store_slug = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text="Manufacturer store product slug (Bambu), e.g. 'pla-matte'. "
        "Blank falls back to a store search link.",
    )
```

- [ ] **Step 2: Add the `FilamentColor` model**

In `inventory/models.py`, immediately after the `Material` class (before `class AuditSession`, ~line 1047):

```python
class FilamentColor(models.Model):
    """Catalog of manufacturer filament colors (a reference palette), independent
    of which spools are owned. Seeded from ``docs/filament-colors.csv`` via the
    ``seed_filament_colors`` command. Decoupled from :class:`Material` (nullable
    FK) so a color is never dropped for lack of a Material row (e.g. PLA Gradient).
    """

    manufacturer = models.CharField(
        max_length=100,
        default="Bambu Lab",
        help_text="Brand of this color (e.g. Bambu Lab, Polymaker)",
    )
    material_name = models.CharField(
        max_length=100, help_text="Base polymer, e.g. 'PLA'"
    )
    material_type = models.CharField(
        max_length=50, blank=True, default="", help_text="Subtype, e.g. 'Matte'"
    )
    color_name = models.CharField(max_length=80)
    hex_code = models.CharField(max_length=9, help_text="#RRGGBB; gradient start")
    hex_code_2 = models.CharField(
        max_length=9, blank=True, default="", help_text="Set => gradient end color"
    )
    material = models.ForeignKey(
        "Material",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="catalog_colors",
        help_text="Resolved spec row; supplies header specs + store_slug.",
    )
    source = models.CharField(max_length=120, blank=True, default="")

    class Meta:
        unique_together = [
            ("manufacturer", "material_name", "material_type", "color_name")
        ]
        ordering = ["manufacturer", "material_name", "material_type", "color_name"]

    def __str__(self):
        sub = f" {self.material_type}" if self.material_type else ""
        return f"{self.manufacturer} {self.material_name}{sub} — {self.color_name}"

    @property
    def is_gradient(self):
        return bool(self.hex_code_2)

    @property
    def swatch_css(self):
        """CSS ``background`` value for the swatch (solid or linear-gradient)."""
        if self.is_gradient:
            return f"linear-gradient(135deg, {self.hex_code}, {self.hex_code_2})"
        return self.hex_code

    def clean(self):
        if self.hex_code:
            normalized = Filament._norm_hex(self.hex_code)
            if normalized is None:
                raise ValidationError(
                    {"hex_code": "Invalid hex color code. Use 3 or 6 hex digits."}
                )
            self.hex_code = normalized
        if self.hex_code_2:
            normalized = Filament._norm_hex(self.hex_code_2)
            if normalized is None:
                raise ValidationError(
                    {"hex_code_2": "Invalid hex color code. Use 3 or 6 hex digits."}
                )
            self.hex_code_2 = normalized

    def save(self, *args, **kwargs):
        if self.hex_code:
            self.hex_code = Filament._norm_hex(self.hex_code) or self.hex_code
        if self.hex_code_2:
            self.hex_code_2 = Filament._norm_hex(self.hex_code_2) or self.hex_code_2
        super().save(*args, **kwargs)
```

(`ValidationError` and `re` are already imported in `models.py`; `Filament` is defined above `Material`.)

- [ ] **Step 3: Generate the migration**

Run: `~/.venvs/inventory/bin/python manage.py makemigrations inventory`
Expected: creates `inventory/migrations/0039_*.py` adding `FilamentColor` and `Material.store_slug`. No prompts (all additive with defaults).

- [ ] **Step 4: Write the failing test**

Append to `inventory/tests.py`:

```python
class FilamentColorModelTests(TestCase):
    def test_str_and_gradient_swatch(self):
        from inventory.models import FilamentColor

        solid = FilamentColor.objects.create(
            material_name="PLA", material_type="Matte",
            color_name="Latte", hex_code="#E8D9C0",
        )
        self.assertIn("PLA Matte", str(solid))
        self.assertFalse(solid.is_gradient)
        self.assertEqual(solid.swatch_css, "#E8D9C0")

        grad = FilamentColor.objects.create(
            material_name="PLA", material_type="Gradient",
            color_name="Ocean to Meadow", hex_code="#307FE2", hex_code_2="#54FF9B",
        )
        self.assertTrue(grad.is_gradient)
        self.assertIn("linear-gradient", grad.swatch_css)

    def test_save_normalizes_hex(self):
        from inventory.models import FilamentColor

        c = FilamentColor.objects.create(
            material_name="ABS", color_name="Black", hex_code="000000",
        )
        c.refresh_from_db()
        self.assertEqual(c.hex_code, "#000000")

    def test_clean_rejects_bad_hex(self):
        from django.core.exceptions import ValidationError as VE

        from inventory.models import FilamentColor

        c = FilamentColor(material_name="PLA", color_name="X", hex_code="nothex")
        with self.assertRaises(VE):
            c.clean()

    def test_default_manufacturer_is_bambu(self):
        from inventory.models import FilamentColor

        c = FilamentColor.objects.create(material_name="PLA", color_name="Y", hex_code="#fff")
        self.assertEqual(c.manufacturer, "Bambu Lab")
```

- [ ] **Step 5: Run the migration + tests**

Run: `~/.venvs/inventory/bin/python manage.py migrate inventory && ~/.venvs/inventory/bin/python manage.py test inventory.tests.FilamentColorModelTests -v 2`
Expected: migration applies; 4 tests PASS.

- [ ] **Step 6: Validate + commit**

```bash
~/.venvs/inventory/bin/python manage.py check
git add inventory/models.py inventory/migrations/0039_*.py inventory/tests.py
git commit -m "feat: add FilamentColor catalog model + Material.store_slug"
```

---

### Task 2: Register `FilamentColor` in the admin

**Files:**
- Modify: `inventory/admin.py` (import `FilamentColor` in the `from .models import (...)` block; add `FilamentColorAdmin`)
- Test: `inventory/tests.py` (append `FilamentColorAdminTests`)

- [ ] **Step 1: Add the admin class**

In `inventory/admin.py`, add `FilamentColor` to the `from .models import (...)` tuple, then append:

```python
@admin.register(FilamentColor)
class FilamentColorAdmin(UnfoldModelAdmin):
    list_display = (
        "swatch",
        "manufacturer",
        "material_name",
        "material_type",
        "color_name",
        "hex_code",
        "hex_code_2",
        "source",
    )
    list_filter = ("manufacturer", "material_name", "material_type")
    search_fields = ("color_name", "material_name", "material_type")
    list_select_related = ("material",)
    autocomplete_fields = ("material",)

    @admin.display(description="Swatch")
    def swatch(self, obj):
        return format_html(
            '<span style="display:inline-block;width:22px;height:22px;'
            'border:1px solid #999;border-radius:4px;background:{};"></span>',
            obj.swatch_css,
        )
```

(`format_html` is already imported in `admin.py`.) `autocomplete_fields = ("material",)` requires `search_fields` on `MaterialAdmin`; if `MaterialAdmin` has none, add `search_fields = ("name", "material_type")` to it.

- [ ] **Step 2: Write the failing test**

Append to `inventory/tests.py`:

```python
class FilamentColorAdminTests(TestCase):
    def setUp(self):
        self.client = Client()
        User.objects.create_superuser("admin1", "a@b.com", "pass")
        self.client.login(username="admin1", password="pass")

    def test_changelist_loads(self):
        from inventory.models import FilamentColor

        FilamentColor.objects.create(
            material_name="PLA", material_type="Matte",
            color_name="Latte", hex_code="#E8D9C0",
        )
        resp = self.client.get("/admin/inventory/filamentcolor/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Latte")
```

(`User` is imported at the top of `tests.py`; if not, add `from django.contrib.auth.models import User`.)

- [ ] **Step 3: Run the test**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.FilamentColorAdminTests -v 2`
Expected: PASS.

- [ ] **Step 4: Validate + commit**

```bash
~/.venvs/inventory/bin/python manage.py check
git add inventory/admin.py inventory/tests.py
git commit -m "feat: register FilamentColor in admin (editable catalog)"
```

---

### Task 3: Seed loader + `seed_filament_colors` command

**Files:**
- Create: `inventory/color_catalog.py` (loader logic + `group_slug`)
- Create: `inventory/management/commands/seed_filament_colors.py`
- Test: `inventory/tests.py` (append `SeedFilamentColorsTests`)

- [ ] **Step 1: Write `color_catalog.py`**

```python
"""Seed the :class:`FilamentColor` catalog from ``docs/filament-colors.csv``.

Idempotent ``get_or_create`` keyed on
``(manufacturer, material_name, material_type, color_name)``. The CSV has no
``manufacturer`` column today (all Bambu); a missing/blank value defaults to
``Bambu Lab``. Human-gated: run ``seed_filament_colors`` on prod after review.
"""

import csv

from django.utils.text import slugify

from inventory.models import FilamentColor, Material


def group_slug(manufacturer, material_name, material_type):
    """Stable URL slug for a sheet group, e.g. 'bambu-lab-pla-matte'."""
    return slugify(f"{manufacturer} {material_name} {material_type}")


def _resolve_material(material_name, material_type):
    return (
        Material.objects.filter(
            name__iexact=material_name, material_type__iexact=material_type
        ).first()
    )


def seed_filament_colors(csv_path, *, default_manufacturer="Bambu Lab"):
    stats = {"created": 0, "updated": 0, "unchanged": 0, "no_material": []}
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            material_name = (row.get("material") or "").strip()
            material_type = (row.get("material_type") or "").strip()
            color_name = (row.get("color_name") or "").strip()
            hex_code = (row.get("hex_code") or "").strip()
            if not material_name or not color_name or not hex_code:
                continue
            manufacturer = (row.get("manufacturer") or "").strip() or default_manufacturer
            hex2 = (row.get("hex_code_2") or "").strip()
            source = (row.get("source_file") or row.get("notes") or "").strip()
            material = _resolve_material(material_name, material_type)
            if material is None:
                stats["no_material"].append(
                    f"{manufacturer} {material_name} {material_type} {color_name}".strip()
                )

            obj, created = FilamentColor.objects.get_or_create(
                manufacturer=manufacturer,
                material_name=material_name,
                material_type=material_type,
                color_name=color_name,
                defaults={
                    "hex_code": hex_code,
                    "hex_code_2": hex2,
                    "material": material,
                    "source": source,
                },
            )
            if created:
                stats["created"] += 1
                continue
            changed = False
            for field, value in (
                ("hex_code", hex_code),
                ("hex_code_2", hex2),
                ("material", material),
                ("source", source),
            ):
                if getattr(obj, field) != value:
                    setattr(obj, field, value)
                    changed = True
            if changed:
                obj.save()
                stats["updated"] += 1
            else:
                stats["unchanged"] += 1
    return stats
```

- [ ] **Step 2: Write the management command**

`inventory/management/commands/seed_filament_colors.py`:

```python
"""Seed the FilamentColor catalog from docs/filament-colors.csv (human-gated)."""

import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from inventory.color_catalog import seed_filament_colors

DEFAULT_CSV = "docs/filament-colors.csv"


class Command(BaseCommand):
    help = "Seed/refresh the FilamentColor catalog from the color CSV (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--csv", default=None, help=f"CSV path (default {DEFAULT_CSV}).")
        parser.add_argument(
            "--manufacturer",
            default="Bambu Lab",
            help="Default brand when the CSV row has no manufacturer column.",
        )

    def handle(self, *args, **options):
        path = options["csv"] or os.path.join(str(settings.BASE_DIR), DEFAULT_CSV)
        if not os.path.isfile(path):
            raise CommandError(f"CSV not found: {path}")
        stats = seed_filament_colors(path, default_manufacturer=options["manufacturer"])
        self.stdout.write(
            self.style.SUCCESS(
                f"created={stats['created']} updated={stats['updated']} "
                f"unchanged={stats['unchanged']} no_material={len(stats['no_material'])}"
            )
        )
        for name in stats["no_material"]:
            self.stdout.write(f"  no Material row: {name}")
```

- [ ] **Step 3: Write the failing test**

Append to `inventory/tests.py`:

```python
class SeedFilamentColorsTests(TestCase):
    def _write_csv(self, rows, header=None):
        import tempfile

        header = header or "material,material_type,color_name,hex_code,hex_code_2,notes,source_file"
        fd, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(header + "\n")
            for r in rows:
                fh.write(r + "\n")
        return path

    def test_seed_is_idempotent_and_defaults_manufacturer(self):
        from inventory.color_catalog import seed_filament_colors
        from inventory.models import FilamentColor

        path = self._write_csv(["PLA,Matte,Latte,#E8D9C0,,,Bambu_PLA_Matte.pdf"])
        s1 = seed_filament_colors(path)
        self.assertEqual(s1["created"], 1)
        c = FilamentColor.objects.get(color_name="Latte")
        self.assertEqual(c.manufacturer, "Bambu Lab")
        s2 = seed_filament_colors(path)
        self.assertEqual((s2["created"], s2["unchanged"]), (0, 1))

    def test_resolves_material_fk_and_reports_missing(self):
        from inventory.color_catalog import seed_filament_colors
        from inventory.models import FilamentColor, Material

        Material.objects.create(name="PLA", material_type="Matte")
        path = self._write_csv(
            [
                "PLA,Matte,Latte,#E8D9C0,,,x.pdf",
                "PLA,Gradient,Ocean to Meadow,#307FE2,#54FF9B,,x.pdf",
            ]
        )
        stats = seed_filament_colors(path)
        latte = FilamentColor.objects.get(color_name="Latte")
        self.assertIsNotNone(latte.material)
        grad = FilamentColor.objects.get(color_name="Ocean to Meadow")
        self.assertIsNone(grad.material)
        self.assertTrue(grad.is_gradient)
        self.assertEqual(len(stats["no_material"]), 1)

    def test_explicit_manufacturer_column(self):
        from inventory.color_catalog import seed_filament_colors
        from inventory.models import FilamentColor

        path = self._write_csv(
            ["Polymaker,PolyTerra,Army Green,#5C6B47,,,p.pdf"],
            header="manufacturer,material,material_type,color_name,hex_code,hex_code_2,notes,source_file",
        )
        seed_filament_colors(path)
        self.assertTrue(
            FilamentColor.objects.filter(manufacturer="Polymaker", color_name="Army Green").exists()
        )
```

(`os` is imported at the top of `tests.py`; if not, add `import os`.)

- [ ] **Step 4: Run the tests**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.SeedFilamentColorsTests -v 2`
Expected: 3 tests PASS.

- [ ] **Step 5: Smoke-run against the real CSV**

Run: `~/.venvs/inventory/bin/python manage.py seed_filament_colors`
Expected: `created=227 updated=0 unchanged=0 no_material=<N>` (N = colors whose material has no local `Material` row in dev; fine). Re-run → `created=0 ... unchanged=227`.

- [ ] **Step 6: Validate + commit**

```bash
~/.venvs/inventory/bin/python manage.py check
git add inventory/color_catalog.py inventory/management/commands/seed_filament_colors.py inventory/tests.py
git commit -m "feat: seed_filament_colors command + idempotent catalog loader"
```

---

### Task 4: `store_links` helper

**Files:**
- Create: `inventory/store_links.py`
- Test: `inventory/tests.py` (append `StoreLinksTests`)

- [ ] **Step 1: Write `store_links.py`**

```python
"""Resolve a 'View in Store' URL for a filament color/material.

Per-manufacturer store config (base + URL templates). A material's product-page
slug lives on ``Material.store_slug`` and is used only when the sheet's
manufacturer matches ``Material.mfr``; otherwise we fall back to the brand's
search URL. Unknown brand => ``None`` (caller hides the button).
"""

from urllib.parse import quote_plus

STORE_CONFIG = {
    "Bambu Lab": {
        "base": "https://us.store.bambulab.com",
        "product": "/products/{slug}",
        "search": "/search?q={query}",
    },
    "Polymaker": {
        "base": "https://us.polymaker.com",
        "search": "/search?q={query}",
    },
}


def store_url(*, manufacturer, material=None, query=""):
    cfg = STORE_CONFIG.get(manufacturer)
    if cfg is None:
        return None
    slug = getattr(material, "store_slug", "") if material is not None else ""
    mfr_match = material is not None and material.mfr == manufacturer
    if slug and mfr_match and "product" in cfg:
        return cfg["base"] + cfg["product"].format(slug=slug)
    if "search" in cfg:
        return cfg["base"] + cfg["search"].format(query=quote_plus(query))
    return cfg["base"]
```

- [ ] **Step 2: Write the failing test**

Append to `inventory/tests.py`:

```python
class StoreLinksTests(TestCase):
    def test_bambu_product_page_when_slug_and_mfr_match(self):
        from inventory.models import Material
        from inventory.store_links import store_url

        m = Material.objects.create(
            name="PLA", material_type="Matte", mfr="Bambu Lab", store_slug="pla-matte"
        )
        url = store_url(manufacturer="Bambu Lab", material=m, query="PLA Matte Latte")
        self.assertEqual(url, "https://us.store.bambulab.com/products/pla-matte")

    def test_bambu_search_when_no_slug(self):
        from inventory.store_links import store_url

        url = store_url(manufacturer="Bambu Lab", material=None, query="PLA Matte Latte")
        self.assertIn("/search?q=PLA+Matte+Latte", url)

    def test_polymaker_always_search(self):
        from inventory.store_links import store_url

        url = store_url(manufacturer="Polymaker", material=None, query="PolyTerra")
        self.assertTrue(url.startswith("https://us.polymaker.com/search?q="))

    def test_unknown_brand_returns_none(self):
        from inventory.store_links import store_url

        self.assertIsNone(store_url(manufacturer="Hatchbox", query="x"))
```

- [ ] **Step 3: Run the tests**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.StoreLinksTests -v 2`
Expected: 4 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add inventory/store_links.py inventory/tests.py
git commit -m "feat: store_links helper (slug-or-search, per manufacturer)"
```

---

### Task 5: Index + sheet views + URLs (owned-✓ join)

**Files:**
- Modify: `inventory/views.py` (add two views near the other filament views, ~line 1198; ensure imports for `FilamentColor`, `InventoryItem`, `Count`, `store_url`, `group_slug`)
- Modify: `inventory/urls.py` (import the two views; add two `path`s near `filament_summary`, ~line 131)
- Test: `inventory/tests.py` (append `ColorSheetViewTests`)

- [ ] **Step 1: Add the views**

In `inventory/views.py`, near the top ensure these imports exist (add what's missing):

```python
from django.db.models import Count

from .color_catalog import group_slug
from .models import FilamentColor
from .store_links import store_url
```

Then add after `FilamentGuideView` (~line 1198):

```python
_TERMINAL_STATUSES = (
    InventoryItem.Status.DEPLETED,
    InventoryItem.Status.SOLD,
    InventoryItem.Status.UNKNOWN,
)


def _owned_color_counts(manufacturer, material_name, material_type):
    """Map of lowercased owned color name -> in-stock roll count for a group."""
    rows = (
        InventoryItem.objects.filter(
            product__filament__manufacturer__iexact=manufacturer,
            product__filament__material__name__iexact=material_name,
            product__filament__material__material_type__iexact=material_type,
        )
        .exclude(status__in=_TERMINAL_STATUSES)
        .values("product__filament__color")
        .annotate(n=Count("id"))
    )
    return {
        (r["product__filament__color"] or "").lower(): r["n"]
        for r in rows
        if r["product__filament__color"]
    }


class FilamentColorSheetIndexView(LoginRequiredMixin, TemplateView):
    template_name = "inventory/filament_color_sheets.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        groups = (
            FilamentColor.objects.values(
                "manufacturer", "material_name", "material_type"
            )
            .annotate(n_colors=Count("id"))
            .order_by("manufacturer", "material_name", "material_type")
        )
        cards = []
        for g in groups:
            owned = _owned_color_counts(
                g["manufacturer"], g["material_name"], g["material_type"]
            )
            cards.append(
                {
                    "manufacturer": g["manufacturer"],
                    "material_name": g["material_name"],
                    "material_type": g["material_type"],
                    "n_colors": g["n_colors"],
                    "n_owned": len(owned),
                    "slug": group_slug(
                        g["manufacturer"], g["material_name"], g["material_type"]
                    ),
                }
            )
        ctx["cards"] = cards
        ctx["active"] = "sheets"
        return ctx


class FilamentColorSheetView(LoginRequiredMixin, TemplateView):
    template_name = "inventory/filament_color_sheet.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        slug = kwargs["slug"]
        groups = FilamentColor.objects.values(
            "manufacturer", "material_name", "material_type"
        ).distinct()
        match = next(
            (
                g
                for g in groups
                if group_slug(
                    g["manufacturer"], g["material_name"], g["material_type"]
                )
                == slug
            ),
            None,
        )
        if match is None:
            raise Http404("No such color sheet")

        colors = list(
            FilamentColor.objects.filter(
                manufacturer=match["manufacturer"],
                material_name=match["material_name"],
                material_type=match["material_type"],
            ).order_by("color_name")
        )
        owned = _owned_color_counts(
            match["manufacturer"], match["material_name"], match["material_type"]
        )
        for c in colors:
            c.owned_count = owned.get(c.color_name.lower(), 0)

        material = (
            colors[0].material
            if colors and colors[0].material_id
            else Material.objects.filter(
                name__iexact=match["material_name"],
                material_type__iexact=match["material_type"],
            ).first()
        )
        query = f"{match['material_name']} {match['material_type']}".strip()
        ctx.update(
            {
                "manufacturer": match["manufacturer"],
                "material_name": match["material_name"],
                "material_type": match["material_type"],
                "colors": colors,
                "material": material,
                "n_owned": sum(1 for c in colors if c.owned_count),
                "store_link": store_url(
                    manufacturer=match["manufacturer"], material=material, query=query
                ),
                "active": "sheets",
            }
        )
        return ctx
```

Ensure `Http404` and `Material` are imported in `views.py` (add `from django.http import Http404` and `Material` to the models import if missing).

- [ ] **Step 2: Wire the URLs**

In `inventory/urls.py`, add the two views to the `from .views import (...)` block, then after the `filament_summary` path (~line 131):

```python
    path(
        "filament/color-sheets/",
        FilamentColorSheetIndexView.as_view(),
        name="filament_color_sheets",
    ),
    path(
        "filament/color-sheets/<slug:slug>/",
        FilamentColorSheetView.as_view(),
        name="filament_color_sheet",
    ),
```

- [ ] **Step 3: Write the failing test**

Append to `inventory/tests.py`:

```python
class ColorSheetViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        User.objects.create_user("sheetuser", "s@b.com", "pass")
        self.client.login(username="sheetuser", password="pass")
        from inventory.models import FilamentColor, Material

        self.mat = Material.objects.create(name="PLA", material_type="Matte", mfr="Bambu Lab")
        FilamentColor.objects.create(
            material_name="PLA", material_type="Matte", color_name="Latte",
            hex_code="#E8D9C0", material=self.mat,
        )
        FilamentColor.objects.create(
            material_name="PLA", material_type="Matte", color_name="Ash",
            hex_code="#9A9A9A", material=self.mat,
        )

    def test_index_lists_group_with_counts(self):
        resp = self.client.get(reverse("filament_color_sheets"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "PLA")
        self.assertContains(resp, "bambu-lab-pla-matte")

    def test_sheet_renders_owned_marker(self):
        from inventory.models import Filament, InventoryItem, Location

        loc = Location.objects.create(name="shelf-a")
        fil = Filament.objects.create(
            name="PLA Matte Latte", upc="0000000000099", material=self.mat,
            color="Latte", hex_code="#E8D9C0", manufacturer="Bambu Lab",
        )
        InventoryItem.objects.create(product=fil, location=loc, status=4)  # STORED
        resp = self.client.get(
            reverse("filament_color_sheet", kwargs={"slug": "bambu-lab-pla-matte"})
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Latte")
        self.assertContains(resp, "Ash")
        self.assertEqual(resp.context["n_owned"], 1)

    def test_depleted_spool_not_counted_owned(self):
        from inventory.models import Filament, InventoryItem, Location

        loc = Location.objects.create(name="shelf-b")
        fil = Filament.objects.create(
            name="PLA Matte Ash", upc="0000000000098", material=self.mat,
            color="Ash", hex_code="#9A9A9A", manufacturer="Bambu Lab",
        )
        InventoryItem.objects.create(product=fil, location=loc, status=5)  # DEPLETED
        resp = self.client.get(
            reverse("filament_color_sheet", kwargs={"slug": "bambu-lab-pla-matte"})
        )
        self.assertEqual(resp.context["n_owned"], 0)

    def test_unknown_slug_404(self):
        resp = self.client.get(
            reverse("filament_color_sheet", kwargs={"slug": "nope-nope"})
        )
        self.assertEqual(resp.status_code, 404)
```

Note: the templates don't exist yet, so the 200-expecting tests will fail at this step — that's expected; they pass after Task 6. The 404 + context-value assertions exercise the view logic now.

- [ ] **Step 4: Run the view-logic tests**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.ColorSheetViewTests.test_unknown_slug_404 -v 2`
Expected: PASS (no template needed for the 404 path).

- [ ] **Step 5: Validate + commit**

```bash
~/.venvs/inventory/bin/python manage.py check
git add inventory/views.py inventory/urls.py inventory/tests.py
git commit -m "feat: color-sheet index + detail views with owned-color join"
```

---

### Task 6: Templates + nav tab + color-guide store link

**Files:**
- Create: `inventory/templates/inventory/filament_color_sheets.html`
- Create: `inventory/templates/inventory/filament_color_sheet.html`
- Modify: `inventory/templates/inventory/filament_nav.html` (add a "Sheets" tab)
- Modify: `inventory/templates/inventory/filament_color_guide.html` (add a per-row store link — only if the row already exposes `manufacturer`/`material`/`color`; otherwise skip and note it)
- Test: rerun `ColorSheetViewTests` (now the 200/render assertions pass)

- [ ] **Step 1: Index template**

`inventory/templates/inventory/filament_color_sheets.html`:

```html
{% extends "inventory/base.html" %}
{% block content %}
  <div class="container my-4">
    {% include "inventory/filament_nav.html" with active="sheets" %}
    <h1 class="h4 mb-3">Color Reference Sheets</h1>
    <p class="text-muted">Printable per-material color cards. Owned colors are flagged.</p>
    <div class="row g-3">
      {% for card in cards %}
        <div class="col-12 col-sm-6 col-lg-4">
          <a class="text-decoration-none"
             href="{% url 'filament_color_sheet' slug=card.slug %}">
            <div class="card h-100 shadow-sm">
              <div class="card-body">
                <h2 class="h6 mb-1">{{ card.manufacturer }}</h2>
                <div class="fw-semibold">{{ card.material_name }} {{ card.material_type }}</div>
                <div class="small text-muted">
                  {{ card.n_colors }} colors · you own {{ card.n_owned }}
                </div>
              </div>
            </div>
          </a>
        </div>
      {% empty %}
        <p class="text-muted">No catalog colors seeded yet. Run
          <code>manage.py seed_filament_colors</code>.</p>
      {% endfor %}
    </div>
  </div>
{% endblock %}
```

- [ ] **Step 2: Sheet template**

`inventory/templates/inventory/filament_color_sheet.html`:

```html
{% extends "inventory/base.html" %}
{% block extra_head %}
  <style>
    .swatch-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(130px,1fr)); gap:.75rem; }
    .swatch-cell { border:1px solid #ddd; border-radius:8px; overflow:hidden; break-inside:avoid; }
    .swatch-cell.owned { border:3px double #198754; }
    .swatch-block { height:64px; }
    .swatch-meta { padding:.4rem .5rem; font-size:.8rem; }
    .swatch-hex { color:#666; font-variant-numeric:tabular-nums; }
    @media print {
      .no-print { display:none !important; }
      body { background:#fff; }
      a[href]::after { content:""; }
    }
  </style>
{% endblock %}
{% block content %}
  <div class="container my-4">
    <div class="no-print">{% include "inventory/filament_nav.html" with active="sheets" %}</div>
    <div class="d-flex justify-content-between align-items-start flex-wrap gap-2 mb-2">
      <div>
        <h1 class="h4 mb-0">{{ manufacturer }} · {{ material_name }} {{ material_type }}</h1>
        <div class="small text-muted">
          {{ colors|length }} colors · you own {{ n_owned }}
          {% if material and material.print_temp_ideal_degC %}
            · nozzle {{ material.print_temp_ideal_degC }}°C{% endif %}
        </div>
      </div>
      <div class="no-print d-flex gap-2">
        {% if store_link %}
          <a class="btn btn-outline-primary btn-sm" href="{{ store_link }}" target="_blank"
             rel="noopener">View in Store</a>
        {% endif %}
        <button class="btn btn-primary btn-sm" onclick="window.print()">Print sheet</button>
      </div>
    </div>
    <div class="swatch-grid">
      {% for c in colors %}
        <div class="swatch-cell{% if c.owned_count %} owned{% endif %}">
          <div class="swatch-block" style="background: {{ c.swatch_css }};"></div>
          <div class="swatch-meta">
            <div class="fw-semibold">
              {{ c.color_name }}{% if c.owned_count %} <span title="owned">✓</span>{% endif %}
            </div>
            <div class="swatch-hex">{{ c.hex_code }}{% if c.hex_code_2 %} → {{ c.hex_code_2 }}{% endif %}</div>
            {% if c.owned_count %}<div class="small text-success">{{ c.owned_count }} on hand</div>{% endif %}
          </div>
        </div>
      {% endfor %}
    </div>
  </div>
{% endblock %}
```

Note: confirm `base.html` defines an `extra_head` block; if the block is named differently (e.g. `extra_css`), use that name instead. Check with: `grep -n "block extra" inventory/templates/inventory/base.html`.

- [ ] **Step 3: Add the nav tab**

In `inventory/templates/inventory/filament_nav.html`, add a list item after the "Colors" `<li>`:

```html
    <li class="nav-item">
        <a class="nav-link{% if active == 'sheets' %} active{% endif %}"
           href="{% url 'filament_color_sheets' %}">
            <i class="bi bi-grid-1x2-fill" aria-hidden="true"></i> Sheets
        </a>
    </li>
```

- [ ] **Step 4: Color-guide store link (conditional)**

Run `grep -n "manufacturer\|store\|color_family\|hex_code" inventory/templates/inventory/filament_color_guide.html` to confirm each row exposes `manufacturer` and the material. If a row object with `.manufacturer` and `.material` is in scope, add a small link in the row's actions cell:

```html
{% load store_extras %}
... {% with surl=row.manufacturer|store_link:row %}{% if surl %}<a href="{{ surl }}" target="_blank" rel="noopener" class="small">Store</a>{% endif %}{% endwith %}
```

If the template instead renders aggregated rows without a single `manufacturer`/`material`, **skip this step** and note in the commit that the color-guide store link is deferred (the sheet's button already covers item #9's primary need). Do not invent fields. (A `store_extras` template tag wrapping `store_url` would be created only if this step proceeds; otherwise omit it.)

- [ ] **Step 5: Run the full view tests**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.ColorSheetViewTests -v 2`
Expected: all 5 tests PASS.

- [ ] **Step 6: Validate + commit**

```bash
~/.venvs/inventory/bin/python manage.py check
pre-commit run --files inventory/templates/inventory/filament_color_sheets.html inventory/templates/inventory/filament_color_sheet.html inventory/templates/inventory/filament_nav.html
git add inventory/templates/inventory/
git commit -m "feat: color-sheet templates + filament nav tab"
```

---

### Task 7: Docs + final validation

**Files:**
- Modify: `todo.md` (mark 17.4 items done)
- Modify: `readme.md` (add the sheets page to the feature/URL list if such a list exists)
- Modify: `CLAUDE.md` (add a 17.4 narrative note + the prod deploy step)

- [ ] **Step 1: Update `todo.md`**

Mark the 17.4 checkbox done and add a short "what was done" note mirroring the other phase entries (catalog model, seed command, sheets, store link; note the deferred color-guide link if skipped, and that `seed_filament_colors` is human-gated on prod).

- [ ] **Step 2: Update `CLAUDE.md`**

Add a Phase 17.4 bullet under the roadmap notes: new `FilamentColor` catalog (manufacturer-aware, migration `0039`), `seed_filament_colors` (human-gated, defaults brand to Bambu Lab, reads optional `manufacturer` CSV column), `Material.store_slug` for Bambu deep links + `store_links.py` search fallback, print sheets at `/filament/color-sheets/`. Note the prod step: `migrate` + `seed_filament_colors`, then fill Bambu `store_slug`s in admin.

- [ ] **Step 3: Run the full inventory test suite**

Run: `~/.venvs/inventory/bin/python manage.py test inventory -v 1`
Expected: all tests PASS (existing + the new classes).

- [ ] **Step 4: Final check + commit**

```bash
~/.venvs/inventory/bin/python manage.py check
git add todo.md readme.md CLAUDE.md
git commit -m "docs: record Phase 17.4 color sheets + store link"
```

- [ ] **Step 5: Push + open PR**

```bash
git push -u origin feat/filament-color-sheets
gh pr create --base master --title "feat: filament color reference sheets + Bambu Store link (Phase 17.4)" --body "<summary + the prod seed/deploy steps>"
```

---

## Deploy checklist (post-merge, James)

1. Auto-deploy runs migration `0039` (additive; nightly backup live).
2. `ssh inventory-manager 'docker exec inventory_management-web-1 python manage.py seed_filament_colors'` → seeds 227 catalog rows.
3. Optionally fill Bambu `Material.store_slug`s in the admin for precise product links.
4. Eyeball `/filament/color-sheets/` and one sheet; test "Print → Save as PDF".
