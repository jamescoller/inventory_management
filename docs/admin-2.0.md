# Admin 2.0 — Recommendation (2026-06-09)

The Django admin is the back-office for everything not yet exposed in the app (and the daily
home for `Material` spec entry, location wiring, and the coming procurement/maintenance data).
It's currently **vanilla Django 6.0 admin** — functional but plain. This doc recommends an
upgrade and scopes the lift. Scheduled **last** in the roadmap (Phase 18.1) so it re-skins the
*final* admin surface — including the new procurement/maintenance/telemetry models — exactly
once.

---

## 1. Current state (what we have, and it's more than it looks)
No theme package is installed (`requirements.txt` / `INSTALLED_APPS` have none). But the admin is already meaningfully customized (`inventory/admin.py`, ~520 lines):
- **10 registered models** with real `list_display` / `list_filter` / `search_fields` /
  `fieldsets`.
- **Custom actions:** `bulk_update_material` (separate form view), `mark_depleted`,
  `print_location_labels`.
- **Custom displays:** `status_badge` (HTML + `admin-badges.css`), `display_product_details`
  (polymorphic-aware), `get_product_type`.
- **Custom views/templates:** `view_log` (tails `inventory.log`), the bulk-material form,
  a `change_list` with a status-badge legend, an admin `index` with a Tools section.
- **Polymorphic admin** for the Product tree; `autocomplete_fields`; a custom `unit` picker
  (`formfield_for_foreignkey`) labeling by serial; an `InventoryItemInline`.

The *information* is all there. What's missing is **presentation**: no landing dashboard, dated
list views, weak mobile, generic look.

---

## 2. Recommendation: adopt `django-unfold`

**`django-unfold`** — a modern, Tailwind-based admin theme that's a **drop-in** over the
existing `ModelAdmin` code.

**Why unfold over alternatives:**
- **Drop-in compatibility.** Existing `list_display`/`fieldsets`/actions/`readonly`/
  `autocomplete`/inline code carries over unchanged. `unfold` provides
  `unfold.admin.ModelAdmin` as a base; mostly a base-class + `INSTALLED_APPS` swap (before
  `django.contrib.admin`).
- **Real dashboard.** A configurable admin landing page — surface spend, low-stock, open
  faults, printers-running (ties into the Phase 14–16 data).
- **Responsive / modern.** Genuinely usable on a phone; clean components; dark mode built in.
- **Polymorphic + custom views survive.** The polymorphic admin, `view_log`, and the bulk-form
  view are custom URLs/templates the theme doesn't override (light restyle only).

**Alternatives considered:**
- `django-jazzmin` — AdminLTE look, popular, but heavier/more opinionated and less actively
  aligned with Django 6.0's styling; more template overrides to maintain.
- `django-grappelli` — mature but dated aesthetic; less "2.0".
- Stay vanilla + hand-CSS — lowest dependency, but reinvents what unfold gives for free.


> ℹ️ **James' Feedback** : I really like how `django-unfold` looks! Let's implement that for sure. `django-jazzmin` would be my second choice, but `django-grappelli` is a no - it's too bland. I like `django-unfold` because it has a nice clean polished look, similar to the look of the public site itself. 

---

## 3. Lift estimate (~2–3 hours)
| Task | Effort |
|---|---|
| Add `django-unfold` to `requirements.txt`, register in `INSTALLED_APPS` (before admin) | trivial |
| Swap `admin.ModelAdmin`/`TabularInline` bases to unfold's | low (mechanical) |
| Verify custom displays/actions (`status_badge`, `display_product_details`, the 3 actions) | low |
| Restyle the 3 custom templates (`view_log`, bulk-material, `change_list` legend) | low |
| Build the landing dashboard (cards: spend, low-stock, faults, live printers) | medium |
| Migrate `admin-badges.css` colors → unfold theme tokens / keep as-is | low |

No data migrations. `status_badge`, `display_product_details`, `get_product_type`, fieldsets,
readonly, autocomplete, and the polymorphic parent/child admin all work unchanged.

---

## 4. Before / after
```
 BEFORE (vanilla)                          AFTER (unfold)
 ┌──────────────────────────────┐          ┌───────────────────────────────────────────┐
 │ Django administration        │          │ Inventory · Admin            ☾ dark  👤 jcoller│
 │ INVENTORY                    │          ├───────────┬───────────────────────────────┤
 │  Filaments                   │          │ ▸ Catalog │  $3,140 on hand · 478 spools  │
 │  Inventory items             │          │ ▸ Inventory│  ⚠ 3 low · 1 open fault       │
 │  Locations                   │          │ ▸ Orders  │  🖨 2 printing now             │
 │  Materials                   │          │ ▸ Maint.  │  [ low-stock ] [ recent recv ] │
 │  ...                         │          │ ▸ Telemetry│ clean tables, mobile-friendly │
 └──────────────────────────────┘          └───────────┴───────────────────────────────┘
```

---

## 5. Sequencing note
Do this **after** the procurement (14), maintenance/print-jobs (15), and telemetry (16) admins
exist, so unfold re-skins the complete set once rather than us theming-then-adding-then-
re-theming. It's an independent, low-risk dependency swap that can land whenever 14–16's admins are in place.
