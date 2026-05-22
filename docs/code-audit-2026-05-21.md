# Code Audit — 2026-05-21

**Scope:** Full review pass of `inventory_manager` for refactor candidates, docstrings, naming, dependency health, deprecated patterns, modern platform features. No code changes in this pass — the output is this report.

**Method:** Three parallel exploration agents covered (1) dependencies & Django 6 compatibility, (2) backend Python code quality, (3) templates & frontend. Key claims spot-checked on the main thread.

**Overall verdict:** Backend Python is in good shape after Phases 1–3 (XSS, N+1, dead code, naming all addressed). Two main investment areas remain:

1. **Templates carry ~435 lines of inline JavaScript** across three files — the explicitly-called-out weak area. Extracting these is the highest-leverage refactor available.
2. **`views.py` at 1054 lines has two complexity hotspots** worth splitting (`FilamentSummaryView.get_context_data` at ~145 lines; `Dashboard.get` at ~77 lines).

Several quick wins (5–30 min each) — dead dependencies, missing ARIA labels, env-driven hosts, one N+1 in admin — can be batched into a single "audit cleanup" PR.

---

## 1. Dependencies & Django 6 Compatibility

Django was bumped from `4.2 LTS` to `>=6.0.5,<7.0` via recent dependabot PRs. No deprecated APIs detected in the codebase (`is_ajax`, `force_text`, `ugettext_*`, `NullBooleanField`, `default_app_config`, `USE_L10N` — all clear). `DEFAULT_AUTO_FIELD = BigAutoField`, `USE_TZ=True`, middleware ordering all correct.

### Dead / unused dependencies

| Package | Status | Recommendation |
|---|---|---|
| `pytz==2025.2` | ⚠️ **No imports found.** Django 5+ uses stdlib `zoneinfo` natively. | **Remove from `requirements.txt`.** |
| `six==1.17.0` | ⚠️ **No imports found.** Py2/3 compat shim — obsolete on Python 3.10+. | **Remove.** |
| `typing_extensions==4.15.0` | ⚠️ **No imports found.** Stdlib `typing` covers Py3.10+. | **Remove.** |
| `django-htmx==1.27.0` | ⚠️ Loaded in `base.html` and one HX-Request header check in views — **zero `hx-*` attributes in any template** (verified). | Either remove (~15 KB shipped), or commit to using it (see §3.6). |
| `django-filter==25.2` | ⚠️ `InventoryFilter` is defined at `inventory/views.py:138` but **never instantiated** (verified). | Either wire `InventorySearchView` to use it (recommended — see §2.7) or remove the package and the dead class. |
| `django-extensions>=4.1` | ⚠️ Installed; no `runserver_plus` / `shell_plus` references in code or docs. | Remove unless used interactively in dev. |

### Package health

- ✅ `python-decouple` — fine; `django-environ` is more popular in new projects but no reason to switch.
- 📌 `django-polymorphic==4.11.3` — **Accepted dependency.** Architecture review (see §1a) concluded this is the right fit for the product/inventory model. Slow-moving but tracks Django releases; currently compatible with Django 6.x. Documented exit path exists if it ever stalls.
- 📌 `brother_ql>=0.9.4` — **Accepted risk, no practical alternative.** Brother QL printers use a proprietary raster protocol with no Brother-published Python SDK; `brother_ql` is the canonical reverse-engineered library. The deprecation warning from `brother_ql.devicedependent` is a years-old module-reorganization note that the ecosystem (Home Assistant, label-printing integrations, etc.) universally suppresses. Suppression in `settings.py:22-29` and `barcode_utils.py:25-30` is intentional and should remain. If upstream truly stalls (not just warning noise), migrate to an active community fork — investigate then, not pre-emptively. Only cleanup worth doing: consolidate the two suppression sites into one.
- ✅ `python-barcode`, `openpyxl`, `gunicorn`, `crispy-bootstrap5` — all healthy.

### 1a. Architecture decision: django-polymorphic

The product hierarchy depends heavily on `django-polymorphic` (`Product` → `Filament`/`Printer`/`Hardware`/`Dryer`/`AMS`, with `InventoryItem` referencing the parent). Reviewed against alternatives:

| Alternative | Verdict |
|---|---|
| Multi-Table Inheritance without django-polymorphic | Same schema, worse ergonomics. `django-model-utils.InheritanceManager` is the lightest replacement if needed. |
| Single Table Inheritance (one wide table, mostly NULL) | Bad fit — subclass attribute sets are genuinely different (filament color/family vs. printer bed dimensions). |
| JSONField for type-specific attributes | Loses validation, admin clarity, and queryability. Tempting on Postgres, weak on SQLite. |
| EAV (Entity-Attribute-Value) | Massive over-engineering for this scale. |
| Composition + `GenericForeignKey` (no parent table) | **Already tried and rejected** — migrations 0003/0004 removed `content_type`/`object_id` from `InventoryItem` in favor of polymorphic. Loses unified `Product.objects.filter(upc=...)` queries and shared SKU/UPC namespace. |
| Explicit type FK + one-to-one detail tables | Honest middle ground. Same DB columns as MTI, but no magic. **This is the documented exit path** if django-polymorphic ever becomes unworkable. |

**Decision: stay on django-polymorphic.** The catalog-vs-instance split (`Product` = "SKU exists in the world", `InventoryItem` = "physical thing on a shelf") is the strong part of the design and is independent of the subtyping mechanism. Even if polymorphic ever has to go, that split stays.

### Settings.py

- ⚙ `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` are hardcoded (`settings.py:45-52, 149-160`). Already on the backlog in todo.md; flagged here for completeness.
- ⚠️ `brother_ql` warning suppression is duplicated in two files (`settings.py` and `barcode_utils.py`). Consolidate to one place.

---

## 2. Backend Python Code Quality

`views.py` is the biggest target (1054 lines). After that, `models.py` (734), `barcode_utils.py` (603), `admin.py` (414). Phases 1–3 cleaned up most layer-crossing issues; remaining work is mostly extraction and helper consolidation.

### 2.1 `views.py` complexity hotspots

- **⚠️ `FilamentSummaryView.get_context_data()` — `views.py:624-768` (~145 lines).** Aggregates active inventory, computes depletion stats across three time windows, builds rows, builds material cards with swatches, applies sort. **Split into `_build_active_rows()`, `_add_depletion_stats()`, `_build_material_cards()`.** Known hotspot; was patched in PR #95 but never refactored.
- **⚠️ `Dashboard.get()` — `views.py:772-848` (~77 lines).** Seven independent aggregations: item counts by type, total value, material chart, color chart, inventory by SKU, low-stock alerts, metadata. Candidate for a service module (`services.DashboardDataBuilder`) — improves testability and reuse if Phase 8 charts are added.
- **⚙ `InventoryEditView.post()` — `views.py:230-301` (~72 lines).** Three-tier warning flow (error → needs_ack → info/warning) is implicit. Extract `_handle_location_warning()`.
- **⚙ `AddInventoryView.post()` — `views.py:318-391` (~74 lines).** Print-confirmation logic duplicates `PrintBarcodeView.post()` (lines 107–115). Extract `_render_print_confirmation()`.
- **⚙ `InUseOverviewView` & `DryStorageOverviewView` — `views.py:974-1054`.** ~96% identical — only the status filter differs. Extract a single base method `_build_grouped_items_context(status_filter)`.

### 2.2 `models.py`

- **⚙ `Filament.normalize_hex_code()` — `models.py:112`.** Mutates `self.hex_code` and returns the value. Pure function would be cleaner: return normalized string, let the caller assign. Currently surprises readers.
- **⚙ `Printer.clean()` — `models.py:296-298`.** Single error message when any of three dimensions is missing; doesn't say which. Use a `ValidationError({"bed_length_mm": "…"})` dict so the form highlights the specific field.
- **⚙ `InventoryItem.from_db()` — `models.py:510-514`.** Tracks `_original_location_id` for location-change detection. Sound pattern but needs a one-line docstring — its purpose isn't obvious.
- **⚙ `InventoryItem.filament_drying_warning()` — `models.py:553-609`.** Three nested if/elif chains. Correct but dense; split into `_check_filament_requirements()` + `_check_location_constraints()`.
- **💡 Missing custom QuerySet/Manager on `InventoryItem`.** Adding `.active()`, `.filament()`, `.depleted()` would remove repeated `exclude(status__in=[...])` calls in `FilamentSummaryView`, `Dashboard`, and the overview views. This is the single highest-leverage cleanup in `models.py`.

### 2.3 `admin.py`

- **⚠️ N+1 in `InventoryItemAdmin.display_product_details()` — `admin.py:278-305`.** Calls `obj.product.get_real_instance()` per row. Add `select_related('product__polymorphic_ctype')` to `get_queryset()`. **Quick win.**
- **⚙ Inconsistent `list_display` across child admins.** `FilamentAdmin` and `InventoryItemAdmin` have proper changelist columns; `PrinterAdmin`, `DryerAdmin`, `AMSAdmin` only define `fields` (the form layout). Add `list_display`, `search_fields`, `list_filter` for parity.
- **⚙ `ProductParentAdmin.fields` — `admin.py:209`.** Only shows `sku`, `upc` — but `name`, `price`, `notes` exist on `Product`. Expand to expose all base fields.
- **⚙ `InventoryItemAdmin.get_fields()` — `admin.py:267-276`.** Returns a list containing both a nested list and a scalar. Likely a bug — verify rendering before any other admin work.

### 2.4 `forms.py`

- **⚙ No `BaseProductForm`.** `FilamentForm`, `PrinterForm`, `DryerForm`, `HardwareForm`, `AMSForm` each list `Meta.fields` from scratch. Extract a base form with `['name', 'upc', 'sku', 'price', 'notes']`; subclasses append their specific fields. Small change, real DRY win.

### 2.5 Docstrings — top gaps

The codebase is mostly well-named, so docstrings are only worth adding where intent isn't obvious. Top 5 spots:

1. `InventorySearchView.get()` — explain the INV-prefix regex shortcut.
2. `BulkUpdateView.post()` — document the `_skip_status_from_location` flag.
3. `PrintBarcodeView.get()` — document `mode` parameter values.
4. `InventoryItem.from_db()` — one line on `_original_location_id` purpose.
5. `InventoryItem.update_status()` — when does it return `None`?

### 2.6 Naming

Cleaned up to PascalCase in Phase 3. Two small remaining items:

- **⚙ Hardcoded `[DEPLETED, SOLD]` in `BulkUpdateView` — `views.py:467`.** Promote to a module-level constant `_STATUS_CLEARS_LOCATION`. Same status pair is already implicit in `_ACTIVE_STATUSES` — derive one from the other.
- **⚙ Hardcoded filter keys in `BulkUpdateView._redirect_back()` — `views.py:479-485`.** Module-level `_BULK_FILTER_KEYS` constant; safer when filters are added.

### 2.7 Modern Django patterns

- **⚠️ `InventorySearchView` should be a `FilterView`.** `django-filter` is installed and `InventoryFilter` is defined — wiring them up replaces ~30 lines of manual queryset-building and gives free pagination + URL-driven filter state. Solves the "django-filter unused" finding in §1.
- **⚠️ Admin N+1** — see §2.3.
- **💡 `barcode_utils.py` (603 lines)** — module-level functions are fine for stateless utilities, but splitting into `barcode_utils.rendering`, `barcode_utils.printing`, `barcode_utils.integration` would aid navigation. Lower priority; not blocking anything.

---

## 3. Templates & Frontend

**This is the section James called out as the weakest area, and the audit agrees.** Three templates carry ~435 lines of inline JavaScript and accessibility gaps are easy to fix.

### 3.1 Inline JS — extract to `inventory/static/inventory/js/`

| Template | Inline JS | Recommendation |
|---|---|---|
| `filament_summary.html` | **~220 lines** (filtering, badges, period toggle, DataTables init) | **→ `filament-summary.js`** |
| `inventory_search.html` | **~114 lines** (checkbox state, sticky action bar, DataTables init) | **→ `bulk-actions.js`** |
| `dashboard.html` | **~95 lines** (Chart.js init, filter logic) | **→ `dashboard-charts.js`** with data-attribute config |

Each is self-contained and stateful — externalisation makes them testable and removes the cognitive load of reading 350-line templates.

### 3.2 Inline CSS — print styles are duplicated

- `dashboard.html:150-165` duplicates print styles already in `base.html:14-37`. **Remove the dashboard copy.**
- Inline swatch styles (`width:18px;height:18px;background:#xxx`) repeat across `filament_summary.html`, `dashboard.html`, `filament_color_guide.html`. **Extract to `.color-swatch` class.**

### 3.3 Bootstrap utility chains

Class chains like `class="d-flex flex-wrap gap-3 mb-4 justify-content-center"` appear 4+ times in `filament_summary.html` and again in `dashboard.html`. Extract semantic classes: `.card-grid`, `.filter-bar`, `.stats-row`. Reduces template noise and centralizes layout tweaks.

### 3.4 Accessibility — quick wins

- **⚠️ Icon-only `<button>` in `filament_summary.html:51` (expand-btn)** — no `aria-label`. Add one.
- **⚠️ Select-all checkbox in `inventory_search.html:68`** uses `title` instead of `aria-label`. `aria-label` is more reliable for screen readers.
- **⚠️ Navigation icons in `navigation.html:19, 24`** — text label is correct, but icons need `aria-hidden="true"` to prevent screen-reader double-reads.
- **⚙ `<a>` styled as buttons in `inventory_edit.html:8-13`** — add `role="button"` or convert to `<button>`.

### 3.5 DataTables

Inconsistent initialization: `filament_summary.html` uses the modern `new DataTable(...)` API; `dashboard.html` and `inventory_search.html` use the jQuery-plugin `$(...).DataTable()` form. **Standardize on `new DataTable()`** (also unblocks a future jQuery removal). Common config (paging, pageLength, ordering) should live in a shared `datatable-defaults.js`.

### 3.6 HTMX decision needed

`django-htmx` is installed, loaded in `base.html`, but **zero `hx-*` attributes exist anywhere** (verified). Two paths:

- **Remove it** — saves ~15 KB shipped JS and a dependency. Recommended unless there's a near-term plan to use it.
- **Use it** — natural fits: inline edit in `inventory_edit.html`, live filtering in `filament_summary.html` (replacing the ~80 lines of vanilla filter JS), pagination in `inventory_search.html` (replacing DataTables).

Either is reasonable; the current state of "loaded but unused" is the worst of both.

### 3.7 Modern CSS opportunities

- **CSS Grid for card layouts.** `filament_summary.html` and `dashboard.html` both use `d-flex flex-wrap` for cards. `grid-template-columns: repeat(auto-fit, minmax(180px, 1fr))` is fewer lines, auto-responsive, and centers naturally.
- **`:has()` selector** for print-specific tweaks would eliminate some media-query duplication.

### 3.8 base.html missing `{% block extra_head %}`

Child templates can't inject custom `<link>` or `<style>` into `<head>` without abusing the content block. Add a `{% block extra_head %}{% endblock %}` before `</head>`.

### 3.9 Top 3 templates needing refactor (priority order)

1. **`filament_summary.html`** (352 lines → ~130 after extraction). 220 lines of JS + 4 utility-class chains + swatch styles.
2. **`inventory_search.html`** (295 lines → ~160 after extraction). 114 lines of JS + 8-property inline style on the sticky action bar.
3. **`dashboard.html`** (321 lines → ~240 after extraction). 95 lines of Chart.js + duplicated print CSS + Chart.js config hardcoded.

---

## 4. Prioritized Action Plan

### Quick wins (~30 min total — single "audit cleanup" PR)

- [ ] Remove `pytz`, `six`, `typing_extensions` from `requirements.txt`
- [ ] Remove `django-extensions` (if not used in dev) or document its use
- [ ] Add `select_related('product__polymorphic_ctype')` to `InventoryItemAdmin.get_queryset()`
- [ ] Add `{% block extra_head %}` to `base.html`
- [ ] Remove duplicated print styles from `dashboard.html:150-165`
- [ ] Add `aria-label` / `aria-hidden` to icon-only buttons and decorative icons
- [ ] Decide on HTMX (remove or commit to using) and on `django-filter` (remove or wire up)

### Backend medium refactor (½ day)

- [ ] Split `FilamentSummaryView.get_context_data()` into 3 helpers
- [ ] Add `InventoryItem` custom QuerySet (`.active()`, `.filament()`, `.depleted()`)
- [ ] Extract `BaseProductForm` to DRY form `Meta.fields`
- [ ] Extract shared logic from `InUseOverviewView` / `DryStorageOverviewView`
- [ ] Wire `InventorySearchView` to `FilterView` + `InventoryFilter` (kills two birds: unused filter + manual queryset code)
- [ ] Convert `Filament.normalize_hex_code()` to a pure function
- [ ] Add the 5 docstrings listed in §2.5

### Template extraction (½ day — the big template win)

- [ ] Extract `filament_summary.html` JS → `filament-summary.js`
- [ ] Extract `inventory_search.html` JS → `bulk-actions.js`
- [ ] Extract `dashboard.html` Chart.js → `dashboard-charts.js` (data-attributes for config)
- [ ] Create `inventory/static/inventory/css/layouts.css` with `.card-grid`, `.filter-bar`, `.color-swatch`, `.sticky-action-bar`
- [ ] Standardize DataTables init on `new DataTable(...)` + shared defaults module

### Longer-term (separate phase)

- Split `barcode_utils.py` into submodules
- `Dashboard` view → service module (worth doing when Phase 8 charts arrive)
- CSS Grid migration for card layouts (nice but not urgent)

---

## 5. What's already good (leave alone)

- Phase 1–3 work is solid — XSS surface is closed, wildcard imports gone, signals wired, N+1 mostly addressed, polymorphic admin functional.
- Naming is consistent (PascalCase CBVs, snake_case helpers, `_private` prefix convention).
- `select_related` / `prefetch_related` correctly applied in user-facing views.
- Crispy-forms + Bootstrap 5 setup is clean.
- Migrations are coherent — no schema mess.
- `models.py` `__str__` methods all present.
- Logging config is well-structured.

---

## Appendix: Confidence notes

- HTMX-unused finding: verified by grepping `hx-*` across all templates — zero matches.
- `InventoryFilter` unused: verified — only the class definition matches; no instantiation.
- All file:line references reflect codebase state at commit `fcbe13c` (master). Lines may shift after refactors; verify before editing.
- `django-polymorphic` and `brother_ql` were initially flagged as risks by the subagents; both have since been reviewed and reclassified as accepted dependencies (see §1a and §1 Package health). They are not on the action plan.
