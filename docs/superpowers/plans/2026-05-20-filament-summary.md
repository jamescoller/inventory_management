# Filament Summary View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/filament-summary/` page showing aggregated filament inventory by material+subtype+color, with clickable material cards (color-family swatches), a period-toggleable usage column, and JS-filtered DataTables table.

**Architecture:** Split `Material.name` (compound, e.g. "PETG HF") into `name` (base polymer) + `material_type` (modifier) via schema migration 0021 + data migration 0022. A new `FilamentSummaryView` runs two `Filament.objects.values().annotate()` queries and passes cards + rows to a server-rendered template. Client-side JS handles filtering and period toggle — no HTMX needed at ~172 rows.

**Tech Stack:** Django 4.2, Bootstrap 5 (Zephyr), DataTables 1.13.6, vanilla JS

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `inventory/models.py` | Add `material_type` field, remove `unique=True` from `name`, add `unique_together`, update `__str__` |
| Create | `inventory/migrations/0021_material_type.py` | Schema migration: add field + constraint change |
| Create | `inventory/migrations/0022_material_type_data.py` | Data migration: split compound names |
| Modify | `inventory/admin.py` | Add `material_type` to `MaterialAdmin.list_display` + `list_editable` |
| Modify | `inventory/views.py` | Add `FilamentSummaryView` |
| Modify | `inventory/urls.py` | Add `/filament-summary/` URL pattern |
| Modify | `inventory/templates/inventory/navigation.html` | Add nav link |
| Create | `inventory/templates/inventory/filament_summary.html` | Card grid + filter bar + DataTables table |

---

## Task 1: Add `material_type` to Material model

**Files:**
- Modify: `inventory/models.py:673-728`

- [ ] **Step 1: Edit models.py — add field, update constraint, update `__str__`**

Replace the `Material` model fields section (lines 703–727) with:

```python
    name = models.CharField(max_length=100)
    material_type = models.CharField(max_length=50, blank=True, default="")
    # name = base polymer (e.g. "PETG", "PLA"); material_type = subtype modifier (e.g. "HF", "CF")
    mfr = models.CharField(max_length=100, blank=True, default="Bambu Lab")
```

Add a `Meta` class and update `__str__` at the end of the `Material` class (after `notes = models.TextField(blank=True)` at line 724):

```python
    class Meta:
        unique_together = [('name', 'material_type')]
        ordering = ['name', 'material_type']

    def __str__(self):
        if self.material_type:
            return f"{self.name} {self.material_type}"
        return self.name
```

Remove the old `def __str__(self): return self.name` at line 726.

- [ ] **Step 2: Syntax validate**

```bash
python3 -c "import ast; ast.parse(open('inventory/models.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit models.py change**

```bash
git add inventory/models.py
git commit -m "feat: add material_type field to Material model

Split compound name (e.g. 'PETG HF') into name + material_type.
Schema migration follows in 0021."
```

---

## Task 2: Schema migration 0021

**Files:**
- Create: `inventory/migrations/0021_material_type.py`

- [ ] **Step 1: Write the migration file**

```python
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0020_phase2_dead_code_removal'),
    ]

    operations = [
        migrations.AddField(
            model_name='material',
            name='material_type',
            field=models.CharField(blank=True, default='', max_length=50),
        ),
        migrations.AlterField(
            model_name='material',
            name='name',
            field=models.CharField(max_length=100),
        ),
        migrations.AlterUniqueTogether(
            name='material',
            unique_together={('name', 'material_type')},
        ),
    ]
```

- [ ] **Step 2: Syntax validate**

```bash
python3 -c "import ast; ast.parse(open('inventory/migrations/0021_material_type.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Apply on app LXC and verify**

```bash
ssh inventory-manager "docker exec inventory_management-web-1 python manage.py migrate inventory 0021"
```

Expected output ends with: `Applying inventory.0021_material_type... OK`

- [ ] **Step 4: Confirm no Django config errors**

```bash
ssh inventory-manager "docker exec inventory_management-web-1 python manage.py check"
```

Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 5: Commit**

```bash
git add inventory/migrations/0021_material_type.py
git commit -m "feat: schema migration 0021 — add material_type to Material"
```

---

## Task 3: Data migration 0022

**Files:**
- Create: `inventory/migrations/0022_material_type_data.py`

Splits all 38 existing compound material names. Rules applied in priority order:
1. `"Support for X"` → `name="Support"`, `material_type="for X"`
2. Hyphen pattern `"X-Y"` → `name=X`, `material_type=Y` (e.g. `"PA6-CF"`, `"PLA-CF"`, `"ABS-GF"`)
3. Space pattern `"X Y"` where X is a known base type → `name=X`, `material_type=Y` (e.g. `"PETG HF"`, `"PLA Matte"`, `"ASA Aero"`)
4. Single word or unrecognised → `material_type=""` unchanged

- [ ] **Step 1: Write the data migration**

```python
from django.db import migrations

KNOWN_BASE_TYPES = {
    'ABS', 'ASA', 'PA6', 'PAHT', 'PC', 'PET', 'PETG',
    'PLA', 'PPS', 'PVA', 'Support', 'TPU',
}


def split_material_names(apps, schema_editor):
    Material = apps.get_model('inventory', 'Material')
    for mat in Material.objects.all():
        name = mat.name
        # Rule 1: "Support for X" (must come before space-split to avoid "Support" matching X Y)
        if name.startswith('Support for '):
            mat.name = 'Support'
            mat.material_type = name[len('Support '):]   # "for X"
        # Rule 2: hyphen — "X-Y"
        elif '-' in name:
            base, modifier = name.split('-', 1)
            mat.name = base
            mat.material_type = modifier
        # Rule 3: space — "X Y" where X is a known base
        elif ' ' in name:
            base, modifier = name.split(' ', 1)
            if base in KNOWN_BASE_TYPES:
                mat.name = base
                mat.material_type = modifier
            # else: unknown pattern, leave name unchanged, material_type stays ''
        # Rule 4: single word — nothing to do
        mat.save()


def reverse_split(apps, schema_editor):
    Material = apps.get_model('inventory', 'Material')
    for mat in Material.objects.all():
        if mat.material_type:
            mat.name = f'{mat.name} {mat.material_type}'
            mat.material_type = ''
            mat.save()


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0021_material_type'),
    ]

    operations = [
        migrations.RunPython(split_material_names, reverse_code=reverse_split),
    ]
```

- [ ] **Step 2: Syntax validate**

```bash
python3 -c "import ast; ast.parse(open('inventory/migrations/0022_material_type_data.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Apply and verify splits**

```bash
ssh inventory-manager "docker exec inventory_management-web-1 python manage.py migrate inventory 0022"
```

Expected: `Applying inventory.0022_material_type_data... OK`

Spot-check the splits in the shell:

```bash
ssh inventory-manager "docker exec inventory_management-web-1 python manage.py shell -c \"
from inventory.models import Material
for m in Material.objects.order_by('name', 'material_type'):
    print(repr(m.name), repr(m.material_type))
\""
```

Verify key cases:
- `'PETG' 'HF'` ✓
- `'PA6' 'CF'` ✓
- `'Support' 'for ABS'` ✓
- `'TPU' '95A HF'` ✓ (space-split, TPU is a known base)
- `'ABS' ''` ✓ (single word)

- [ ] **Step 4: Commit**

```bash
git add inventory/migrations/0022_material_type_data.py
git commit -m "feat: data migration 0022 — split compound Material names into name + material_type"
```

---

## Task 4: Update MaterialAdmin

**Files:**
- Modify: `inventory/admin.py:393-408`

- [ ] **Step 1: Add `material_type` to `list_display` and add `list_editable`**

Replace the current `MaterialAdmin` class:

```python
class MaterialAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "material_type",
        "mfr",
        "print_temp_min_degC",
        "print_temp_max_degC",
        "print_temp_ideal_degC",
        "dry_temp_min_degC",
        "dry_temp_max_degC",
        "dry_temp_ideal_degC",
        "dry_time_hrs",
        "ams_capable",
        "drying_required",
        "notes",
    ]
    list_editable = ["name", "material_type"]
    list_filter = ["mfr", "ams_capable", "drying_required"]
```

- [ ] **Step 2: Syntax validate**

```bash
python3 -c "import ast; ast.parse(open('inventory/admin.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add inventory/admin.py
git commit -m "feat: add material_type to MaterialAdmin with list_editable for bulk correction"
```

---

## Task 5: Add FilamentSummaryView

**Files:**
- Modify: `inventory/views.py`

The view runs two `Filament.objects.values().annotate()` queries then builds cards and rows in Python.

- [ ] **Step 1: Add the view class after `FilamentColorGuideView` (after line 618 in views.py)**

First, add the import at the top of views.py (find the `from datetime import` line or add near the top imports):

```python
from datetime import timedelta
```

Then add the view after `FilamentColorGuideView`:

```python
class FilamentSummaryView(LoginRequiredMixin, TemplateView):
    template_name = "inventory/filament_summary.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()
        cutoff_7 = now - timedelta(days=7)
        cutoff_30 = now - timedelta(days=30)
        cutoff_365 = now - timedelta(days=365)
        DEPLETED = InventoryItem.Status.DEPLETED

        # Active inventory grouped by (material, subtype, color, family)
        active_qs = list(
            Filament.objects.values(
                "material__name",
                "material__material_type",
                "color",
                "color_family",
            ).annotate(
                on_hand=Count(
                    "inventory_items",
                    filter=Q(inventory_items__status__in=_ACTIVE_STATUSES),
                ),
                hex_code=Max("hex_code"),
                weight=Max("weight"),
            )
        )

        # Depleted counts for all three windows in one query
        depleted_map = {
            (
                row["material__name"],
                row["material__material_type"],
                row["color"],
                row["color_family"],
            ): row
            for row in Filament.objects.values(
                "material__name",
                "material__material_type",
                "color",
                "color_family",
            ).annotate(
                depleted_7=Count(
                    "inventory_items",
                    filter=Q(
                        inventory_items__status=DEPLETED,
                        inventory_items__date_depleted__gte=cutoff_7,
                    ),
                ),
                depleted_30=Count(
                    "inventory_items",
                    filter=Q(
                        inventory_items__status=DEPLETED,
                        inventory_items__date_depleted__gte=cutoff_30,
                    ),
                ),
                depleted_365=Count(
                    "inventory_items",
                    filter=Q(
                        inventory_items__status=DEPLETED,
                        inventory_items__date_depleted__gte=cutoff_365,
                    ),
                ),
            ).filter(
                Q(depleted_7__gt=0) | Q(depleted_30__gt=0) | Q(depleted_365__gt=0)
            )
        }

        # Build table rows
        rows = []
        for row in active_qs:
            key = (
                row["material__name"],
                row["material__material_type"],
                row["color"],
                row["color_family"],
            )
            dep = depleted_map.get(key, {})
            on_hand = row["on_hand"]
            weight = row["weight"]
            est_kg = round(float(weight) * on_hand, 2) if weight and on_hand else None
            rows.append(
                {
                    "material_name": row["material__name"] or "",
                    "material_type": row["material__material_type"] or "",
                    "color": row["color"] or "",
                    "color_family": row["color_family"] or "",
                    "hex_code": row["hex_code"] or "",
                    "on_hand": on_hand,
                    "used_7d": dep.get("depleted_7", 0),
                    "used_30d": dep.get("depleted_30", 0),
                    "used_365d": dep.get("depleted_365", 0),
                    "est_weight_kg": est_kg,
                }
            )
        rows.sort(key=lambda r: (r["material_name"], r["material_type"], r["color"]))

        # Build material cards
        cards_dict = {}
        for row in rows:
            mat = row["material_name"]
            if mat not in cards_dict:
                cards_dict[mat] = {
                    "name": mat,
                    "total_on_hand": 0,
                    "subtypes": set(),
                    "family_counts": {},
                }
            cards_dict[mat]["total_on_hand"] += row["on_hand"]
            if row["material_type"]:
                cards_dict[mat]["subtypes"].add(row["material_type"])
            fam = row["color_family"]
            if fam:
                cards_dict[mat]["family_counts"][fam] = (
                    cards_dict[mat]["family_counts"].get(fam, 0) + row["on_hand"]
                )

        cards = []
        for mat_name in sorted(cards_dict):
            data = cards_dict[mat_name]
            all_swatches = sorted(
                [
                    {
                        "family": fam,
                        "hex": COLOR_FAMILY_HEX.get(fam, "#cccccc"),
                        "count": cnt,
                    }
                    for fam, cnt in data["family_counts"].items()
                ],
                key=lambda x: -x["count"],
            )
            cards.append(
                {
                    "name": data["name"],
                    "total_on_hand": data["total_on_hand"],
                    "subtype_count": len(data["subtypes"]),
                    "visible_swatches": all_swatches[:8],
                    "hidden_swatches": all_swatches[8:],
                    "extra_count": max(0, len(all_swatches) - 8),
                }
            )

        context["cards"] = cards
        context["rows"] = rows
        context["grand_total_rolls"] = sum(r["on_hand"] for r in rows)
        context["total_filament_types"] = len(rows)
        context["total_materials"] = len(cards)
        return context
```

- [ ] **Step 2: Syntax validate**

```bash
python3 -c "import ast; ast.parse(open('inventory/views.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Check imports — ensure these are all present near the top of views.py**

```python
from datetime import timedelta          # add if missing
from django.db.models import Count, Max, Q
from django.utils import timezone
```

Search: `grep -n "^from datetime\|^from django.db.models\|^from django.utils import timezone" inventory/views.py`

- [ ] **Step 4: Commit**

```bash
git add inventory/views.py
git commit -m "feat: add FilamentSummaryView with two-query aggregation and card/row context"
```

---

## Task 6: URL + navigation

**Files:**
- Modify: `inventory/urls.py`
- Modify: `inventory/templates/inventory/navigation.html`

- [ ] **Step 1: Add import + URL pattern to urls.py**

In the import block at the top (after `FilamentColorGuideView`), add `FilamentSummaryView`:

```python
from .views import (
    AboutView,
    AddAMSView,
    AddDryerView,
    AddFilamentView,
    AddHardwareView,
    AddInventoryView,
    AddPrinterView,
    AddProductChoiceView,
    BarcodeRedirectView,
    BulkUpdateView,
    Dashboard,
    DryStorageOverviewView,
    FilamentColorGuideView,
    FilamentSummaryView,
    Index,
    InventoryEditView,
    InventoryExportView,
    InventorySearchView,
    InUseOverviewView,
    PrintBarcodeView,
    SignUpView,
)
```

Add the URL pattern after the `filament-color-guide/` line:

```python
    path("filament-summary/", FilamentSummaryView.as_view(), name="filament_summary"),
```

- [ ] **Step 2: Add nav link to navigation.html**

After the existing "Colors" `<li>` nav item (after line 20), insert:

```html
					<li class="nav-item">
						<a class="nav-link" href="{% url 'filament_summary' %}">
							<i class="bi bi-bar-chart-fill"></i> Filament
						</a>
					</li>
```

- [ ] **Step 3: Syntax validate**

```bash
python3 -c "import ast; ast.parse(open('inventory/urls.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add inventory/urls.py inventory/templates/inventory/navigation.html
git commit -m "feat: add /filament-summary/ URL and nav link"
```

---

## Task 7: Create filament_summary.html template

**Files:**
- Create: `inventory/templates/inventory/filament_summary.html`

- [ ] **Step 1: Write the template**

```html
{% extends "inventory/base.html" %}

{% block content %}
<div class="container-fluid py-3">

  <!-- Header stats -->
  <div class="d-flex gap-3 flex-wrap mb-4">
    <div class="card text-center px-4 py-2">
      <div class="fw-bold fs-3">{{ grand_total_rolls }}</div>
      <div class="text-muted small">Total Rolls</div>
    </div>
    <div class="card text-center px-4 py-2">
      <div class="fw-bold fs-3">{{ total_filament_types }}</div>
      <div class="text-muted small">Color/Type Combos</div>
    </div>
    <div class="card text-center px-4 py-2">
      <div class="fw-bold fs-3">{{ total_materials }}</div>
      <div class="text-muted small">Materials</div>
    </div>
  </div>

  <!-- Material card grid -->
  <div class="d-flex flex-wrap gap-3 mb-4" id="material-cards">
    {% for card in cards %}
    <div class="card filament-card"
         style="min-width:145px; max-width:200px; cursor:pointer"
         data-material="{{ card.name }}"
         onclick="filterByMaterial('{{ card.name }}')">
      <div class="card-body p-2">
        <div class="fw-semibold">{{ card.name }}</div>
        <div class="text-muted small mb-1">
          {{ card.total_on_hand }} roll{{ card.total_on_hand|pluralize }}{% if card.subtype_count %} &middot; {{ card.subtype_count }} type{{ card.subtype_count|pluralize }}{% endif %}
        </div>
        <div class="d-flex flex-wrap gap-1 swatch-container">
          {% for swatch in card.visible_swatches %}
          <span class="swatch"
                style="width:18px;height:18px;border-radius:3px;display:inline-block;background:{{ swatch.hex }};border:1px solid rgba(0,0,0,.15);cursor:pointer"
                title="{{ swatch.family }} — {{ swatch.count }} roll{{ swatch.count|pluralize }}"
                onclick="event.stopPropagation(); filterByFamily('{{ card.name }}', '{{ swatch.family }}')"></span>
          {% endfor %}
          {% for swatch in card.hidden_swatches %}
          <span class="swatch swatch-hidden"
                style="width:18px;height:18px;border-radius:3px;display:none;background:{{ swatch.hex }};border:1px solid rgba(0,0,0,.15);cursor:pointer"
                title="{{ swatch.family }} — {{ swatch.count }} roll{{ swatch.count|pluralize }}"
                onclick="event.stopPropagation(); filterByFamily('{{ card.name }}', '{{ swatch.family }}')"></span>
          {% endfor %}
          {% if card.extra_count %}
          <button class="btn btn-link btn-sm p-0 lh-1 expand-btn"
                  style="font-size:.75rem"
                  data-extra="{{ card.extra_count }}"
                  data-expanded="false"
                  onclick="event.stopPropagation(); toggleOverflow(this)">
            +{{ card.extra_count }} more
          </button>
          {% endif %}
        </div>
      </div>
    </div>
    {% endfor %}
  </div>

  <!-- Filter chip bar -->
  <div class="d-flex align-items-center gap-2 flex-wrap mb-2" id="filter-bar">
    <div id="active-filter-chips"></div>
    <div class="btn-group btn-group-sm ms-auto" role="group" aria-label="Usage period">
      <button type="button" class="btn btn-outline-secondary period-btn active"
              data-period="7d" onclick="setPeriod(this)">7d</button>
      <button type="button" class="btn btn-outline-secondary period-btn"
              data-period="30d" onclick="setPeriod(this)">30d</button>
      <button type="button" class="btn btn-outline-secondary period-btn"
              data-period="1y" onclick="setPeriod(this)">1y</button>
    </div>
    <span class="text-muted small ms-2" id="row-count-label"></span>
  </div>

  <!-- DataTables table -->
  <table id="filament-summary-table" class="table table-sm table-hover">
    <thead>
      <tr>
        <th>Material</th>
        <th>Subtype</th>
        <th>Color</th>
        <th>Family</th>
        <th>On Hand</th>
        <th>Used (<span id="period-label">7d</span>)</th>
        <th>Est. Weight (kg)</th>
      </tr>
    </thead>
    <tbody>
      {% for row in rows %}
      <tr data-material="{{ row.material_name }}" data-family="{{ row.color_family }}">
        <td>{{ row.material_name }}</td>
        <td>{{ row.material_type|default:"—" }}</td>
        <td>
          {% if row.hex_code %}
          <span style="display:inline-block;width:12px;height:12px;border-radius:2px;
                       background:{{ row.hex_code }};border:1px solid rgba(0,0,0,.2);
                       vertical-align:middle;margin-right:4px"></span>
          {% endif %}
          {{ row.color }}
        </td>
        <td>{{ row.color_family }}</td>
        <td>{{ row.on_hand }}</td>
        <td class="usage-cell"
            data-used-7d="{{ row.used_7d }}"
            data-used-30d="{{ row.used_30d }}"
            data-used-365d="{{ row.used_365d }}">
          {% if row.used_7d %}{{ row.used_7d }}{% else %}&mdash;{% endif %}
        </td>
        <td>{% if row.est_weight_kg %}{{ row.est_weight_kg }}{% else %}&mdash;{% endif %}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>

</div>
{% endblock %}

{% block extra_scripts %}
<script>
var activeMaterial = null;
var activeFamily = null;
var activePeriod = '7d';

function filterByMaterial(material) {
  if (activeMaterial === material && activeFamily === null) {
    activeMaterial = null;
  } else {
    activeMaterial = material;
    activeFamily = null;
  }
  applyFilters();
}

function filterByFamily(material, family) {
  if (activeMaterial === material && activeFamily === family) {
    activeMaterial = null;
    activeFamily = null;
  } else {
    activeMaterial = material;
    activeFamily = family;
  }
  applyFilters();
}

function clearFilters() {
  activeMaterial = null;
  activeFamily = null;
  applyFilters();
}

function applyFilters() {
  var rows = document.querySelectorAll('#filament-summary-table tbody tr');
  var visible = 0;
  rows.forEach(function(row) {
    var mat = row.dataset.material;
    var fam = row.dataset.family;
    var show = (!activeMaterial || mat === activeMaterial) &&
               (!activeFamily || fam === activeFamily);
    row.style.display = show ? '' : 'none';
    if (show) visible++;
  });

  // Card active state
  document.querySelectorAll('.filament-card').forEach(function(card) {
    card.classList.toggle('border-primary', card.dataset.material === activeMaterial);
    card.classList.toggle('bg-light', card.dataset.material === activeMaterial);
  });

  // Filter chips
  var chips = '';
  if (activeMaterial) {
    chips += '<span class="badge bg-primary me-1">' + activeMaterial +
             ' <span style="cursor:pointer" onclick="filterByMaterial(\'' + activeMaterial + '\')">&#x2715;</span></span>';
  }
  if (activeFamily) {
    chips += '<span class="badge bg-secondary me-1">' + activeFamily +
             ' <span style="cursor:pointer" onclick="filterByFamily(\'' + activeMaterial + '\',\'' + activeFamily + '\')">&#x2715;</span></span>';
  }
  if (chips) {
    chips += '<button class="btn btn-link btn-sm p-0" onclick="clearFilters()">Clear all</button>';
  }
  document.getElementById('active-filter-chips').innerHTML = chips;

  document.getElementById('row-count-label').textContent = visible + ' row' + (visible !== 1 ? 's' : '');
}

function setPeriod(btn) {
  activePeriod = btn.dataset.period;
  document.querySelectorAll('.period-btn').forEach(function(b) {
    b.classList.remove('active');
  });
  btn.classList.add('active');

  var attrKey = activePeriod === '1y' ? 'used-365d' : 'used-' + activePeriod;
  document.querySelectorAll('.usage-cell').forEach(function(cell) {
    var val = parseInt(cell.dataset[attrKey.replace('-', '')] || '0', 10);
    // dataset converts "used-7d" -> "used7d", "used-30d" -> "used30d", "used-365d" -> "used365d"
    // Re-read using getAttribute for safety
    var raw = parseInt(cell.getAttribute('data-' + attrKey) || '0', 10);
    cell.textContent = raw > 0 ? raw : '—';
  });
  document.getElementById('period-label').textContent = activePeriod;
}

function toggleOverflow(btn) {
  var container = btn.closest('.swatch-container');
  var hidden = container.querySelectorAll('.swatch-hidden');
  var isExpanded = btn.dataset.expanded === 'true';
  if (isExpanded) {
    hidden.forEach(function(s) { s.style.display = 'none'; });
    btn.textContent = '+' + btn.dataset.extra + ' more';
    btn.dataset.expanded = 'false';
  } else {
    hidden.forEach(function(s) { s.style.display = 'inline-block'; });
    btn.textContent = 'show less';
    btn.dataset.expanded = 'true';
  }
}

document.addEventListener('DOMContentLoaded', function() {
  new DataTable('#filament-summary-table', {
    ordering: true,
    searching: false,
    paging: false,
    info: false,
  });
  applyFilters();
});
</script>
{% endblock %}
```

- [ ] **Step 2: Commit**

```bash
git add inventory/templates/inventory/filament_summary.html
git commit -m "feat: add filament_summary.html — card grid, DataTables, JS filtering and period toggle"
```

---

## Task 8: End-to-end validation

- [ ] **Step 1: Apply all migrations and run Django check**

```bash
ssh inventory-manager "docker exec inventory_management-web-1 python manage.py migrate && python manage.py check"
```

Expected: migrations applied, `System check identified no issues (0 silenced).`

- [ ] **Step 2: Load the page and verify rendering**

Open `http://10.10.20.17:8080/filament-summary/` in a browser.

Check:
- Header stats show non-zero values
- Material cards render with correct names (e.g. "PETG", "PLA", "ABS" — not "PETG HF")
- Each card shows color family swatches sorted by count descending
- Cards with > 8 families show "+N more" button
- Clicking "+N more" expands swatches in place; "show less" collapses
- Table shows one row per (material, subtype, color) — aggregated
- Clicking a card filters the table to that material; card gets blue border
- Clicking a swatch filters by material + family
- Period toggle 7d/30d/1y swaps the Usage column (check with a depleted item)
- Filter chip bar shows active filter with ✕ to clear
- Material subtype column shows "—" for base types (e.g. plain "ABS")

- [ ] **Step 3: Verify MaterialAdmin bulk edit**

Open `http://10.10.20.17:8080/admin/inventory/material/` — confirm `name` and `material_type` columns are editable inline. Spot-check a few rows to confirm data migration ran correctly.

- [ ] **Step 4: Review and update todo.md**

Check `todo.md` for any items this PR closes. Mark them `[x]`.

- [ ] **Step 5: Final commit and push**

```bash
git status  # confirm clean or only todo.md
git add todo.md  # if updated
git commit -m "docs: mark filament summary view complete in todo.md"
git push origin feat/filament-summary
```

Then open a PR against `master`.

---

## Spec Coverage Checklist

- [x] `Material.material_type` field added — Task 1
- [x] `unique=True` dropped, `unique_together` added — Task 2 (migration)
- [x] Data migration splits all 38 compound names — Task 3
- [x] `MaterialAdmin` with `list_editable = ['name', 'material_type']` — Task 4
- [x] `FilamentSummaryView` at `/filament-summary/` — Tasks 5, 6
- [x] Two DB queries (active + depleted) using `Filament.objects.values().annotate()` — Task 5
- [x] Card per distinct `material.name` with `total_on_hand`, `subtype_count`, `family_swatches` — Task 5
- [x] Swatches sorted by count descending — Task 5
- [x] First 8 swatches visible; overflow expanded in-place — Task 7
- [x] Hover tooltip: "FAMILY — N rolls" — Task 7
- [x] Click card → filter table — Task 7
- [x] Click swatch → filter by material + family — Task 7
- [x] Filter chip bar with ✕ clear — Task 7
- [x] Period toggle 7d/30d/1y (no reload) — Task 7
- [x] DataTables: ordering=true, searching=false, paging=false — Task 7
- [x] One row per (material_name, material_type, color) — Task 5 aggregation
- [x] Zero usage shown as "—" — Task 7
- [x] Header stats: grand_total_rolls, total_filament_types, total_materials — Tasks 5, 7
- [x] Est. weight = on_hand × filament.weight — Task 5
- [x] Nav link — Task 6
