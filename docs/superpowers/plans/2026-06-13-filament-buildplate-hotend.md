# Phase 17.1 Build-plate & Hot-end — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Populate + display `Material.build_plate_compat` / `hot_end_compat` via the existing reviewed-CSV + `load_material_specs` pipeline. No migration.

**Architecture:** Small parser cleanup → extend the committed CSV with two columns → extend the loader to write them (blank-only) → add two columns to the guide reference table.

**Tech Stack:** Django 6.0, SQLite, Bootstrap/DataTables, Django `TestCase`. No new deps.

**Spec:** `docs/superpowers/specs/2026-06-13-filament-buildplate-hotend-design.md`

**Conventions:**
- Python via `~/.venvs/inventory/bin/python`. Tests in `inventory/tests.py`; run a class with
  `~/.venvs/inventory/bin/python manage.py test inventory.tests.<ClassName> -v 2`.
- `~/.venvs/inventory/bin/python manage.py check` after Python edits.
- Branch `feat/filament-buildplate-hotend` is already checked out. Commit per task. Do NOT push/PR.
- pre-commit hooks run on commit; re-stage if they auto-fix.

---

### Task 1: Parser camel-case cleanup in `_extract_build_plate`

**Files:** Modify `inventory/filament_tds.py` (`_extract_build_plate`, ~line 115). Test: `inventory/tests.py`.

- [ ] **Step 1: Write the failing test.** Append to `inventory/tests.py`:

```python
class BuildPlateParserCleanupTests(TestCase):
    def test_splits_concatenated_plate_names(self):
        from inventory.filament_tds import _extract_build_plate

        # Simulates PDF text-extraction concatenation around the Bed Type row.
        text = "Build Plate Type TexturedPEIPlate Bed Temperature 60"
        self.assertEqual(_extract_build_plate(text), "Textured PEI Plate")

    def test_plain_value_still_parses(self):
        from inventory.filament_tds import _extract_build_plate

        text = "Bed Type Cool Plate / Textured PEI Plate Bed Surface foo"
        self.assertEqual(
            _extract_build_plate(text), "Cool Plate, Textured PEI Plate"
        )
```

- [ ] **Step 2: Run it; expect FAIL** (`test_splits_concatenated_plate_names` returns `"TexturedPEIPlate"`).
  `~/.venvs/inventory/bin/python manage.py test inventory.tests.BuildPlateParserCleanupTests -v 2`

- [ ] **Step 3: Implement.** In `_extract_build_plate`, after `val = _norm(m.group(1))` and before the separator normalization, insert:

```python
    # PDF text extraction concatenates words ("TexturedPEIPlate"); re-insert
    # spaces at case boundaries before normalizing separators.
    val = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", val)
    val = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", val)
```

- [ ] **Step 4: Run the test; expect PASS.** Also `~/.venvs/inventory/bin/python manage.py check`.

- [ ] **Step 5: Commit.**
```bash
git add inventory/filament_tds.py inventory/tests.py
git commit -m "fix: split concatenated build-plate names in TDS parser"
```

---

### Task 2: Extend `docs/filament-tds-specs.csv` with build-plate + hot-end columns

**Files:** Modify `docs/filament-tds-specs.csv`.

- [ ] **Step 1: Generate build-plate drafts.** Run the cleaned parser over the TDS PDFs and read the
  review CSV it writes (gitignored `filament_review/`):
  `~/.venvs/inventory/bin/python manage.py parse_filament_tds` (then read the printed output path).
  Map each `(name, material_type)` in `docs/filament-tds-specs.csv` to the parser's
  `build_plate_compat` value. Rows with no TDS PDF (some `Support` variants) → leave blank.

- [ ] **Step 2: Apply the hot-end rule.** For each of the 38 rows set `hot_end_compat`:
  - **"Hardened steel"** if `material_type` contains `CF` or `GF`, OR name/`material_type` ∈
    {`Glow`, `Metal`, `Marble`, `Wood`, `Sparkle`, `Galaxy`}.
  - **"Standard"** otherwise.

- [ ] **Step 3: Rewrite the CSV** with the new header and all 38 rows:
  `name,material_type,dry_temp_ideal_degC,dry_time_hrs,build_plate_compat,hot_end_compat`
  Preserve the existing `dry_temp_ideal_degC,dry_time_hrs` values exactly. Quote any
  `build_plate_compat` value that contains a comma. Example rows:
  `PLA,Basic,50,8,"Cool Plate, Textured PEI Plate, Engineering Plate",Standard`
  `PLA,CF,55,8,"Textured PEI Plate",Hardened steel`
  `ABS,GF,80,8,"Textured PEI Plate",Hardened steel`

- [ ] **Step 4: Verify the CSV parses** with the same columns and 38 data rows:
```bash
~/.venvs/inventory/bin/python -c "import csv; r=list(csv.DictReader(open('docs/filament-tds-specs.csv'))); print(len(r), sorted(r[0].keys()))"
```
Expected: `38 ['build_plate_compat', 'dry_temp_ideal_degC', 'dry_time_hrs', 'hot_end_compat', 'material_type', 'name']`

- [ ] **Step 5: Commit.**
```bash
git add docs/filament-tds-specs.csv
git commit -m "data: add reviewed build-plate + hot-end columns to TDS specs CSV"
```

---

### Task 3: Extend `material_specs.py` loader for the two string fields

**Files:** Modify `inventory/material_specs.py`. Test: `inventory/tests.py`.

- [ ] **Step 1: Write the failing test.** Append to `inventory/tests.py`:

```python
class MaterialSpecsStringFieldsTests(TestCase):
    def _csv(self, line):
        import os
        import tempfile

        fd, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(
                "name,material_type,dry_temp_ideal_degC,dry_time_hrs,"
                "build_plate_compat,hot_end_compat\n" + line + "\n"
            )
        return path

    def test_fills_blank_string_fields(self):
        from inventory.material_specs import load_material_specs
        from inventory.models import Material

        Material.objects.create(name="PLA", material_type="CF")
        path = self._csv('PLA,CF,55,8,"Textured PEI Plate",Hardened steel')
        load_material_specs(path)
        m = Material.objects.get(name="PLA", material_type="CF")
        self.assertEqual(m.build_plate_compat, "Textured PEI Plate")
        self.assertEqual(m.hot_end_compat, "Hardened steel")
        self.assertEqual(m.dry_temp_ideal_degC, 55)  # ints still load

    def test_blank_only_does_not_overwrite(self):
        from inventory.material_specs import load_material_specs
        from inventory.models import Material

        Material.objects.create(
            name="PLA", material_type="Matte", build_plate_compat="Cool Plate"
        )
        path = self._csv('PLA,Matte,50,8,"Textured PEI Plate",Standard')
        load_material_specs(path)  # overwrite=False default
        m = Material.objects.get(name="PLA", material_type="Matte")
        self.assertEqual(m.build_plate_compat, "Cool Plate")  # unchanged
        self.assertEqual(m.hot_end_compat, "Standard")  # was blank -> filled

    def test_overwrite_replaces_string(self):
        from inventory.material_specs import load_material_specs
        from inventory.models import Material

        Material.objects.create(
            name="ABS", material_type="", build_plate_compat="Old"
        )
        path = self._csv('ABS,,80,8,"Textured PEI Plate",Standard')
        load_material_specs(path, overwrite=True)
        m = Material.objects.get(name="ABS", material_type="")
        self.assertEqual(m.build_plate_compat, "Textured PEI Plate")
```

- [ ] **Step 2: Run; expect FAIL** (loader ignores string fields).

- [ ] **Step 3: Implement.** Edit `inventory/material_specs.py`:

Add after `INT_FIELDS`:
```python
STR_FIELDS = ["build_plate_compat", "hot_end_compat"]
```

In `load_material_specs`, after the `for f in INT_FIELDS:` loop (before the `if changed:` block), add:
```python
            for f in STR_FIELDS:
                want = (row.get(f) or "").strip()
                if not want:
                    continue
                if (overwrite or getattr(obj, f) == "") and getattr(obj, f) != want:
                    setattr(obj, f, want)
                    changed = True
```

Change the save line from `obj.save(update_fields=INT_FIELDS)` to:
```python
                obj.save(update_fields=INT_FIELDS + STR_FIELDS)
```

- [ ] **Step 4: Run the test; expect PASS.** Then `manage.py check`.

- [ ] **Step 5: Commit.**
```bash
git add inventory/material_specs.py inventory/tests.py
git commit -m "feat: load build-plate + hot-end specs in load_material_specs (blank-only)"
```

---

### Task 4: Display Build Plate + Hot End in the guide reference table

**Files:** Modify `inventory/templates/inventory/filament_guide.html`. Test: `inventory/tests.py`.

- [ ] **Step 1: Write the failing test.** Append to `inventory/tests.py`:

```python
class GuideTableSpecColumnsTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User

        self.client = Client()
        User.objects.create_user("guideuser", "g@b.com", "pass")
        self.client.login(username="guideuser", password="pass")

    def test_table_shows_buildplate_and_hotend(self):
        from inventory.models import Material

        Material.objects.create(
            name="PLA", material_type="CF",
            build_plate_compat="Textured PEI Plate", hot_end_compat="Hardened steel",
        )
        resp = self.client.get(reverse("filament_guide"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Build Plate")
        self.assertContains(resp, "Hot End")
        self.assertContains(resp, "Textured PEI Plate")
        self.assertContains(resp, "Hardened steel")
```

- [ ] **Step 2: Run; expect FAIL** (columns absent).

- [ ] **Step 3: Implement.** In `inventory/templates/inventory/filament_guide.html`:

After the `<th ...>Drying Time</th>` header (~line 61), add:
```html
                            <th title="Compatible build-plate surfaces">Build Plate</th>
                            <th title="Nozzle / hot-end requirement">Hot End</th>
```

After the drying-time `<td>` body cell (the one rendering `m.dry_time_hrs`, ~line 115), add:
```html
                            <td>
                                {% if m.build_plate_compat %}{{ m.build_plate_compat }}{% else %}<span class="text-muted">—</span>{% endif %}
                            </td>
                            <td>
                                {% if m.hot_end_compat %}{{ m.hot_end_compat }}{% else %}<span class="text-muted">—</span>{% endif %}
                            </td>
```

Verify there is no `{% empty %}` `colspan` row to update; if one exists, bump its colspan to match the new total (16). Header `<th>` count must equal body `<td>` count.

- [ ] **Step 4: Run the test; expect PASS.** Then `manage.py check`.

- [ ] **Step 5: Commit.**
```bash
pre-commit run --files inventory/templates/inventory/filament_guide.html || true
git add inventory/templates/inventory/filament_guide.html inventory/tests.py
git commit -m "feat: build-plate + hot-end columns in the filament guide table"
```

---

### Task 5: Docs + final validation

**Files:** Modify `todo.md`, `CLAUDE.md`.

- [ ] **Step 1:** In `todo.md`, change the open 17.1 sub-item ("Build-plate / hot-end still pending")
  to `[x]` with a one-line note: build-plate spacing fixed in the parser; build-plate (from a
  cleaned parse) + hot-end (rule-based) loaded via the extended `docs/filament-tds-specs.csv` +
  `load_material_specs`; shown in the guide reference table. Human-gated prod re-run.

- [ ] **Step 2:** Add a brief Phase 17.1 follow-up note to `CLAUDE.md` (near the existing 17.1
  entry): the two `Material` free-text fields are now loaded from the same CSV/loader; hot-end is
  rule-based (abrasive → hardened steel) because the TDS rarely states it; prod step is a
  `load_material_specs` re-run (blank-only).

- [ ] **Step 3: Full suite + check.**
  `~/.venvs/inventory/bin/python manage.py test inventory -v 1` (expect OK) and
  `~/.venvs/inventory/bin/python manage.py check`.

- [ ] **Step 4: Commit.**
```bash
git add todo.md CLAUDE.md
git commit -m "docs: record Phase 17.1 build-plate + hot-end completion"
```

---

## Deploy checklist (post-merge, James)
1. No migration. After deploy, review the extended `docs/filament-tds-specs.csv`.
2. `ssh inventory-manager 'docker exec inventory_management-web-1 python manage.py load_material_specs'`
   — blank-only; fills build-plate/hot-end without touching drying temps.
3. Eyeball `/filament-guide/` — the two new columns populated.
