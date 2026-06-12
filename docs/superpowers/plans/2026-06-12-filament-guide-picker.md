# Filament Guide Picker + Data Load — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish Phase 17.2/17.3 — ship the filament selection-guide requirements picker, the supporting `Material`/`Filament` schema, and two human-gated data loaders.

**Architecture:** Additive schema on `Material` (tri-state drying, category, drop food_safe) and `Filament` (second hex for gradients). Two idempotent management-command loaders read committed CSVs. The picker is client-side JS over a `json_script` payload grouped by base polymer — no server round-trips, mirroring the dashboard-charts pattern.

**Tech Stack:** Django 6.0, SQLite/WAL, Bootstrap 5, DataTables, vanilla JS, `django-unfold` admin. Spec: `docs/superpowers/specs/2026-06-12-filament-guide-picker-and-data-design.md`.

**Branch:** `feat/filament-guide-picker` (already created; design artifacts + CSVs committed).

**Conventions & gotchas:**
- Python: `~/.venvs/inventory/bin/python`; settings module `inventory_management_site.settings` (auto-loaded by `manage.py`).
- Tests: `~/.venvs/inventory/bin/python manage.py test inventory.tests.<Class> -v2`
- Check: `~/.venvs/inventory/bin/python manage.py check`
- **A model change and its migration MUST land in the same commit** — the pre-commit "missing migrations" hook fails otherwise, and the test DB is built from migrations (new fields don't exist in tests until the migration is created). So each schema task = model edit + migration + tests in one commit.
- Migration numbers: **verify head first** — `ls inventory/migrations/ | sort | tail -3`. Plan assumes head is `0036`, so first new = `0037`.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `inventory/models.py` | `Material.Category`/`DryingNeed` enums + fields; `drying_required` property; drop `food_safe`; `Filament.hex_code_2` + gradient `color_family` |
| `inventory/migrations/0037_*.py` | Material: add category/drying_need, RunPython backfill, drop drying_required+food_safe |
| `inventory/migrations/0038_*.py` | Filament: add hex_code_2, alter color_family choices |
| `inventory/admin.py` | `MaterialAdmin`: category/drying_need in, food_safe out |
| `inventory/guide_data.py` | NEW — `load_guide_data(csv_path, *, overwrite)` service |
| `inventory/hex_loader.py` | NEW — `load_filament_hex(csv_path, *, overwrite)` service |
| `inventory/management/commands/load_guide_data.py` | NEW — command wrapper |
| `inventory/management/commands/load_filament_hex.py` | NEW — command wrapper |
| `inventory/views.py` | `FilamentGuideView` — grouped-by-base picker payload + picker options |
| `inventory/templates/inventory/filament_guide.html` | table (drop food_safe, category grouping, drying tri-state) + picker section |
| `inventory/static/inventory/js/filament_guide.js` | NEW — picker scoring + render |
| `inventory/tests.py` | tests for all of the above |

---

## Task 1: Material schema + migration — tri-state drying, category, drop food_safe

**Files:**
- Modify: `inventory/models.py` (`Material`, `models.py:965-981`)
- Create: `inventory/migrations/0037_material_guide_drying_category.py`
- Test: `inventory/tests.py`

- [ ] **Step 1: Write failing tests**

Add to `inventory/tests.py`:

```python
class MaterialGuideSchemaTests(TestCase):
    def test_drying_required_property_true_only_for_required(self):
        from inventory.models import Material
        m = Material.objects.create(name="PETG", material_type="Basic",
                                    drying_need=Material.DryingNeed.REQUIRED)
        self.assertTrue(m.drying_required)
        m.drying_need = Material.DryingNeed.RECOMMENDED
        self.assertFalse(m.drying_required)
        m.drying_need = Material.DryingNeed.NOT_NEEDED
        self.assertFalse(m.drying_required)

    def test_category_defaults_everyday(self):
        from inventory.models import Material
        m = Material.objects.create(name="PLA", material_type="Basic")
        self.assertEqual(m.category, Material.Category.EVERYDAY)

    def test_food_safe_field_removed(self):
        from inventory.models import Material
        field_names = {f.name for f in Material._meta.get_fields()}
        self.assertNotIn("food_safe", field_names)
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.MaterialGuideSchemaTests -v2`
Expected: FAIL (`Material has no attribute 'DryingNeed'`).

- [ ] **Step 3: Edit the model**

In `inventory/models.py`, inside `class Material`, add the enums at the top of the class body (above the field declarations):

```python
    class Category(models.TextChoices):
        EVERYDAY = "everyday", "Everyday"
        ENGINEERING = "engineering", "Engineering"
        FLEXIBLE = "flexible", "Flexible"
        SUPPORT = "support", "Support"

    class DryingNeed(models.TextChoices):
        NOT_NEEDED = "not_needed", "Not needed"
        RECOMMENDED = "recommended", "Recommended"
        REQUIRED = "required", "Required"
```

Replace the `drying_required` field (`models.py:965-967`) with the tri-state field + a property shim:

```python
    drying_need = models.CharField(
        max_length=12,
        choices=DryingNeed.choices,
        default=DryingNeed.REQUIRED,
        help_text="Whether drying is required, recommended, or not needed before printing.",
    )

    @property
    def drying_required(self):
        """Back-compat shim: the wet-filament safety check and admin read this.
        Only a REQUIRED need blocks moving a NEW spool into dry storage."""
        return self.drying_need == self.DryingNeed.REQUIRED
```

Add the `category` field near the guide-properties block:

```python
    category = models.CharField(
        max_length=12,
        choices=Category.choices,
        default=Category.EVERYDAY,
        help_text="Drives guide grouping; SUPPORT materials are excluded from the picker.",
    )
```

**Delete** the `food_safe` field line (`models.py:977`).

- [ ] **Step 4: Generate the migration**

Run: `~/.venvs/inventory/bin/python manage.py makemigrations inventory -n material_guide_drying_category`
Expected: a migration adding `category` + `drying_need`, removing `drying_required` + `food_safe`.

- [ ] **Step 5: Insert a RunPython backfill BEFORE the RemoveField ops**

Open the generated migration. Add above `class Migration`:

```python
CATEGORY_BY_BASE = {
    "PLA": "everyday", "PETG": "everyday", "ABS": "everyday", "ASA": "everyday",
    "PC": "engineering", "PA6": "engineering", "PAHT": "engineering",
    "PET": "engineering", "PPS": "engineering",
    "TPU": "flexible", "PVA": "support", "Support": "support",
}


def backfill(apps, schema_editor):
    Material = apps.get_model("inventory", "Material")
    for m in Material.objects.all():
        m.drying_need = "required" if m.drying_required else "not_needed"
        m.category = CATEGORY_BY_BASE.get(m.name, "everyday")
        m.save(update_fields=["drying_need", "category"])


def noop(apps, schema_editor):
    pass
```

In `operations`, place `migrations.RunPython(backfill, noop)` **after** the `AddField('drying_need')`/`AddField('category')` ops and **before** `RemoveField('drying_required')`. (The historical model still has `drying_required` as a real field there — RunPython reads it safely.)

- [ ] **Step 6: Apply + verify + run tests**

Run:
```bash
~/.venvs/inventory/bin/python manage.py makemigrations --check --dry-run
~/.venvs/inventory/bin/python manage.py migrate inventory
~/.venvs/inventory/bin/python manage.py test inventory.tests.MaterialGuideSchemaTests -v2
```
Expected: `--check` exits 0; migrate applies clean; tests PASS.

- [ ] **Step 7: Commit**

```bash
git add inventory/models.py inventory/migrations/0037_*.py inventory/tests.py
git commit -m "feat: Material drying tri-state + category, drop food_safe (migration 0037)"
```

---

## Task 2: Filament gradient + migration — second hex + Gradient color family

**Files:**
- Modify: `inventory/models.py` (`Filament`, `models.py:90-235`; `COLOR_FAMILIES` `models.py:146-159`)
- Create: `inventory/migrations/0038_filament_hex_code_2.py`
- Test: `inventory/tests.py`

- [ ] **Step 1: Write failing tests**

```python
class FilamentGradientTests(TestCase):
    def test_second_hex_sets_gradient_family(self):
        from inventory.models import Filament
        f = Filament.objects.create(color="Ocean to Meadow",
                                    hex_code="#307FE2", hex_code_2="#54FF9B")
        self.assertEqual(f.color_family, "GRADIENT")

    def test_single_hex_unchanged(self):
        from inventory.models import Filament
        f = Filament.objects.create(color="Blue", hex_code="#0A2CA5")
        self.assertEqual(f.color_family, "BLUE")

    def test_second_hex_normalized(self):
        from inventory.models import Filament
        f = Filament.objects.create(color="X", hex_code="#fff", hex_code_2="abcdef")
        self.assertEqual(f.hex_code_2, "#abcdef")
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.FilamentGradientTests -v2`
Expected: FAIL (`hex_code_2` unexpected kwarg).

- [ ] **Step 3: Edit the model**

Append to `COLOR_FAMILIES` (`models.py:146-159`), before the closing bracket:

```python
        ("GRADIENT", "Gradient"),
```

Add the field after `hex_code` (`models.py:108`):

```python
    hex_code_2 = models.CharField(
        max_length=7,
        blank=True,
        default="",
        help_text="Second hex for two-tone / gradient spools; renders a gradient swatch.",
    )
```

Add a static normalizer to `Filament` (next to `normalize_hex_code`):

```python
    @staticmethod
    def _norm_hex(value):
        """Return a normalized '#rrggbb' (or '#rgb') for ``value`` or None if invalid."""
        rev = value.strip().lower().lstrip("#")
        if re.fullmatch(r"(?:[0-9a-fA-F]{3}){1,2}", rev):
            return f"#{rev}"
        return None
```

Update `clean()` (`models.py:222-229`) to validate the second hex:

```python
    def clean(self):
        if self.hex_code:
            if self.normalize_hex_code() is None:
                raise ValidationError(
                    {"hex_code": "Invalid hex color code. Use 3 or 6 hex digits (e.g. #F0F or #FF00FF)."}
                )
        if self.hex_code_2:
            normalized = self._norm_hex(self.hex_code_2)
            if normalized is None:
                raise ValidationError(
                    {"hex_code_2": "Invalid hex color code. Use 3 or 6 hex digits."}
                )
            self.hex_code_2 = normalized
```

Update `save()` (`models.py:231-235`):

```python
    def save(self, *args, **kwargs):
        if self.hex_code_2:
            normalized = self._norm_hex(self.hex_code_2)
            if normalized:
                self.hex_code_2 = normalized
        if self.hex_code:
            self.normalize_hex_code()
            if self.hex_code_2:
                self.color_family = "GRADIENT"
            else:
                self.color_family = self.get_color_family()
        super().save(*args, **kwargs)
```

- [ ] **Step 4: Generate + apply migration**

Run:
```bash
~/.venvs/inventory/bin/python manage.py makemigrations inventory -n filament_hex_code_2
~/.venvs/inventory/bin/python manage.py migrate inventory
```
Expected: a migration adding `Filament.hex_code_2` and altering `color_family` choices; applies clean.

- [ ] **Step 5: Run tests, verify pass**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.FilamentGradientTests -v2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add inventory/models.py inventory/migrations/0038_*.py inventory/tests.py
git commit -m "feat: Filament.hex_code_2 + Gradient color family (migration 0038)"
```

---

## Task 3: Drying-warning regression guard (tri-state)

The wet-filament safety check (`models.py:700-742`) reads `material.drying_required` (now a property). PLA moves from blanket-`True` to `RECOMMENDED` → property `False`, so PLA NEW spools no longer get *blocked* from dry storage (intended). Lock it with a test; no production code change.

**Files:** Test: `inventory/tests.py`

- [ ] **Step 1: Write the test**

```python
class DryingWarningTriStateTests(TestCase):
    def _filament_at_new(self, drying_need):
        from inventory.models import Material, Filament, InventoryItem, Location
        mat = Material.objects.create(name="PLA", material_type="Basic", drying_need=drying_need)
        fil = Filament.objects.create(color="Black", hex_code="#000000", material=mat)
        item = InventoryItem.objects.create(product=fil, status=InventoryItem.Status.NEW)
        dry = Location.objects.create(name="DS-1", kind=Location.Kind.DRY_STORAGE)
        return item, dry

    def test_required_blocks_dry_storage(self):
        from inventory.models import Material
        item, dry = self._filament_at_new(Material.DryingNeed.REQUIRED)
        result = item.filament_drying_warning(dry)
        self.assertEqual(result[0], "error")

    def test_recommended_does_not_block_dry_storage(self):
        from inventory.models import Material
        item, dry = self._filament_at_new(Material.DryingNeed.RECOMMENDED)
        result = item.filament_drying_warning(dry)
        self.assertIsNone(result)
```

> Note: confirm `InventoryItem`/`Location` constructor kwargs against `inventory/models.py` (e.g. `Location.default_status` may be required). If creation errors (not the assertion), supply the missing non-null kwargs in the helper.

- [ ] **Step 2: Run, verify pass**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.DryingWarningTriStateTests -v2`
Expected: PASS (if FAIL, the property shim or warning logic is wrong — fix before continuing).

- [ ] **Step 3: Commit**

```bash
git add inventory/tests.py
git commit -m "test: lock drying-warning behavior under tri-state drying_need"
```

---

## Task 4: `MaterialAdmin` — surface category/drying_need, drop food_safe

**Files:** Modify: `inventory/admin.py` (`MaterialAdmin`, `admin.py:576+`)

- [ ] **Step 1: Edit the admin**

In `MaterialAdmin`:
- `list_display`: replace `"drying_required"` → `"drying_need"`; add `"category"` after `"mfr"`.
- `list_filter`: replace `"drying_required"` → `"drying_need"`; add `"category"`.
- First fieldset `fields`: replace `"drying_required"` → `"drying_need"`; add `"category"` after `"mfr"`.
- "Guide Properties" fieldset `fields`: **remove** `"food_safe"`.

- [ ] **Step 2: Verify**

Run: `~/.venvs/inventory/bin/python manage.py check`
Expected: `System check identified no issues`.

- [ ] **Step 3: Commit**

```bash
git add inventory/admin.py
git commit -m "feat: MaterialAdmin — category + drying_need, drop food_safe"
```

---

## Task 5: `load_guide_data` loader (service + command)

**Files:**
- Create: `inventory/guide_data.py`, `inventory/management/commands/load_guide_data.py`
- Test: `inventory/tests.py`

- [ ] **Step 1: Write failing tests**

```python
class LoadGuideDataTests(TestCase):
    def _write_csv(self, rows):
        import csv, tempfile, os
        fd, path = tempfile.mkstemp(suffix=".csv"); os.close(fd)
        cols = ["name","material_type","category","description","uv_resistant","flexible",
                "high_strength","heat_resistant","easy_to_print","budget_friendly",
                "impact_resistant","requires_enclosure","drying_need"]
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
            for r in rows: w.writerow(r)
        return path

    def test_creates_and_updates(self):
        from inventory.guide_data import load_guide_data
        from inventory.models import Material
        row = {"name":"PLA","material_type":"Basic","category":"everyday",
               "description":"Easy.","uv_resistant":0,"flexible":0,"high_strength":0,
               "heat_resistant":0,"easy_to_print":1,"budget_friendly":1,"impact_resistant":0,
               "requires_enclosure":0,"drying_need":"recommended"}
        path = self._write_csv([row])
        load_guide_data(path)
        m = Material.objects.get(name="PLA", material_type="Basic")
        self.assertTrue(m.easy_to_print)
        self.assertEqual(m.drying_need, "recommended")
        self.assertEqual(m.category, "everyday")
        stats2 = load_guide_data(path)  # idempotent
        self.assertEqual(stats2["created"], 0)
        self.assertEqual(stats2["updated"], 0)
```

- [ ] **Step 2: Run, verify fail**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.LoadGuideDataTests -v2`
Expected: FAIL (no module `inventory.guide_data`).

- [ ] **Step 3: Write the service**

Create `inventory/guide_data.py`:

```python
"""Load the validated filament-guide property matrix into ``Material`` rows.

Reads ``docs/filament-guide-data.csv`` (committed; 38 rows). Idempotent
``get_or_create`` keyed on ``(name, material_type)``. Human-gated: run the
``load_guide_data`` management command on prod after reviewing the CSV.
"""

import csv

from inventory.models import Material

BOOL_FIELDS = [
    "uv_resistant", "flexible", "high_strength", "heat_resistant",
    "easy_to_print", "budget_friendly", "impact_resistant", "requires_enclosure",
]


def _as_bool(value):
    return str(value).strip().lower() in ("1", "true", "yes", "y", "x")


def load_guide_data(csv_path, *, overwrite=True):
    """Apply the guide CSV to Material rows. Returns a counts dict.

    ``overwrite=True`` (default) sets every column from the CSV — it is the
    authoritative source. ``overwrite=False`` only fills blank/False fields."""
    stats = {"created": 0, "updated": 0, "unchanged": 0, "errors": []}
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            name = row["name"].strip()
            mtype = row["material_type"].strip()
            try:
                obj, created = Material.objects.get_or_create(name=name, material_type=mtype)
            except Exception as exc:  # noqa: BLE001 - report, don't crash the batch
                stats["errors"].append((f"{name} {mtype}", str(exc)))
                continue
            changed = False
            for f in BOOL_FIELDS:
                want = _as_bool(row[f])
                if (overwrite or not getattr(obj, f)) and getattr(obj, f) != want:
                    setattr(obj, f, want); changed = True
            for f in ("category", "drying_need", "description"):
                want = row[f].strip()
                if want and (overwrite or not getattr(obj, f)) and getattr(obj, f) != want:
                    setattr(obj, f, want); changed = True
            if changed:
                obj.save()
            stats["created" if created else ("updated" if changed else "unchanged")] += 1
    return stats
```

- [ ] **Step 4: Write the command**

Create `inventory/management/commands/load_guide_data.py`:

```python
"""Load docs/filament-guide-data.csv into Material guide fields (human-gated)."""

import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from inventory.guide_data import load_guide_data

DEFAULT_CSV = "docs/filament-guide-data.csv"


class Command(BaseCommand):
    help = "Load the filament-guide property matrix CSV into Material rows (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--csv", default=None, help=f"CSV path (default <BASE_DIR>/{DEFAULT_CSV}).")
        parser.add_argument("--fill-blank-only", action="store_true",
                            help="Only fill blank/False fields instead of overwriting.")

    def handle(self, *args, **options):
        path = options["csv"] or os.path.join(str(settings.BASE_DIR), DEFAULT_CSV)
        if not os.path.isfile(path):
            raise CommandError(f"CSV not found: {path}")
        stats = load_guide_data(path, overwrite=not options["fill_blank_only"])
        self.stdout.write(self.style.SUCCESS(
            f"created={stats['created']} updated={stats['updated']} unchanged={stats['unchanged']}"))
        for name, msg in stats["errors"]:
            self.stdout.write(self.style.WARNING(f"  - {name}: {msg}"))
```

- [ ] **Step 5: Run tests, verify pass**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.LoadGuideDataTests -v2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add inventory/guide_data.py inventory/management/commands/load_guide_data.py inventory/tests.py
git commit -m "feat: load_guide_data loader for the guide property matrix"
```

---

## Task 6: `load_filament_hex` loader (service + command)

**Files:**
- Create: `inventory/hex_loader.py`, `inventory/management/commands/load_filament_hex.py`
- Test: `inventory/tests.py`

- [ ] **Step 1: Write failing tests**

```python
class LoadFilamentHexTests(TestCase):
    def _write_csv(self, rows):
        import csv, tempfile, os
        fd, path = tempfile.mkstemp(suffix=".csv"); os.close(fd)
        cols = ["material","material_type","color_name","hex_code","hex_code_2","notes","source_file"]
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
            for r in rows: w.writerow(r)
        return path

    def test_fills_blank_hex_and_sets_family(self):
        from inventory.models import Material, Filament
        from inventory.hex_loader import load_filament_hex
        mat = Material.objects.create(name="PLA", material_type="Silk")
        fil = Filament.objects.create(color="Gold", hex_code="", material=mat)
        path = self._write_csv([{"material":"PLA","material_type":"Silk","color_name":"Gold",
                                 "hex_code":"#F4A925","hex_code_2":"","notes":"","source_file":"x"}])
        stats = load_filament_hex(path)
        fil.refresh_from_db()
        self.assertEqual(fil.hex_code, "#f4a925")
        self.assertTrue(fil.color_family)
        self.assertEqual(stats["filled"], 1)

    def test_gradient_two_hex(self):
        from inventory.models import Material, Filament
        from inventory.hex_loader import load_filament_hex
        mat = Material.objects.create(name="PLA", material_type="Gradient")
        fil = Filament.objects.create(color="Ocean to Meadow", hex_code="", material=mat)
        path = self._write_csv([{"material":"PLA","material_type":"Gradient",
                                 "color_name":"Ocean to Meadow","hex_code":"#307FE2",
                                 "hex_code_2":"#54FF9B","notes":"gradient","source_file":"x"}])
        load_filament_hex(path)
        fil.refresh_from_db()
        self.assertEqual(fil.color_family, "GRADIENT")

    def test_skips_already_set(self):
        from inventory.models import Material, Filament
        from inventory.hex_loader import load_filament_hex
        mat = Material.objects.create(name="PLA", material_type="Basic")
        Filament.objects.create(color="Black", hex_code="#111111", material=mat)
        path = self._write_csv([{"material":"PLA","material_type":"Basic","color_name":"Black",
                                 "hex_code":"#000000","hex_code_2":"","notes":"","source_file":"x"}])
        stats = load_filament_hex(path)  # overwrite=False default
        self.assertEqual(stats["filled"], 0)
        self.assertEqual(stats["skipped_set"], 1)
```

- [ ] **Step 2: Run, verify fail**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.LoadFilamentHexTests -v2`
Expected: FAIL (no module `inventory.hex_loader`).

- [ ] **Step 3: Write the service**

Create `inventory/hex_loader.py`:

```python
"""Backfill ``Filament.hex_code`` (+ ``hex_code_2``) from the merged color CSV.

Reads ``docs/filament-colors.csv`` (227 Bambu colors: 123 text-PDF parse + 104 vision
pass). Matches existing ``Filament`` spools by color name (case-insensitive), narrowed
by linked ``Material`` name/subtype when the CSV provides them. Only fills BLANK hex by
default. Unmatched rows are reported, never created. Human-gated."""

import csv

from inventory.models import Filament


def load_filament_hex(csv_path, *, overwrite=False):
    stats = {"filled": 0, "skipped_set": 0, "unmatched": []}
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            color = row["color_name"].strip()
            material = row["material"].strip()
            mtype = row["material_type"].strip()
            hex_code = row["hex_code"].strip()
            hex2 = (row.get("hex_code_2") or "").strip()
            if not color or not hex_code:
                continue

            qs = Filament.objects.filter(color__iexact=color)
            if material:
                narrowed = qs.filter(material__name__iexact=material)
                if mtype:
                    narrowed = narrowed.filter(material__material_type__iexact=mtype)
                if narrowed.exists():
                    qs = narrowed

            matches = list(qs)
            if not matches:
                stats["unmatched"].append(f"{material} {mtype} {color}".strip())
                continue
            for fil in matches:
                if fil.hex_code and not overwrite:
                    stats["skipped_set"] += 1
                    continue
                fil.hex_code = hex_code
                fil.hex_code_2 = hex2
                fil.save()  # recomputes color_family (GRADIENT when hex2 set)
                stats["filled"] += 1
    return stats
```

- [ ] **Step 4: Write the command**

Create `inventory/management/commands/load_filament_hex.py`:

```python
"""Backfill Filament hex codes from docs/filament-colors.csv (human-gated)."""

import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from inventory.hex_loader import load_filament_hex

DEFAULT_CSV = "docs/filament-colors.csv"


class Command(BaseCommand):
    help = "Backfill Filament.hex_code/hex_code_2 from the merged color CSV (blank-only by default)."

    def add_arguments(self, parser):
        parser.add_argument("--csv", default=None, help=f"CSV path (default <BASE_DIR>/{DEFAULT_CSV}).")
        parser.add_argument("--overwrite", action="store_true", help="Overwrite spools that already have a hex.")

    def handle(self, *args, **options):
        path = options["csv"] or os.path.join(str(settings.BASE_DIR), DEFAULT_CSV)
        if not os.path.isfile(path):
            raise CommandError(f"CSV not found: {path}")
        stats = load_filament_hex(path, overwrite=options["overwrite"])
        self.stdout.write(self.style.SUCCESS(
            f"filled={stats['filled']} skipped_set={stats['skipped_set']} "
            f"unmatched={len(stats['unmatched'])}"))
        for name in stats["unmatched"]:
            self.stdout.write(f"  unmatched: {name}")
```

- [ ] **Step 5: Run tests, verify pass**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.LoadFilamentHexTests -v2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add inventory/hex_loader.py inventory/management/commands/load_filament_hex.py inventory/tests.py
git commit -m "feat: load_filament_hex loader for blank hex backfill"
```

---

## Task 7: `FilamentGuideView` — grouped-by-base picker payload + options

**Files:**
- Modify: `inventory/views.py` (`FilamentGuideView`, `views.py:1198-1208`)
- Test: `inventory/tests.py`

- [ ] **Step 1: Write failing test**

```python
class FilamentGuidePayloadTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        from inventory.models import Material, Filament
        User.objects.create_user("u", password="p")
        for name, mt, cat in [("PLA","Basic","everyday"),("PLA","CF","everyday"),
                              ("PVA","","support")]:
            m = Material.objects.create(name=name, material_type=mt, category=cat)
            Filament.objects.create(color="C", hex_code="#111111", material=m)

    def test_payload_groups_by_base_and_excludes_support(self):
        self.client.login(username="u", password="p")
        resp = self.client.get("/filament-guide/")
        self.assertEqual(resp.status_code, 200)
        payload = resp.context["guide_payload"]
        names = {g["name"] for g in payload}
        self.assertIn("PLA", names)
        self.assertNotIn("PVA", names)  # SUPPORT excluded from picker
        pla = next(g for g in payload if g["name"] == "PLA")
        self.assertEqual({s["material_type"] for s in pla["subtypes"]}, {"Basic", "CF"})

    def test_picker_options_present(self):
        self.client.login(username="u", password="p")
        resp = self.client.get("/filament-guide/")
        self.assertEqual(len(resp.context["picker_options"]), 7)
```

- [ ] **Step 2: Run, verify fail**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.FilamentGuidePayloadTests -v2`
Expected: FAIL (`guide_payload` missing).

- [ ] **Step 3: Edit the view**

Replace `FilamentGuideView.get_context_data` (`views.py:1201-1208`) with:

```python
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        materials = (
            Material.objects.filter(filament__isnull=False)
            .distinct()
            .order_by("name", "material_type")
        )
        context["materials"] = materials  # full reference table (all categories)

        REQ_FIELDS = [
            "uv_resistant", "flexible", "high_strength", "heat_resistant",
            "easy_to_print", "budget_friendly", "impact_resistant",
        ]
        groups = {}
        for m in materials:
            if m.category == Material.Category.SUPPORT:
                continue  # excluded from the picker
            g = groups.setdefault(m.name, {
                "name": m.name, "category": m.category,
                "description": "", "subtypes": [],
            })
            sub = {"material_type": m.material_type,
                   "requires_enclosure": m.requires_enclosure,
                   "drying_need": m.drying_need,
                   "dry_temp": m.dry_temp_ideal_degC, "dry_time": m.dry_time_hrs,
                   "description": m.description}
            for f in REQ_FIELDS:
                sub[f] = getattr(m, f)
            g["subtypes"].append(sub)
            if (m.material_type in ("", "Basic") and m.description) or not g["description"]:
                g["description"] = m.description or g["description"]
        context["guide_payload"] = list(groups.values())

        context["picker_options"] = [
            ("uv_resistant", "UV Resistant", "Outdoor use or parts in direct sunlight."),
            ("flexible", "Flexible", "Bends or compresses without breaking (clips, gaskets)."),
            ("high_strength", "High Strength", "Load-bearing or structural — takes stress or weight."),
            ("heat_resistant", "Heat Resistant", "Near heat, in a car interior, or hot liquids."),
            ("easy_to_print", "Easy to Print", "Beginner-friendly; no enclosure or dryer needed."),
            ("budget_friendly", "Budget Friendly", "Cost is a priority."),
            ("impact_resistant", "Impact Resistant", "Absorbs shock without shattering."),
        ]
        return context
```

- [ ] **Step 4: Run, verify pass**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.FilamentGuidePayloadTests -v2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add inventory/views.py inventory/tests.py
git commit -m "feat: FilamentGuideView grouped-by-base picker payload + options (SUPPORT excluded)"
```

---

## Task 8: Reference table — drop food_safe, group by category, drying tri-state

**Files:** Modify: `inventory/templates/inventory/filament_guide.html`

- [ ] **Step 1: Update the table markup**

In `filament_guide.html`:
- Remove the `<th title="Safe for food contact">Food Safe</th>` (line 29) and its `<td>` block (lines 63-65).
- Add a leading `<th>Category</th>` as the **first** column header, and a matching first `<td>` per row (before the Material cell):

```html
                            <td data-order="{{ m.category }}">
                                {% if m.category == 'everyday' %}<span class="badge bg-primary">Everyday</span>
                                {% elif m.category == 'engineering' %}<span class="badge bg-secondary">Engineering</span>
                                {% elif m.category == 'flexible' %}<span class="badge bg-info text-dark">Flexible</span>
                                {% else %}<span class="badge bg-light text-dark">Support</span>{% endif %}
                            </td>
```

- Replace the drying-required `<td>` (lines 78-80) with the tri-state:

```html
                            <td data-sort="{{ m.drying_need }}" class="text-center">
                                {% if m.drying_need == 'required' %}<span class="text-warning">Required</span>
                                {% elif m.drying_need == 'recommended' %}<span class="text-muted">Recommended</span>
                                {% else %}<span class="text-muted">—</span>{% endif %}
                            </td>
```

- [ ] **Step 2: Group rows by category in the DataTable**

Replace the `new DataTable(...)` init (lines 100-106) with:

```javascript
        new DataTable('#filament-guide-table', {
            ordering: true, paging: false, info: false, searching: true,
            order: [],  // preserve server order (name, material_type) within groups
            columnDefs: [{
                targets: 0,
                render: function (data, type) {
                    if (type !== 'sort') return data;
                    return {everyday:'1',engineering:'2',flexible:'3',support:'4'}[data] || '9';
                },
            }],
            rowGroup: { dataSrc: 0 },
            language: { emptyTable: 'No materials with filament in inventory.' },
        });
```

> `rowGroup` is a DataTables extension. Check it's bundled: `grep -rn "rowGroup\|dataTables.rowGroup" inventory/templates/inventory/base.html inventory/static`. If absent, either add the rowGroup CDN `<script>`+CSS to `base.html`, or drop the `rowGroup` line and use `order: [[0,'asc']]` (sorted-by-category, ungrouped) as the fallback. Don't block on it.

- [ ] **Step 3: Verify + manual check**

Run: `~/.venvs/inventory/bin/python manage.py check`
Then eyeball `/filament-guide/`: no Food Safe column; Category badges; Everyday grouped/sorted first; drying shows Required/Recommended/—.

- [ ] **Step 4: Commit**

```bash
git add inventory/templates/inventory/filament_guide.html
git commit -m "feat: guide table — category grouping, drying tri-state, drop Food Safe"
```

---

## Task 9: Requirements picker — checkboxes, cards, scoring JS

**Files:**
- Modify: `inventory/templates/inventory/filament_guide.html` (replace the `{# Stage 2 #}` placeholder, line 15; load JS; ensure `{% load static %}` at top)
- Create: `inventory/static/inventory/js/filament_guide.js`
- Test: manual (no JS harness; scoring rule documented in spec §3.2 and below)

- [ ] **Step 1: Insert the picker markup + json_script**

Replace `{# Stage 2: requirements picker goes here #}` (line 15) with:

```html
    {{ guide_payload|json_script:"guide-data" }}
    <div class="card mb-4 no-print">
        <div class="card-body">
            <h5 class="card-title">What do you need from your part?</h5>
            <p class="text-muted small mb-3">Check what matters — we'll rank the materials that fit.</p>
            <div class="row" id="picker-checkboxes">
                {% for key, label, tip in picker_options %}
                <div class="col-6 col-md-4 col-lg-3 mb-2">
                    <div class="form-check">
                        <input class="form-check-input picker-req" type="checkbox" value="{{ key }}" id="req-{{ key }}">
                        <label class="form-check-label" for="req-{{ key }}" data-bs-toggle="tooltip" title="{{ tip }}">{{ label }}</label>
                    </div>
                </div>
                {% endfor %}
            </div>
            <div class="mt-2">
                <button type="button" class="btn btn-sm btn-outline-secondary" id="picker-clear">Clear</button>
                <span class="form-check form-check-inline float-end">
                    <input class="form-check-input" type="checkbox" id="picker-show-all">
                    <label class="form-check-label small" for="picker-show-all">Show all materials</label>
                </span>
            </div>
        </div>
    </div>
    <div id="picker-results" class="row mb-4"></div>
```

- [ ] **Step 2: Write the picker JS**

Create `inventory/static/inventory/js/filament_guide.js`. **Scoring rule** (must match spec §3.2): for each base group, each subtype's score = (checked reqs it satisfies)/(checked count); the base card's score is the best subtype's; ties prefer the base/Basic row; sort by score desc then EVERYDAY-first then name.

```javascript
(function () {
  "use strict";
  const data = JSON.parse(document.getElementById("guide-data").textContent);
  const REQ_LABELS = {
    uv_resistant: "UV Resistant", flexible: "Flexible", high_strength: "High Strength",
    heat_resistant: "Heat Resistant", easy_to_print: "Easy to Print",
    budget_friendly: "Budget Friendly", impact_resistant: "Impact Resistant",
  };
  const CAT_RANK = { everyday: 0, engineering: 1, flexible: 2, support: 3 };
  const results = document.getElementById("picker-results");

  function checkedReqs() {
    return Array.from(document.querySelectorAll(".picker-req:checked")).map((c) => c.value);
  }

  function scoreGroup(group, reqs) {
    let best = null;
    for (const sub of group.subtypes) {
      const satisfied = reqs.filter((r) => sub[r]).length;
      const score = reqs.length ? satisfied / reqs.length : 0;
      const isBase = sub.material_type === "" || sub.material_type === "Basic";
      if (!best || score > best.score || (score === best.score && isBase && !best.isBase)) {
        best = { sub, score, isBase };
      }
    }
    return best;
  }

  function chip(label, met) {
    return `<span class="badge ${met ? "bg-success" : "bg-light text-muted"} me-1">${met ? "✓" : "✗"} ${label}</span>`;
  }

  function card(group, best, reqs) {
    const score = best.score;
    let badge = "";
    if (score >= 0.999) badge = '<span class="badge bg-warning text-dark">★ Perfect match</span>';
    else if (score >= 0.5) badge = `<span class="badge bg-info text-dark">${Math.round(score * 100)}% match</span>`;
    const everyday = group.category === "everyday"
      ? '<span class="badge bg-primary me-1">Everyday favorite</span>' : "";
    const surfaced = (!best.isBase && best.sub.material_type)
      ? `<div class="small text-muted">best match: <strong>${group.name} ${best.sub.material_type}</strong></div>` : "";
    const chips = reqs.map((r) => chip(REQ_LABELS[r], best.sub[r])).join("");
    const warns = [];
    if (best.sub.drying_need === "required") {
      const dt = best.sub.dry_temp ? ` ${best.sub.dry_temp}°C` : "";
      const dh = best.sub.dry_time ? `/${best.sub.dry_time}h` : "";
      warns.push(`<span class="badge bg-warning text-dark me-1">⚠ Requires drying${dt}${dh}</span>`);
    } else if (best.sub.drying_need === "recommended") {
      warns.push('<span class="badge bg-light text-muted me-1">Drying recommended</span>');
    }
    if (best.sub.requires_enclosure) warns.push('<span class="badge bg-danger me-1">⚠ Needs enclosure</span>');
    return `<div class="col-md-6 col-lg-4 mb-3"><div class="card h-100"><div class="card-body">
      <div class="d-flex justify-content-between align-items-start">
        <h5 class="card-title mb-1">${group.name}</h5><div>${everyday}${badge}</div></div>
      <p class="card-text small text-muted">${group.description || ""}</p>${surfaced}
      <div class="mb-2">${chips}</div><div>${warns.join("")}</div>
    </div></div></div>`;
  }

  function emptyState() {
    const everyday = data.filter((g) => g.category === "everyday");
    const cards = everyday.map((g) =>
      `<div class="col-md-6 col-lg-3 mb-3"><div class="card h-100 border-primary"><div class="card-body">
        <span class="badge bg-primary mb-1">Everyday favorite</span>
        <h5 class="card-title">${g.name}</h5>
        <p class="card-text small text-muted">${g.description || ""}</p></div></div></div>`
    ).join("");
    results.innerHTML = `<div class="col-12"><p class="text-muted">New to this? Start with one of these four:</p></div>${cards}`;
  }

  function render() {
    const reqs = checkedReqs();
    if (!reqs.length) { emptyState(); return; }
    const showAll = document.getElementById("picker-show-all").checked;
    const scored = data.map((g) => ({ g, best: scoreGroup(g, reqs) }))
      .sort((a, b) => (b.best.score - a.best.score)
        || (CAT_RANK[a.g.category] - CAT_RANK[b.g.category])
        || a.g.name.localeCompare(b.g.name));
    const visible = scored.filter((s) => showAll || s.best.score >= 0.5);
    if (!visible.length) {
      results.innerHTML = '<div class="col-12"><p class="text-muted">No strong matches — tick "Show all materials".</p></div>';
      return;
    }
    results.innerHTML = visible.map((s) => card(s.g, s.best, reqs)).join("");
  }

  document.querySelectorAll(".picker-req").forEach((c) => c.addEventListener("change", render));
  document.getElementById("picker-show-all").addEventListener("change", render);
  document.getElementById("picker-clear").addEventListener("click", function () {
    document.querySelectorAll(".picker-req:checked").forEach((c) => (c.checked = false));
    render();
  });
  render();  // initial: empty state
})();
```

- [ ] **Step 3: Load the JS + init tooltips**

Ensure `{% load static %}` is at the top of `filament_guide.html`. In `{% block extra_scripts %}`, after the DataTable init `<script>`, add:

```html
<script src="{% static 'inventory/js/filament_guide.js' %}"></script>
```

Inside the existing `DOMContentLoaded` handler (where table-header tooltips are set up), add a line so the checkbox-label tooltips also initialize:

```javascript
        document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function (el) {
            new bootstrap.Tooltip(el);
        });
```

- [ ] **Step 4: Verify + manual check**

Run:
```bash
~/.venvs/inventory/bin/python manage.py check
~/.venvs/inventory/bin/python manage.py collectstatic --noinput
pre-commit run --files inventory/templates/inventory/filament_guide.html inventory/static/inventory/js/filament_guide.js
```
Then load `/filament-guide/`: nothing checked → "start with these four" band; check **High Strength** → PLA card surfaces "best match: PLA CF"; check **UV Resistant** → ASA/PETG rank above PET/PPS with "Everyday favorite" badges. **Flag James for a visual pass** — render quality (card layout/badges) can't be self-verified.

- [ ] **Step 5: Commit**

```bash
git add inventory/templates/inventory/filament_guide.html inventory/static/inventory/js/filament_guide.js
git commit -m "feat: filament requirements picker — base cards, best-subtype surfacing, category prominence"
```

---

## Task 10: Full validation, docs, PR

**Files:** Modify: `todo.md`, `CLAUDE.md`, `readme.md` (if it lists the guide)

- [ ] **Step 1: Full sweep**

```bash
~/.venvs/inventory/bin/python manage.py check
~/.venvs/inventory/bin/python manage.py makemigrations --check --dry-run
~/.venvs/inventory/bin/python manage.py test inventory -v1
```
Expected: check clean, no missing migrations, all tests pass. (Optional high-confidence check once deployed: `ssh inventory-manager 'docker exec inventory_management-web-1 python manage.py check'`.)

- [ ] **Step 2: Mark todo.md**

Under Phase 17: mark `17.2` (PNG vision + loader) and `17.3` (guide build + picker) `[x]`, noting the prod data-load stays human-gated. Leave `17.1 TDS loader` and `17.4 color sheets` unchecked.

- [ ] **Step 3: Update CLAUDE.md**

Add a "Phase 17.2/17.3 — what was done" paragraph mirroring the existing phase notes: schema (gradient `hex_code_2`, drying tri-state + `drying_required` property shim, `category`, dropped `food_safe`), two human-gated loaders, base-card/best-subtype picker. **State explicitly: the two loaders are NOT yet run on prod — James reviews `docs/filament-guide-data.csv` + `docs/filament-colors.csv` first, then runs `load_guide_data` + `load_filament_hex`.**

- [ ] **Step 4: Commit + push**

```bash
git add todo.md CLAUDE.md readme.md
git commit -m "docs: mark Phase 17.2/17.3 guide picker + data shipped"
git push
```

- [ ] **Step 5: Open the PR**

```bash
gh pr create --base master --head feat/filament-guide-picker \
  --title "feat: filament selection-guide picker + hex/guide data (Phase 17.2/17.3)" \
  --body "Spec: docs/superpowers/specs/2026-06-12-filament-guide-picker-and-data-design.md

Schema: Filament.hex_code_2 (gradient swatch), Material drying tri-state (drying_required
kept as a property so the wet-filament safety warning is untouched), category, food_safe
dropped. Two human-gated loaders (load_guide_data, load_filament_hex) + committed CSVs
(38 guide rows, 227 colors). Stage 2 requirements picker (base cards, best-subtype surfaced,
Everyday prominence).

POST-MERGE (James):
1. Review docs/filament-guide-data.csv + docs/filament-colors.csv.
2. On prod: manage.py migrate, manage.py load_guide_data, manage.py load_filament_hex.
3. Visual pass on /filament-guide/ (picker cards + table grouping).

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

---

## Self-Review Notes (executor)
- **Spec coverage:** §1.1 → T1/T3; §1.2 → T2; §1.3 migrations → T1/T2; §2 loaders → T5/T6; §3 picker → T7/T9; §4 table → T8. All covered.
- **Schema+migration coupled per commit** (pre-commit "missing migrations" hook + test DB built from migrations) — that's why T1/T2 include `makemigrations`.
- **Verify migration head** (`ls inventory/migrations/ | sort | tail -3`) before T1 — plan assumes `0036`.
- **PLA Tough / PLA Gradient** have no `Material` row → `load_filament_hex` logs them unmatched (expected, not a bug).
- **`Location`/`InventoryItem` kwargs** (T3) — confirm non-null fields against the model.
- **`rowGroup`** (T8) — graceful fallback to ordered-by-category if the extension isn't bundled.
- **Type consistency:** `guide_payload`/`picker_options` (view T7) ↔ `guide-data` json_script + `picker_options` loop (template T9) ↔ JS `JSON.parse("guide-data")`. Category values `everyday/engineering/flexible/support` and drying `not_needed/recommended/required` consistent across migration/view/template/JS. ✓
