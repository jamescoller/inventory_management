# Filament Guide Picker + Data Load — Design Spec (2026-06-12)

Supersedes the **Stage 2** half of `2026-05-21-filament-guide-design.md` (Stage 1 — the
reference table — shipped). Scope: finish Phase **17.2** (hex backfill) and **17.3** (guide
data + requirements picker), plus the schema changes those need. This is the "one coherent
PR" for the overnight build.

**Out of scope (fast-follow PRs):** 17.1 TDS→specs loader (drying temps / build-plate / hot-end),
17.4 color sheets + Bambu Store link. The picker *displays* drying temp/time if present but does
not populate them here.

---

## 1. Schema changes

### 1.1 `Material`
- **`category`** — `CharField(choices=Category)`, new `Category` TextChoices:
  `EVERYDAY`, `ENGINEERING`, `FLEXIBLE`, `SUPPORT`. Default `EVERYDAY`. Drives table grouping +
  picker prominence. `SUPPORT` rows are **excluded from the picker** (shown only in the table).
- **`drying_need`** — `CharField(choices=DryingNeed)`, new `DryingNeed` TextChoices:
  `NOT_NEEDED`, `RECOMMENDED`, `REQUIRED`. Replaces the boolean `drying_required`.
  - Keep **`drying_required` as a `@property`** → `self.drying_need == DryingNeed.REQUIRED`, so the
    existing wet-filament safety check (`filament_drying_warning()`, `models.py:721/727/733`),
    admin, and the Stage-1 table keep working **unchanged**. Only the model gains a richer field.
  - `filament_drying_warning()` keeps reading `drying_required` (the property) — no logic change
    needed there; verify the 3 call sites still behave (PLA → `RECOMMENDED` → property False → no
    wet-storage *block*, which is the correct, intended change from today's blanket True).
- **Drop `food_safe`** (`BooleanField`, currently all-False — trivial, no real data loss). Remove
  from model, admin, Stage-1 table, and the picker checkbox set.
- Already present from 17.1, no change: `build_plate_compat`, `hot_end_compat`, `requires_enclosure`,
  `dry_temp_ideal_degC`, `dry_time_hrs`, `description`.

### 1.2 `Filament`
- **`hex_code_2`** — `CharField(max_length=7, blank=True, default="")`, nullable-ish (blank). When
  set, the spool is a two-tone/gradient; the swatch renders a CSS `linear-gradient`.
- `get_color_family()` / `color_family`: add a `"Gradient"` family. A `Filament` with `hex_code_2`
  set is classified `color_family="Gradient"` (so it does not pollute solid-color filters).

### 1.3 Migrations
One migration, ordered: add `category` + `drying_need` (with `default`), **RunPython** to set
`drying_need = REQUIRED where drying_required else NOT_NEEDED` (then the loader corrects PLA →
RECOMMENDED), backfill `category` from a base-name map, **then** remove `drying_required` column and
`food_safe`. Add `Filament.hex_code_2`. No NOT-NULL-without-default traps. Flag to James: this drops
two columns — both safe (one derived, one all-False), backed up nightly regardless.

---

## 2. Data loaders (idempotent, `update_or_create`, human-gated run)

Both are management commands; **James runs them on prod after reviewing the committed CSVs.** Both
fill only blank fields by default (`--overwrite` to force).

### 2.1 `load_guide_data` ← `docs/filament-guide-data.csv` (committed, 38 rows, this session)
Columns: `name, material_type, category, description, uv_resistant, flexible, high_strength,
heat_resistant, easy_to_print, budget_friendly, impact_resistant, requires_enclosure, drying_need`.
Keyed on `(name, material_type)` (the existing unique constraint). Sets the 7 booleans + enclosure +
`category` + `drying_need` + `description`. `drying_need` strings map to the enum.

### 2.2 `load_filament_hex` ← `docs/filament-colors.csv` (committed; merge of the two review CSVs)
Build by merging:
- `filament_review/filament-hex-review.csv` (123 colors, text-PDF parse, gitignored) +
- `filament_review/filament-hex-from-png.csv` (104 colors, vision pass, this session, gitignored)
→ committed `docs/filament-colors.csv` (`material, material_type, color_name, hex_code, hex_code_2, notes`;
227 rows). The loader matches `Filament` rows by color name (+ material/subtype where possible) with a
blank/placeholder `hex_code` and fills `hex_code` (+ `hex_code_2` for the 8 gradients); `Filament.save()`
recomputes `color_family` (gradients → `"Gradient"`). No-match rows are logged, not created.
**Spot-check flags from the vision pass:** the 8 PLA-Basic-Gradient pairs (low-res source),
`PLA Silk Candy Green #018814`, `PA6-GF Gray #353533`, `TPU 95A HF Black #101820`,
`PETG-HF Peanut Brown #875718`.

---

## 3. Requirements picker (Stage 2) — `/filament-guide/`

Purely additive to `FilamentGuideView.get_context_data()` + `filament_guide.html`. **No server
round-trips** — all material data embedded via `json_script` (dashboard/charts pattern), JS scores
on checkbox change and re-renders cards. New JS file `static/inventory/js/filament_guide.js`
(consistent with the 18.2 inline-JS-extraction direction).

### 3.1 Inputs
**7 checkboxes** (food_safe removed): UV Resistant, Flexible, High Strength, Heat Resistant,
Easy to Print, Budget Friendly, Impact Resistant. Each has a Bootstrap tooltip (text carried over
from the May-21 spec, minus Food Safe).

### 3.2 Scoring & "base card, best subtype surfaced"
Card granularity = **base polymer** (group the 38 Material rows by `name`), `SUPPORT` excluded.
For each base, among its subtypes compute each subtype's score = (checked requirements it satisfies)
/ (number checked). The **base card's score = the best subtype's score**, and the card surfaces that
subtype's name when it beats the base/Basic row (e.g. "PLA — best match: **PLA-CF**"). The base's
own `description` is shown; the surfaced subtype is a labeled chip. With **0 checked**, no scoring;
see empty state (§3.4).

### 3.3 Card anatomy
```
┌───────────────────────────────────────────────┐
│ ★ ASA            [Everyday favorite] [Perfect]  │
│ ABS's UV-stable cousin: top choice for outdoor… │
│ best match: ASA-CF                              │
│ [✓ UV Resistant] [✓ High Strength] [✗ Budget]   │
│ ⚠ Requires drying 80°C/4h   ⚠ Needs enclosure   │
└───────────────────────────────────────────────┘
```
- **Perfect** (score 1.0): gold star + "Perfect match", sorted first.
- **Partial** (≥0.5): below perfect, score desc. Met → green `✓` chips; unmet → muted `✗` chips.
- **Poor** (<0.5): hidden behind a "Show all materials" toggle.
- **Tie-break: `EVERYDAY` sorts before other categories at equal score.**
- `EVERYDAY` cards carry an **"Everyday favorite"** badge.
- `drying_need`: `REQUIRED` → amber "Requires drying" (+ temp/time if set); `RECOMMENDED` → grey
  "Drying recommended"; `NOT_NEEDED` → nothing.
- `requires_enclosure` → red "Needs enclosure" badge.

### 3.4 Empty state (nothing checked)
A "New to this? Start with one of these four" band showing the four `EVERYDAY` bases
(PLA, PETG, ABS, ASA) as cards — page is useful before any box is checked.

---

## 4. Reference table updates (Stage 1 table, same page)
- **Drop the Food Safe column.**
- **Group rows by `category`** with section headers in order: *Everyday Filaments*, *Engineering*,
  *Flexible*, *Support* (DataTables `rowGroup`, or pre-grouped render). EVERYDAY visually banded/first.
- Drying column shows tri-state (Required / Recommended / —) instead of ✓/—.
- Swatch columns (if any filament swatches shown) render gradient via `hex_code_2`.

---

## 5. Files touched
| File | Change |
|------|--------|
| `inventory/models.py` | `Material.Category`, `Material.DryingNeed`, `category`, `drying_need` fields; `drying_required` → property; drop `food_safe`; `Filament.hex_code_2`; `get_color_family()` Gradient bucket |
| `inventory/migrations/00XX_*.py` | schema + RunPython (drying/category backfill), drop columns |
| `inventory/admin.py` | MaterialAdmin: add category/drying_need, drop food_safe |
| `inventory/views.py` | `FilamentGuideView.get_context_data()` — embed per-material json_script (grouped by base), category, drying_need |
| `inventory/templates/inventory/filament_guide.html` | picker checkboxes + card grid + empty-state band; table grouping; drop Food Safe col |
| `inventory/static/inventory/js/filament_guide.js` | new — scoring, best-subtype surfacing, render |
| `inventory/management/commands/load_guide_data.py` | new loader |
| `inventory/management/commands/load_filament_hex.py` | new loader |
| `docs/filament-guide-data.csv` | filled (this session) |
| `docs/filament-colors.csv` | new — merged 227-color hex data |

## 6. Tests
- Model: `drying_required` property == (`drying_need`==REQUIRED); `get_color_family` gradient.
- Loaders: idempotent re-run is a no-op; blank-only fill; `--overwrite`; bad row logged not crashed.
- View: `/filament-guide/` 200; json_script present; SUPPORT excluded from picker payload; EVERYDAY
  flagged; the grouped-by-base payload shape is asserted. Picker scoring runs in JS (no JS test
  harness in this repo) — verified manually; the scoring *rule* is documented in §3.2 so the JS and a
  reviewer agree on expected output.
- Migration: existing `drying_required=True` → `REQUIRED`; category backfill by base.

## 7. What this is NOT
- No radar/polar charts; no saved preferences; no "compare two"; the picker does **not** filter the
  reference table (independent sections). No TDS drying-temp population (fast-follow). No color sheets
  (fast-follow).
