# Audit Quick Wins — 2026-05-22

**Source:** §4 of `docs/code-audit-2026-05-21.md`  
**Branch:** `chore/audit-quick-wins`  
**Scope:** All items in the "Quick wins (~30 min total)" list, plus incidental cleanup found while reading the affected files.

---

## Changes

### 1. Dead dependencies removed from `requirements.txt`

| Package | Reason for removal |
|---|---|
| `pytz==2025.2` | No imports anywhere in the project. Django 5+ uses stdlib `zoneinfo` natively. |
| `six==1.17.0` | Python 2/3 compatibility shim — obsolete on Python 3.10+. No imports found. |
| `typing_extensions==4.15.0` | Stdlib `typing` covers everything needed on Python 3.10+. No imports found. |
| `django-extensions>=4.1` | Listed in `INSTALLED_APPS` but zero usage of `runserver_plus`, `shell_plus`, or any other feature in code or docs. Not documented as a dev-only tool. |
| `django-htmx==1.27.0` | See decision below. |
| `django-filter==25.2` | See decision below. |

### 2. Decision: `django-htmx` — removed Python package, kept htmx CDN

**What changed:** `django-htmx` removed from `requirements.txt` and `INSTALLED_APPS`. The htmx.org CDN `<script>` tag in `base.html` is **unchanged**.

**Why:** The Python package (`django-htmx`) provides the `HtmxMiddleware` and `request.htmx` object. It was in `INSTALLED_APPS` but **not** in `MIDDLEWARE`, so the middleware was never active. The one `HX-Request` header check in `PrintBarcodeView.get()` uses `request.headers.get("HX-Request")` — a raw header lookup that works without the package. Removing the package costs nothing.

The htmx CDN script is retained because Phase 6 plans camera barcode scanning with HTMX (`@zxing/browser` + htmx). When that work begins, add `django_htmx` back to both `INSTALLED_APPS` and `MIDDLEWARE` and switch the header check to `request.htmx`.

### 3. Decision: `django-filter` — removed package and dead class

**What changed:** `django-filter` removed from `requirements.txt` and `INSTALLED_APPS`. The dead `InventoryFilter` class in `views.py` (lines 138–151 pre-edit) and the `import django_filters` at the top of `views.py` were deleted.

**Why:** `InventoryFilter` was defined but never instantiated — verified by grepping for usages (only the class definition matched). The audit §2.7 recommends wiring `InventorySearchView` to `FilterView` as the proper fix, but that is a medium-effort refactor (replaces ~30 lines of manual queryset-building, adds URL-driven filter state). It does not belong in a quick-win PR. The dead class was pure clutter; removing it and the package is the clean choice now. The `FilterView` wiring can be added back in a dedicated refactor PR.

### 4. `InventoryItemAdmin.get_queryset()` — N+1 fix

**File:** `inventory/admin.py`

**What changed:** Added a `get_queryset()` override to `InventoryItemAdmin`:

```python
def get_queryset(self, request):
    return (
        super()
        .get_queryset(request)
        .select_related("product__polymorphic_ctype", "location")
    )
```

**Why:** `display_product_details()` calls `obj.product.get_real_instance()` for every row in the changelist. Without `select_related`, each row triggers an extra `SELECT` on `polymorphic_ctype` to resolve the real type, plus another for `location`. This caused an O(n) query storm on the admin changelist. Added `location` to the `select_related` as well since it appears in `list_display` and would hit the same problem.

### 5. `{% block extra_head %}` added to `base.html`

**File:** `inventory/templates/inventory/base.html`

**What changed:** Added `{% block extra_head %}{% endblock %}` between the stylesheet links and the inline `<style>` block.

**Why:** Child templates had no way to inject `<link>` or `<meta>` tags into `<head>` without abusing the content block. Phase 5 (Filament Guide) and Phase 6 (barcode scanning) will both need this — the guide may need a custom stylesheet and the camera scanning integration may need a `<meta>` permission tag.

### 6. Duplicate print styles removed from `dashboard.html`

**File:** `inventory/templates/inventory/dashboard.html`

**What changed:** Removed the `<style>@media print { … }</style>` block at lines 150–165 (pre-edit).

**Why:** `base.html` already contains an identical `@media print` block covering the same selectors (`nav`, `.btn`, `.dataTables_*`, `canvas`, `body { background: white }`). The dashboard copy added no new rules and was only creating maintenance drift (any print-style change had to be made in two places).

### 7. `aria-hidden="true"` on decorative nav icons

**File:** `inventory/templates/inventory/navigation.html`

**What changed:** Added `aria-hidden="true"` to the Bootstrap icon `<i>` elements for the "Colors" and "Filament" nav links.

**Why:** Both links already have visible text labels ("Colors", "Filament"). The icon elements are purely decorative; without `aria-hidden`, screen readers announce both the icon's implicit name and the text label, producing double-reads like "palette2 Colors".

### 8. `aria-label` on the expand-overflow button in filament cards

**File:** `inventory/templates/inventory/filament_summary.html`

**What changed:** Added `aria-label="Show {{ card.extra_count }} more colors"` to the `expand-btn` button.

**Why:** The button showed only "+N more" as its label with no `aria-label`. Screen readers announced a cryptic "+3 more" with no context. The new label is descriptive and dynamic.

### 9. `aria-label` on the select-all checkbox in `inventory_search.html`

**File:** `inventory/templates/inventory/inventory_search.html`

**What changed:** Changed `title="Select all on this page"` → `aria-label="Select all on this page"` on the `#select-all` checkbox.

**Why:** The `title` attribute surfaces as a tooltip on hover but is unreliable for screen readers. `aria-label` is the correct semantic attribute for an unlabelled control.

---

## Files changed

| File | Change type |
|---|---|
| `requirements.txt` | 6 packages removed |
| `inventory_management_site/settings.py` | 3 apps removed from `INSTALLED_APPS` |
| `inventory/views.py` | `import django_filters` + `InventoryFilter` class deleted |
| `inventory/admin.py` | `get_queryset()` added to `InventoryItemAdmin` |
| `inventory/templates/inventory/base.html` | `{% block extra_head %}` added |
| `inventory/templates/inventory/dashboard.html` | Duplicate print `<style>` block removed |
| `inventory/templates/inventory/navigation.html` | `aria-hidden="true"` on 2 icons |
| `inventory/templates/inventory/filament_summary.html` | `aria-label` on expand button |
| `inventory/templates/inventory/inventory_search.html` | `title` → `aria-label` on select-all checkbox |
| `todo.md` | Quick wins marked complete; decisions documented |

---

## What was NOT done (intentionally)

- **`InventorySearchView` → `FilterView` wiring** — Audit §2.7 recommends this but it is a medium refactor. Removed `django-filter` now; add it back when the refactor PR is written.
- **`django-htmx` middleware** — The CDN script stays. Add the Python package back (and wire the middleware) when Phase 6 HTMX work begins.
- **Brother QL warning consolidation** — Audit §1 notes the suppression is duplicated in `settings.py` and `barcode_utils.py`. Left alone: it is a one-liner in each file and consolidating it requires deciding which file "owns" logging config, which is a design choice not a quick win.
