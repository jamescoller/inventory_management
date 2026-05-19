# Bulk Inventory Editor — Design Spec

**Date:** 2026-05-19  
**Branch:** feat/bulk-editor (to be created)  
**Status:** Approved, ready for implementation

---

## Problem

Keeping the DB current requires marking many items (e.g. a batch of depleted filament spools) one at a time via the existing single-item edit view. There is no way to act on multiple items at once.

---

## Scope

Extend the existing Search Inventory page with:
- Checkboxes to select items from search results
- A sticky action bar to apply a single value to all selected items for: **status**, **location**, and/or **shipment**
- A `BulkUpdateView` to process the POST and redirect back to the same filtered view

No new model, no migration, no new form class.

---

## Fields available for bulk update

| Field | Input type | "No change" sentinel |
|---|---|---|
| `status` | `<select>` with `InventoryItem.Status` choices | `""` (empty string) |
| `location` | `<select>` with all `Location` objects | `""` (empty string) |
| `shipment` | `<input type="text">` | `""` (empty string) |

`percent_remaining` is excluded — values differ per spool.

---

## URL & View

```
POST /bulk-update/   name="bulk_update"
```

`BulkUpdateView(LoginRequiredMixin, View)` — POST only. GET redirects to `inventory_search`.

### Validation

- `item_ids`: required, non-empty list of integers. Unknown IDs silently skipped (no 404).
- `status`: must be a valid `InventoryItem.Status` integer value if provided.
- `location`: must be a valid `Location` pk if provided.
- If all three fields are blank/empty, redirect back with a `messages.warning`: *"No fields selected — nothing was changed."*

### Update logic

Wrapped in `transaction.atomic()`. Iterates (never `queryset.update()`) to preserve `save()` side-effects — specifically `date_depleted`, `date_sold`, and location-change signal behaviour established in Phase 2/3:

```python
with transaction.atomic():
    for item in InventoryItem.objects.filter(id__in=validated_ids):
        status_clears_location = False
        if new_status == Status.DEPLETED:
            item.mark_depleted()       # sets date_depleted, location=None
            status_clears_location = True
        elif new_status == Status.SOLD:
            item.mark_sold()           # sets date_sold, location=None
            status_clears_location = True
        elif new_status is not None:
            item.status = new_status
        # Don't re-assign location if mark_depleted/mark_sold just cleared it
        if new_location is not None and not status_clears_location:
            item.location = new_location
        if shipment is not None:
            item.shipment = shipment
        item.save()
```

### Redirect

After update, redirect to `/search/` with the original filter query params preserved (passed as hidden inputs in the form). Django `messages.success`: *"Updated N items."*

---

## Search page changes (`inventory_search.html`)

### Table

- Add a checkbox column as the leftmost column.
- Header checkbox: selects/deselects all rows on the **current DataTables page only**.
- Each row's checkbox carries `data-id="{{ item.id }}"`.

### DataTables config

Add `lengthMenu` option:

```js
lengthMenu: [[25, 50, 100, -1], [25, 50, 100, "All"]],
pageLength: 25,
```

To select all items for a bulk action, the user sets pagination to "All" then uses Select All.

### JS selection tracking

A single `selectedIds = new Set()` is the source of truth. DOM checkboxes reflect it; they are never read directly.

**Interactions:**

| Event | Effect |
|---|---|
| Row checkbox clicked | Add/remove `item.id` from `selectedIds` → `syncUI()` |
| Header "Select All" clicked | Add/remove all current-page IDs → `syncUI()` |
| DataTables redraw (`draw.dt`) | Re-check checkboxes for IDs in Set; update header checkbox state |
| Clear button clicked | `selectedIds.clear()` → uncheck all visible → hide action bar |
| Apply button clicked | Write one hidden `<input name="item_ids">` per ID, submit form |

**`syncUI()`** — called after every Set mutation:
1. Show/hide action bar (`selectedIds.size > 0`)
2. Update button label: `"Apply to N items"`
3. Set header checkbox: checked (all on page selected), indeterminate (some), or unchecked

### Action bar

`position: sticky; bottom: 0` — visible only when `selectedIds.size > 0`.

Contains:
- Selected count label: *"N items selected"*
- Status `<select>` (default: `""` / "— no change —")
- Location `<select>` (default: `""` / "— no change —")
- Shipment `<input type="text">` (default: empty)
- **"Apply to N items"** submit button (label updates with count)
- **"Clear"** button

The action bar is a `<form method="POST" action="{% url 'bulk_update' %}">` with:
- CSRF token
- Hidden inputs for selected IDs (written by JS on submit)
- Hidden inputs for current filter params (`sku`, `upc`, `name`, `status`, `location`, `serial_number`, `item_id`) so the redirect lands on the same filtered view

---

## Files to change

| File | Change |
|---|---|
| `inventory/urls.py` | Add `path("bulk-update/", BulkUpdateView.as_view(), name="bulk_update")` |
| `inventory/views.py` | Add `BulkUpdateView` |
| `inventory/templates/inventory/inventory_search.html` | Checkbox column, DataTables lengthMenu, action bar, JS Set logic |

---

## Out of scope

- Bulk delete (no delete capability in this app)
- Bulk `percent_remaining` edit
- Confirmation modal (the explicit "Apply to N items" label is sufficient)
- Pagination across pages in a single "select all" action (use "All" page size instead)
