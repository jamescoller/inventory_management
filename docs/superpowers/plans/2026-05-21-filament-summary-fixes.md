# Filament Summary — Post-Ship Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix seven UX/bug issues in `FilamentSummaryView` and its template identified after PR #92 shipped.

**Architecture:** All changes are isolated to two files — `inventory/views.py` (view logic, sort order, hex colour map) and `inventory/templates/inventory/filament_summary.html` (layout, JS, column headers). No new models, migrations, or URLs needed.

**Tech Stack:** Django 4.2, Bootstrap 5, DataTables, vanilla JS.

---

## File Map

| File | Change |
|------|--------|
| `inventory/views.py` | Fix sort order (cards by count, not name); fix `COLOR_FAMILY_HEX["BLACK"]`; add hex fallback for rows with missing `hex_code` |
| `inventory/templates/inventory/filament_summary.html` | Center header stats + cards; rename "Family" → "Color Family"; fix period-toggle active state; add subtype/material/color-family filter row above table |
| `inventory/tests.py` | Add `FilamentSummaryViewTests` covering the context values changed in this plan |

---

## Task 1: View-side fixes — sort order, BLACK hex, hex fallback

These three are all in `inventory/views.py`. Fix them together to keep the context window narrow.

**Files:**
- Modify: `inventory/views.py`
- Test: `inventory/tests.py`

- [ ] **Step 1: Write failing tests**

Add at the bottom of `inventory/tests.py`:

```python
from .models import Filament, Material, InventoryItem, Location
from django.urls import reverse


class FilamentSummaryViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="tester2", password="pass")
        self.client.login(username="tester2", password="pass")
        self.loc = Location.objects.create(name="Shelf", default_status=InventoryItem.Status.NEW)
        self.mat = Material.objects.create(name="PLA", material_type="")
        # 3 PLA rolls + 1 PETG roll — cards should sort by roll count, PLA first
        pla_black = Filament.objects.create(
            name="PLA Black", upc="1000000000001",
            material=self.mat, color="Black", color_family="BLACK",
            hex_code="",
        )
        petg_mat = Material.objects.create(name="PETG", material_type="")
        petg_white = Filament.objects.create(
            name="PETG White", upc="1000000000002",
            material=petg_mat, color="White", color_family="WHITE",
            hex_code="#ffffff",
        )
        for _ in range(3):
            InventoryItem.objects.create(product=pla_black, location=self.loc)
        InventoryItem.objects.create(product=petg_white, location=self.loc)
        self.url = reverse("filament_summary")

    def test_cards_sorted_by_roll_count_descending(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        cards = resp.context["cards"]
        counts = [c["total_on_hand"] for c in cards]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_black_family_hex_is_not_bootstrap_dark(self):
        """BLACK swatch should be pure black, not Bootstrap's dark (#2c3e50)."""
        resp = self.client.get(self.url)
        cards = resp.context["cards"]
        pla_card = next(c for c in cards if c["name"] == "PLA")
        black_swatch = next(s for s in pla_card["visible_swatches"] if s["family"] == "BLACK")
        self.assertEqual(black_swatch["hex"], "#000000")

    def test_row_hex_falls_back_to_family_hex_when_missing(self):
        """Row with no hex_code should get a fallback from COLOR_FAMILY_HEX."""
        resp = self.client.get(self.url)
        rows = resp.context["rows"]
        black_row = next(r for r in rows if r["color"] == "Black")
        # hex_code is empty in the DB, but color_family is BLACK → fallback expected
        self.assertEqual(black_row["hex_code"], "#000000")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/claude/projects/inventory_manager
python3 -m pytest inventory/tests.py::FilamentSummaryViewTests -v 2>&1 | tail -20
```

Expected: 3 FAILs (Django not installed here — note: run this via `docker exec` on 10.10.20.17 or confirm syntax-only with `python3 -c "import ast; ast.parse(open('inventory/tests.py').read())"`)

- [ ] **Step 3: Fix sort order in views.py**

In `inventory/views.py` around line 738–739, replace:

```python
        cards = []
        for mat_name in sorted(cards_dict):
```

with:

```python
        cards = []
        for mat_name in sorted(cards_dict, key=lambda m: -cards_dict[m]["total_on_hand"]):
```

- [ ] **Step 4: Fix BLACK hex in COLOR_FAMILY_HEX**

In `inventory/views.py` around line 66, replace:

```python
    "BLACK": "#2c3e50",
```

with:

```python
    "BLACK": "#000000",
```

- [ ] **Step 5: Add hex fallback when building rows**

In `inventory/views.py` around line 708, replace:

```python
                    "hex_code": row["hex_code"] or "",
```

with:

```python
                    "hex_code": row["hex_code"] or COLOR_FAMILY_HEX.get(row["color_family"] or "", ""),
```

- [ ] **Step 6: Syntax-validate**

```bash
python3 -c "import ast; ast.parse(open('inventory/views.py').read()); print('OK')"
python3 -c "import ast; ast.parse(open('inventory/tests.py').read()); print('OK')"
```

Expected: `OK` for both.

- [ ] **Step 7: Commit**

```bash
git add inventory/views.py inventory/tests.py
git commit -m "fix: sort filament cards by roll count; fix BLACK swatch to #000000; hex fallback from family"
```

---

## Task 2: Template — centering, column header, period toggle

Three simple template changes.

**Files:**
- Modify: `inventory/templates/inventory/filament_summary.html`

- [ ] **Step 1: Center the header stats row**

In `filament_summary.html` around line 7, replace:

```html
  <div class="d-flex gap-3 flex-wrap mb-4">
```

with:

```html
  <div class="d-flex gap-3 flex-wrap mb-4 justify-content-center">
```

- [ ] **Step 2: Center the material card grid**

Around line 23, replace:

```html
  <div class="d-flex flex-wrap gap-3 mb-4" id="material-cards">
```

with:

```html
  <div class="d-flex flex-wrap gap-3 mb-4 justify-content-center" id="material-cards">
```

- [ ] **Step 3: Rename column header**

Around line 83, replace:

```html
        <th>Family</th>
```

with:

```html
        <th>Color Family</th>
```

- [ ] **Step 4: Fix period toggle active state**

The `btn-outline-secondary` active state is too subtle (grey-on-grey). Switch to `btn-outline-primary` so the active button shows white text on blue (clearly inverted).

Around lines 65–71, replace:

```html
      <button type="button" class="btn btn-outline-secondary period-btn active"
              data-period="7d" onclick="setPeriod(this)">7d</button>
      <button type="button" class="btn btn-outline-secondary period-btn"
              data-period="30d" onclick="setPeriod(this)">30d</button>
      <button type="button" class="btn btn-outline-secondary period-btn"
              data-period="1y" onclick="setPeriod(this)">1y</button>
```

with:

```html
      <button type="button" class="btn btn-outline-primary period-btn active"
              data-period="7d" onclick="setPeriod(this)">7d</button>
      <button type="button" class="btn btn-outline-primary period-btn"
              data-period="30d" onclick="setPeriod(this)">30d</button>
      <button type="button" class="btn btn-outline-primary period-btn"
              data-period="1y" onclick="setPeriod(this)">1y</button>
```

- [ ] **Step 5: Commit**

```bash
git add inventory/templates/inventory/filament_summary.html
git commit -m "fix: center filament summary cards; rename Family header; improve period toggle contrast"
```

---

## Task 3: Add subtype / material / color-family filter row

Add three `<select>` dropdowns above the table. Populated dynamically from table data on page load. Wire into the existing JS filter state.

**Files:**
- Modify: `inventory/templates/inventory/filament_summary.html`

- [ ] **Step 1: Add the filter row HTML**

Insert the following block immediately before the `<!-- DataTables table -->` comment (around line 75):

```html
  <!-- Table filter row -->
  <div class="d-flex gap-2 flex-wrap align-items-center mb-2">
    <select id="filter-material" class="form-select form-select-sm" style="width:auto">
      <option value="">All Materials</option>
    </select>
    <select id="filter-subtype" class="form-select form-select-sm" style="width:auto">
      <option value="">All Subtypes</option>
    </select>
    <select id="filter-family" class="form-select form-select-sm" style="width:auto">
      <option value="">All Color Families</option>
    </select>
  </div>
```

- [ ] **Step 2: Add activeSubtype state and update applyFilters**

In the `<script>` block, at the top where filter state variables are declared, add `activeSubtype`:

```javascript
var activeMaterial = null;
var activeFamily = null;
var activeSubtype = null;
var activePeriod = '7d';
```

Replace the `applyFilters()` function body (the row-visibility loop) to also honour `activeSubtype`. Replace:

```javascript
    var show = (!activeMaterial || mat === activeMaterial) &&
               (!activeFamily || fam === activeFamily);
```

with:

```javascript
    var sub = row.dataset.subtype;
    var show = (!activeMaterial || mat === activeMaterial) &&
               (!activeFamily || fam === activeFamily) &&
               (!activeSubtype || sub === activeSubtype);
```

- [ ] **Step 3: Add data-subtype to table rows**

In the table `<tr>` around line 90, replace:

```html
      <tr data-material="{{ row.material_name }}" data-family="{{ row.color_family }}">
```

with:

```html
      <tr data-material="{{ row.material_name }}" data-family="{{ row.color_family }}" data-subtype="{{ row.material_type }}">
```

- [ ] **Step 4: Populate selects and wire change events in DOMContentLoaded**

At the end of the `DOMContentLoaded` handler (just before the closing `});`), add:

```javascript
  // Populate filter selects from table data
  var rows = document.querySelectorAll('#filament-summary-table tbody tr');
  var materials = new Set(), subtypes = new Set(), families = new Set();
  rows.forEach(function(row) {
    if (row.dataset.material) materials.add(row.dataset.material);
    if (row.dataset.subtype) subtypes.add(row.dataset.subtype);
    if (row.dataset.family) families.add(row.dataset.family);
  });
  function populateSelect(id, values) {
    var sel = document.getElementById(id);
    Array.from(values).sort().forEach(function(v) {
      var opt = document.createElement('option');
      opt.value = v; opt.textContent = v;
      sel.appendChild(opt);
    });
  }
  populateSelect('filter-material', materials);
  populateSelect('filter-subtype', subtypes);
  populateSelect('filter-family', families);

  document.getElementById('filter-material').addEventListener('change', function() {
    activeMaterial = this.value || null;
    activeFamily = null;
    document.getElementById('filter-family').value = '';
    applyFilters();
  });
  document.getElementById('filter-subtype').addEventListener('change', function() {
    activeSubtype = this.value || null;
    applyFilters();
  });
  document.getElementById('filter-family').addEventListener('change', function() {
    activeFamily = this.value || null;
    applyFilters();
  });
```

- [ ] **Step 5: Keep card-click and select in sync**

When a card is clicked (or cleared), update the material select to match. In `applyFilters()`, after the card active-state block (around line 177), add:

```javascript
  // Sync selects with active state
  var matSel = document.getElementById('filter-material');
  if (matSel) matSel.value = activeMaterial || '';
  var famSel = document.getElementById('filter-family');
  if (famSel) famSel.value = activeFamily || '';
```

- [ ] **Step 6: Syntax-validate template (basic check)**

```bash
python3 -c "
import re, sys
html = open('inventory/templates/inventory/filament_summary.html').read()
opens = len(re.findall(r'<(?!/)(?!br)(?!input)(?!img)(?!link)(?!meta)(\w+)', html))
closes = len(re.findall(r'</\w+>', html))
print(f'Open-ish tags: {opens}, close tags: {closes}')
print('No obvious template syntax errors checked by ast; visual review required.')
"
```

- [ ] **Step 7: Commit**

```bash
git add inventory/templates/inventory/filament_summary.html
git commit -m "feat: add material/subtype/color-family filter dropdowns to filament summary table"
```

---

## Task 4: PR

- [ ] **Step 1: Check todo.md items are all covered, mark done**

Mark each resolved item `[x]` in `todo.md` Phase 3 Bugs section.

- [ ] **Step 2: Push branch and open PR**

```bash
git push -u origin HEAD
gh pr create --title "fix: filament summary post-ship fixes" \
  --body "$(cat <<'EOF'
## Summary

- Sort material cards by roll count descending (was alphabetical)
- Fix BLACK family swatch to `#000000` (was Bootstrap dark `#2c3e50`)
- Fall back to `COLOR_FAMILY_HEX` for table rows missing `hex_code`
- Center header stats and material card grid
- Rename "Family" column header to "Color Family"
- Improve period toggle active state visibility (`btn-outline-primary`)
- Add Material / Subtype / Color Family filter dropdowns above the table

## Test plan

- [ ] Visit `/filament-summary/` — cards should appear sorted by count (most rolls first)
- [ ] Verify PLA Black swatch shows true black, not dark blue-grey
- [ ] Check table rows for "Black" filaments without individual hex codes show a black swatch
- [ ] Confirm header stats and cards are horizontally centered
- [ ] Confirm column header reads "Color Family" not "Family"
- [ ] Click 7d/30d/1y — active button should show white-on-blue (inverted), not subtle border change
- [ ] Use Material/Subtype/Color Family dropdowns — table rows filter correctly
- [ ] Click a material card — Material dropdown syncs to match; click again to clear

🤖 Generated with [Claude Code](https://claude.ai/code)
EOF
)"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] Cards sorted by roll count — Task 1 Step 3
- [x] BLACK = `#000000` — Task 1 Step 4
- [x] Center cards and totals — Task 2 Steps 1–2
- [x] Subtype/material/color-family filters above table — Task 3
- [x] "Family" → "Color Family" header — Task 2 Step 3
- [x] Period toggle active state — Task 2 Step 4
- [x] Hex fallback for missing hex_code — Task 1 Step 5

**Placeholder scan:** No TBDs or vague steps. All code blocks are complete.

**Type consistency:** `activeSubtype`, `activeMaterial`, `activeFamily` used consistently across all steps. `data-subtype` attribute added to both the template `<tr>` and read in JS.
