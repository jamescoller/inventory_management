# Filament Selection Guide — Design Spec

**Goal:** Add a `/filament-guide/` page that helps non-expert users select the right filament via a requirements picker, and gives expert users a full reference table.

**Audience:** Primary — partner and others asking for filament advice (non-expert). Secondary — James (expert, wants the reference table for himself).

**Staged delivery:** Stage 1 is a complete, useful feature on its own. Stage 2 builds on top of it.

---

## Stage 1 — Data Foundation + Reference Table

### Material model additions

Add the following fields to `inventory/models.py` on the `Material` model:

**Requirement flags** (used by the picker in Stage 2 — store now, use later):

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `uv_resistant` | BooleanField | False | Survives prolonged sunlight / outdoor exposure |
| `flexible` | BooleanField | False | Can bend or flex without fracturing |
| `high_strength` | BooleanField | False | Suitable for structural or load-bearing parts |
| `heat_resistant` | BooleanField | False | Tolerates elevated temperatures (car interiors, near heat sources, dishwasher) |
| `food_safe` | BooleanField | False | Safe for food contact (note: depends on printer/filament certification) |
| `easy_to_print` | BooleanField | False | Beginner-friendly; forgiving on open-frame printers without enclosure or drying |
| `budget_friendly` | BooleanField | False | Generally lower cost per spool relative to engineering filaments |
| `impact_resistant` | BooleanField | False | Absorbs impact without shattering (e.g. functional clips, protective parts) |

**Warning/info properties** (displayed on result cards and reference table — not filter criteria):

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `requires_enclosure` | BooleanField | False | VOCs or warping make this unsafe or impractical on open-frame printers; good ventilation required |
| `requires_drying` | BooleanField | False | Must be dried before printing for good results |
| `drying_temp_c` | PositiveSmallIntegerField | null/blank | Recommended drying temperature in °C |
| `drying_time_hours` | PositiveSmallIntegerField | null/blank | Recommended drying time in hours |
| `description` | CharField(max_length=200) | blank | One-sentence plain-English summary (shown on result cards and reference table) |

### Migration

Generate `0023_material_guide_fields.py` via `python manage.py makemigrations`. All boolean fields default to `False`; no data migration needed.

### Admin updates

Update `MaterialAdmin` in `inventory/admin.py`:
- Add a `Guide Properties` fieldset grouping all new fields for clean editing
- `drying_temp_c` and `drying_time_hours` should only display when `requires_drying` is True — use `fieldsets` with a JS collapse, or just group them visually

### Reference table view + template

**URL:** `/filament-guide/` → `FilamentGuideView` (GET only, `LoginRequiredMixin`)

**Context:** All `Material` objects with at least one `Filament` FK, ordered alphabetically. Pass the full field list so the template can render all columns.

**Template:** `inventory/templates/inventory/filament_guide.html`

Layout:
- Page header: "Filament Selection Guide"
- DataTables table with columns: Material | Description | UV | Flexible | Strength | Heat | Food Safe | Easy to Print | Budget | Impact | Enclosure Req. | Drying Req. | Drying Temp | Drying Time
- Boolean columns render as ✓ / — (not Yes/No — more scannable)
- `requires_enclosure` and `requires_drying` columns use a warning colour (Bootstrap `text-warning`) on ✓
- Stage 2 picker section is absent in Stage 1 — add a placeholder comment `{# Stage 2: requirements picker goes here #}`

**Nav:** Add "Filament Guide" link to `navigation.html` alongside "Filament Summary"

### Data loading (separate task after Stage 1 ships)

Once Stage 1 is deployed, James will provide source documentation and Haiku agents will be dispatched to populate the new fields for all existing `Material` rows via Django shell or a management command. This is out of scope for the Stage 1 implementation plan.

---

## Stage 2 — Requirements Picker

### Requirements picker UI

Inserted above the reference table at `/filament-guide/`.

**Layout:** Two-column grid of labelled checkboxes. Each label has a Bootstrap tooltip (`data-bs-toggle="tooltip"`, `title="..."`) that appears on hover.

Checkbox labels and tooltip text:

| Checkbox label | Tooltip |
|----------------|---------|
| UV Resistant | Important for outdoor use or parts exposed to direct sunlight indoors. |
| Flexible | The part needs to bend, flex, or compress without breaking (e.g. clips, gaskets, phone cases). |
| High Strength | Load-bearing or structural use — the part will be stressed or take weight. |
| Heat Resistant | Near heat sources, in a car interior, or in contact with hot liquids / dishwasher. |
| Food Safe | Will come into contact with food or drink. Note: both the filament and the printer must be certified. |
| Easy to Print | Beginner-friendly or printing without an enclosure or dryer. |
| Budget Friendly | Cost is a priority — avoiding expensive engineering filaments. |
| Impact Resistant | The part needs to absorb shock without shattering (e.g. protective covers, functional clips). |

### Scoring and results display

When one or more checkboxes are checked, results render below the checkboxes (above the reference table) in a card grid.

**Scoring:** For each material, count how many checked requirements it satisfies. Score = satisfied / total checked.

**Result card anatomy:**
```
┌─────────────────────────────────────────────────┐
│ ★ PETG                    [Perfect match]        │
│ Tough, chemical-resistant, easy to print.        │
│                                                  │
│ [✓ UV Resistant] [✓ High Strength] [✓ Easy]      │
│                                                  │
│ ⚠ Requires drying  65°C / 4h                    │
└─────────────────────────────────────────────────┘
```

- **Perfect match** (score = 1.0): gold star + "Perfect match" badge, shown first
- **Partial match** (score ≥ 0.5): shown below perfect matches, sorted by score descending. Met requirements show green `✓ Label` chips; unmet requirements show muted `✗ Label` chips.
- **Poor match** (score < 0.5): hidden by default; a "Show all materials" toggle reveals them
- `requires_enclosure`: red `⚠ Requires enclosure` badge on the card
- `requires_drying`: amber `⚠ Requires drying` badge with temp/time if set
- If no checkboxes checked: results section hidden, only reference table shows

### Implementation

**No server round-trips.** All material data is embedded in the page as a `json_script` block (same pattern as the dashboard charts — avoids XSS). JS reads it, filters and scores on checkbox change, re-renders the card grid via DOM manipulation.

**Data shape passed from view:**
```python
[{
    "name": "PETG",
    "description": "Tough, chemical-resistant...",
    "uv_resistant": True,
    "flexible": False,
    "high_strength": True,
    # ... all 8 requirement flags ...
    "requires_enclosure": False,
    "requires_drying": True,
    "drying_temp_c": 65,
    "drying_time_hours": 4,
}]
```

**No new URL or view** — Stage 2 is purely additive changes to `FilamentGuideView.get_context_data()` and `filament_guide.html`.

---

## What this is NOT

- No polar/radar charts — the badge-per-requirement approach is more scannable and less complex
- No user accounts or saved preferences
- No "compare two materials" feature
- The picker does not filter the reference table — they are independent UI sections

---

## Files touched

| File | Change |
|------|--------|
| `inventory/models.py` | Add 13 fields to `Material` |
| `inventory/migrations/0023_*.py` | Generated migration |
| `inventory/admin.py` | Add `Guide Properties` fieldset to `MaterialAdmin` |
| `inventory/views.py` | Add `FilamentGuideView` |
| `inventory/urls.py` | Add `/filament-guide/` URL |
| `inventory/templates/inventory/filament_guide.html` | New template (Stage 1: table; Stage 2: picker + cards) |
| `inventory/templates/inventory/navigation.html` | Add nav link |
