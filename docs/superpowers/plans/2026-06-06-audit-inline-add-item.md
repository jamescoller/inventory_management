# Inline "Add Item" During Inventory Audit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the audit scan stream handle untracked spools — in-catalog UPCs mint an `InventoryItem` at the active location immediately; unknown UPCs queue to a durable model reviewed post-walk at `/audit/unknowns/`.

**Architecture:** Extend `parse_code()` so a bare-numeric scan is a UPC. A new `audit.add_or_queue_upc()` service either creates the item (catalog hit, logging a new `AuditEvent.Action.ADDED`) or records an `AuditUnknownScan` row. `AuditScanView` dispatches UPC scans and does the label print (logic in `audit.py`, I/O in the view — mirroring `AddInventoryView`). A dedicated review page hands queued UPCs into the existing `pending_inventory` → add-product flow, threading an `unknown_scan_id` so item creation marks the queue row resolved.

**Tech Stack:** Django 6.0, SQLite, HTMX, django-crispy-forms/bootstrap5, `brother_ql` label printing.

**Spec:** `docs/superpowers/specs/2026-06-06-audit-inline-add-item-design.md`

**Branch:** `feat/audit-inline-add-item` (already created off `master`, spec committed).

**Validation runner:** `~/.venvs/inventory/bin/python` (alias `PY` below). Run from repo root.

---

## File Structure

- **`inventory/models.py`** — add `AuditEvent.Action.ADDED`; add `AuditUnknownScan` model.
- **`inventory/migrations/0027_audit_unknown_scan.py`** — generated, additive.
- **`inventory/audit.py`** — `parse_code` UPC kind; `ADDED` in `PRESENT_ACTIONS`; `add_or_queue_upc()`.
- **`inventory/views.py`** — `AuditScanView` UPC dispatch + print; `_audit_context` `added` tally + `unknown_count`; `AuditUnknownsView`/`AuditUnknownResolveView`/`AuditUnknownDismissView`; `_resolve_pending_unknown` helper wired into the two `pending_inventory` consumers.
- **`inventory/urls.py`** — 3 new `/audit/unknowns/...` routes.
- **`inventory/templates/inventory/audit_unknowns.html`** — review page (new).
- **`inventory/templates/inventory/partials/audit_body.html`** — "Added" stat card + "Unknowns (N)" badge.
- **`inventory/templates/inventory/audit_finalize.html`** — queued-unknowns note.
- **`inventory/admin.py`** — `AuditUnknownScanAdmin` (visibility).
- **`inventory/tests.py`** — new tests appended to existing audit test classes / new classes.

---

## Task 1: Model + migration — `AuditUnknownScan` and `AuditEvent.Action.ADDED`

**Files:**
- Modify: `inventory/models.py` (AuditEvent.Action ~line 885; new model after `AuditEvent` ~line 909)
- Create: `inventory/migrations/0027_audit_unknown_scan.py` (generated)
- Test: `inventory/tests.py` (new class `AuditUnknownScanModelTests`)

- [ ] **Step 1: Write the failing test**

Append to `inventory/tests.py` (it already imports `AuditEvent, AuditSession` at line 532; add `AuditUnknownScan` to that import line, and ensure `Location`, `InventoryItem`, `Filament`, `User` are imported — they are, used by existing audit tests):

```python
class AuditUnknownScanModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="uq", password="pass")
        self.loc = Location.objects.create(
            name="Q1", kind=Location.Kind.SHELF,
            default_status=InventoryItem.Status.NEW,
        )

    def test_create_and_defaults(self):
        session = AuditSession.objects.create(user=self.user)
        scan = AuditUnknownScan.objects.create(
            session=session, upc="111222333444", location=self.loc
        )
        self.assertFalse(scan.resolved)
        self.assertFalse(scan.dismissed)
        self.assertIsNone(scan.resolved_item)
        self.assertIsNotNone(scan.created_at)

    def test_added_action_exists(self):
        self.assertEqual(AuditEvent.Action.ADDED, "added")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.AuditUnknownScanModelTests -v2`
Expected: FAIL — `ImportError`/`AttributeError` (`AuditUnknownScan` and `AuditEvent.Action.ADDED` don't exist).

- [ ] **Step 3: Add the `ADDED` action**

In `inventory/models.py`, in `class AuditEvent` → `class Action(models.TextChoices)`, add after `CLOSED`:

```python
        CLOSED = "closed", "Location closed"
        ADDED = "added", "Added during audit"
```

- [ ] **Step 4: Add the `AuditUnknownScan` model**

In `inventory/models.py`, immediately after the `AuditEvent` class (after its `__str__`, ~line 909):

```python
class AuditUnknownScan(models.Model):
    """A UPC scanned during an audit that matched no catalog Product.

    Captured at the active location and queued for post-walk review at
    ``/audit/unknowns/``, where it is handed into the normal add-product flow.
    """

    session = models.ForeignKey(
        AuditSession, on_delete=models.CASCADE, related_name="unknown_scans"
    )
    upc = models.CharField(max_length=64)
    location = models.ForeignKey(
        "Location", on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)
    resolved_item = models.ForeignKey(
        "InventoryItem", on_delete=models.SET_NULL, null=True, blank=True
    )
    dismissed = models.BooleanField(default=False)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"UPC {self.upc} @ {self.location_id} ({'open' if not (self.resolved or self.dismissed) else 'closed'})"
```

- [ ] **Step 5: Generate the migration**

Run: `~/.venvs/inventory/bin/python manage.py makemigrations inventory --name audit_unknown_scan`
Expected: creates `inventory/migrations/0027_audit_unknown_scan.py` adding the model + the `ADDED` choice. Confirm it depends on `0026_backfill_location_kind`.

- [ ] **Step 6: Run tests + migration check**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.AuditUnknownScanModelTests -v2 && ~/.venvs/inventory/bin/python manage.py makemigrations --dry-run --check`
Expected: tests PASS; "No changes detected".

- [ ] **Step 7: Commit**

```bash
git add inventory/models.py inventory/migrations/0027_audit_unknown_scan.py inventory/tests.py
git commit -m "feat: AuditUnknownScan model + AuditEvent.ADDED action for audit inline-add"
```

---

## Task 2: `audit.py` — UPC parsing, present-immunity, `add_or_queue_upc`

**Files:**
- Modify: `inventory/audit.py` (imports ~line 25; `PRESENT_ACTIONS` line 38; `parse_code` lines 45-57; new service after `scan_item`)
- Test: `inventory/tests.py` (new class `AuditAddOrQueueTests`)

- [ ] **Step 1: Write the failing tests**

Append to `inventory/tests.py`:

```python
class AuditAddOrQueueTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="aq", password="pass")
        self.shelf = Location.objects.create(
            name="AQ1", kind=Location.Kind.SHELF,
            default_status=InventoryItem.Status.NEW,
        )
        self.rack = Location.objects.create(name="Rack", kind=Location.Kind.RACK)
        self.product = Filament.objects.create(name="PLA Q", upc="600000000001")

    def test_parse_code_upc(self):
        self.assertEqual(audit.parse_code("600000000001"), ("upc", "600000000001"))
        self.assertEqual(audit.parse_code("LOC-5"), ("loc", 5))
        self.assertEqual(audit.parse_code("INV-12"), ("item", 12))
        with self.assertRaises(audit.AuditError):
            audit.parse_code("not-a-code")

    def test_in_catalog_creates_item_present_immune(self):
        session = audit.start_session(self.user)
        outcome, obj = audit.add_or_queue_upc(session, self.shelf, "600000000001")
        self.assertEqual(outcome, "added")
        self.assertEqual(obj.product_id, self.product.id)
        self.assertEqual(obj.location_id, self.shelf.id)
        self.assertTrue(
            AuditEvent.objects.filter(
                session=session, item=obj, action=AuditEvent.Action.ADDED
            ).exists()
        )
        # Present-immune: closing the location must NOT flag the just-added item.
        audit.close_location(session, self.shelf)
        obj.refresh_from_db()
        self.assertNotEqual(obj.status, InventoryItem.Status.UNKNOWN)

    def test_unknown_upc_queues(self):
        session = audit.start_session(self.user)
        outcome, obj = audit.add_or_queue_upc(session, self.shelf, "999888777666")
        self.assertEqual(outcome, "queued")
        self.assertEqual(obj.upc, "999888777666")
        self.assertEqual(obj.location_id, self.shelf.id)
        self.assertFalse(obj.resolved)

    def test_unknown_upc_dedup(self):
        session = audit.start_session(self.user)
        audit.add_or_queue_upc(session, self.shelf, "999888777666")
        audit.add_or_queue_upc(session, self.shelf, "999888777666")
        self.assertEqual(
            AuditUnknownScan.objects.filter(
                session=session, upc="999888777666", location=self.shelf
            ).count(),
            1,
        )

    def test_no_active_location_raises(self):
        session = audit.start_session(self.user)
        with self.assertRaises(audit.AuditError):
            audit.add_or_queue_upc(session, None, "600000000001")

    def test_container_location_raises(self):
        session = audit.start_session(self.user)
        with self.assertRaises(audit.AuditError):
            audit.add_or_queue_upc(session, self.rack, "600000000001")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.AuditAddOrQueueTests -v2`
Expected: FAIL — `add_or_queue_upc` undefined; `parse_code("600...")` raises instead of returning `("upc", ...)`.

- [ ] **Step 3: Extend imports + `PRESENT_ACTIONS`**

In `inventory/audit.py`, add `AuditUnknownScan` and `Product` to the `from .models import (...)` block:

```python
from .models import (
    AMS,
    AuditEvent,
    AuditSession,
    AuditUnknownScan,
    Dryer,
    InventoryItem,
    Location,
    Printer,
    Product,
)
```

Change `PRESENT_ACTIONS` (line 38) so a just-added item counts as accounted-for:

```python
# Actions that mean "the item was physically accounted for at a location".
PRESENT_ACTIONS = (
    AuditEvent.Action.SCANNED_PRESENT,
    AuditEvent.Action.MOVED_IN,
    AuditEvent.Action.ADDED,
)
```

- [ ] **Step 4: Extend `parse_code` to recognise bare UPCs**

Replace the final `raise` in `parse_code` (line 57) so a bare-numeric falls through to a UPC:

```python
def parse_code(raw):
    """Classify a scanned string -> ``("loc"|"item"|"upc", value)``.

    ``LOC-``/``INV-`` carry an int pk; a bare-numeric scan is a manufacturer UPC
    (returned as a string). Raises :class:`AuditError` for anything else.
    """
    code = (raw or "").strip().upper()
    for prefix, kind in (("LOC-", "loc"), ("INV-", "item")):
        if code.startswith(prefix):
            rest = code[len(prefix) :]
            if rest.isdigit():
                return kind, int(rest)
            raise AuditError(f"Malformed code: {raw!r}")
    if code.isdigit():
        return "upc", code
    raise AuditError(f"Unrecognized code {raw!r}. Expected LOC-…, INV-…, or a UPC.")
```

- [ ] **Step 5: Add the `add_or_queue_upc` service**

In `inventory/audit.py`, after `scan_item` (before `close_location`, ~line 145):

```python
def add_or_queue_upc(session, location, upc):
    """Reconcile an untracked-spool UPC scan against the active location.

    Catalog hit -> create an :class:`InventoryItem` here, log ``ADDED``, return
    ``("added", item)``. Catalog miss -> queue an :class:`AuditUnknownScan`
    (deduped on session+upc+location) and return ``("queued", scan)``.

    The caller (view) is responsible for label printing on the ``added`` branch.
    """
    if location is None:
        raise AuditError("Scan a location barcode first.")
    if location.is_container:
        raise AuditError(f"{location.name} is a container, not a storage spot.")

    product = Product.objects.filter(upc=upc).first()
    if product is None:
        scan, _ = AuditUnknownScan.objects.get_or_create(
            session=session,
            upc=upc,
            location=location,
            resolved=False,
            dismissed=False,
        )
        return "queued", scan

    item = InventoryItem(product=product, location=location)
    new_status = item.update_status()
    if new_status:
        item.status = new_status
    item._skip_status_from_location = True  # status set explicitly above
    item.save()
    AuditEvent.objects.create(
        session=session, item=item, location=location, action=AuditEvent.Action.ADDED
    )
    return "added", item
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.AuditAddOrQueueTests -v2`
Expected: PASS (6 tests).

- [ ] **Step 7: Commit**

```bash
git add inventory/audit.py inventory/tests.py
git commit -m "feat: add_or_queue_upc audit service + UPC parsing + ADDED present-immunity"
```

---

## Task 3: `AuditScanView` UPC dispatch + print, and `_audit_context` tally

**Files:**
- Modify: `inventory/views.py` (`AuditScanView.post` ~lines 350-405; `_audit_context` lines 1140-1184)
- Test: `inventory/tests.py` (new class `AuditScanUpcViewTests`)

- [ ] **Step 1: Write the failing tests**

Append to `inventory/tests.py`:

```python
class AuditScanUpcViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        User.objects.create_user(username="su", password="pass")
        self.client.login(username="su", password="pass")
        self.shelf = Location.objects.create(
            name="SU1", kind=Location.Kind.SHELF,
            default_status=InventoryItem.Status.NEW,
        )
        self.product = Filament.objects.create(name="PLA SU", upc="700000000001")
        self.client.post(reverse("audit_start"))
        self.client.post(reverse("audit_scan"), {"code": f"LOC-{self.shelf.pk}"})

    def test_scan_in_catalog_upc_creates_item(self):
        before = InventoryItem.objects.count()
        resp = self.client.post(
            reverse("audit_scan"), {"code": "700000000001"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(InventoryItem.objects.count(), before + 1)

    def test_scan_unknown_upc_queues(self):
        resp = self.client.post(
            reverse("audit_scan"), {"code": "123123123123"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            AuditUnknownScan.objects.filter(upc="123123123123").count(), 1
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.AuditScanUpcViewTests -v2`
Expected: FAIL — bare-numeric currently raises `AuditError`, so no item/scan is created (counts unchanged).

- [ ] **Step 3: Add the UPC branch to `AuditScanView.post`**

In `inventory/views.py`, inside `AuditScanView.post`, the `try` block dispatches on `kind`. Add a `kind == "upc"` branch alongside the existing `loc`/`item` handling. The existing structure is:

```python
            kind, pk = audit.parse_code(request.POST.get("code", ""))
            if kind == "loc":
                ...
            else:  # item
                ...
```

Replace the `kind, pk = ...` unpacking and the `if/else` with a three-way dispatch (note `parse_code` now returns a str for UPC, so don't unpack into `pk` unconditionally):

```python
            kind, value = audit.parse_code(request.POST.get("code", ""))
            if kind == "loc":
                location = Location.objects.filter(pk=value).first()
                if location is None:
                    raise audit.AuditError(f"No location with id {value}.")
                audit.visit_location(session, location, previous_location=active)
                _set_active_location(request, location)
                active = location
                last_result = ("info", f"At {location.name}.")
            elif kind == "upc":
                outcome, obj = audit.add_or_queue_upc(session, active, value)
                if outcome == "added":
                    try:
                        generate_and_print_barcode(obj, mode="unique")
                    except Exception as e:  # label print is non-fatal
                        messages.warning(request, f"Label printing failed: {e}")
                        logger.error(f"Label printing failed: {e}")
                    last_result = (
                        "success",
                        f"Added {obj.product.name} (INV-{obj.pk}).",
                    )
                else:  # queued
                    last_result = (
                        "warning",
                        f"Unknown UPC {value} queued for review.",
                    )
            else:  # item
                item = InventoryItem.objects.filter(pk=value).first()
                if item is None:
                    raise audit.AuditError(f"No item with id {value}.")
                action = audit.scan_item(session, active, item)
                labels = {
                    AuditEvent.Action.SCANNED_PRESENT: ("success", "Present"),
                    AuditEvent.Action.MOVED_IN: ("success", "Moved here"),
                    AuditEvent.Action.REVIVED: ("warning", "Revived here"),
                }
                tag, verb = labels[action]
                last_result = (tag, f"{verb}: {item.product.name} (INV-{item.pk}).")
```

Confirm `generate_and_print_barcode` is already imported in `views.py` (it is — used by `AddInventoryView`). If not, add `from .barcode_utils import generate_and_print_barcode`.

- [ ] **Step 4: Add `added` tally + `unknown_count` to `_audit_context`**

In `inventory/views.py` `_audit_context`, inside the returned `"tally"` dict add an `added` count, and add a top-level `unknown_count`. In the `tally` dict (after `closed`):

```python
            "closed": AuditEvent.objects.filter(
                session=session, action=AuditEvent.Action.CLOSED
            ).count(),
            "added": AuditEvent.objects.filter(
                session=session, action=AuditEvent.Action.ADDED
            ).count(),
```

And in the returned dict (after `"unknown_items": ...`):

```python
        "unknown_count": AuditUnknownScan.objects.filter(
            resolved=False, dismissed=False
        ).count(),
```

Ensure `AuditUnknownScan` is imported at the top of `views.py` (add to the existing `from .models import (...)` block alongside `AuditEvent`, `AuditSession`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.AuditScanUpcViewTests -v2`
Expected: PASS (2 tests). Label printing is stubbed in test mode (see existing `[TEST MODE] Skipping actual label print` log).

- [ ] **Step 6: Commit**

```bash
git add inventory/views.py inventory/tests.py
git commit -m "feat: dispatch UPC scans in AuditScanView; added/unknown tallies"
```

---

## Task 4: Review page — views, urls, template

**Files:**
- Modify: `inventory/views.py` (new CBVs near the other audit views, after `AuditAbandonView`)
- Modify: `inventory/urls.py` (after the `audit/abandon/` route, line 93)
- Create: `inventory/templates/inventory/audit_unknowns.html`
- Test: `inventory/tests.py` (new class `AuditUnknownsPageTests`)

- [ ] **Step 1: Write the failing tests**

Append to `inventory/tests.py`:

```python
class AuditUnknownsPageTests(TestCase):
    def setUp(self):
        self.client = Client()
        User.objects.create_user(username="up", password="pass")
        self.client.login(username="up", password="pass")
        self.loc = Location.objects.create(
            name="UP1", kind=Location.Kind.SHELF,
            default_status=InventoryItem.Status.NEW,
        )
        self.session = AuditSession.objects.create()
        self.scan = AuditUnknownScan.objects.create(
            session=self.session, upc="555000111000", location=self.loc
        )

    def test_list_shows_open_only(self):
        resolved = AuditUnknownScan.objects.create(
            session=self.session, upc="000", location=self.loc, resolved=True
        )
        resp = self.client.get(reverse("audit_unknowns"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "555000111000")
        self.assertNotContains(resp, ">000<")

    def test_dismiss_hides(self):
        self.client.post(reverse("audit_unknown_dismiss", args=[self.scan.pk]))
        self.scan.refresh_from_db()
        self.assertTrue(self.scan.dismissed)

    def test_resolve_sets_pending_inventory(self):
        resp = self.client.post(
            reverse("audit_unknown_resolve", args=[self.scan.pk])
        )
        self.assertEqual(resp.status_code, 302)
        pending = self.client.session["pending_inventory"]
        self.assertEqual(pending["upc"], "555000111000")
        self.assertEqual(pending["location_id"], self.loc.id)
        self.assertEqual(pending["unknown_scan_id"], self.scan.id)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.AuditUnknownsPageTests -v2`
Expected: FAIL — `NoReverseMatch` for `audit_unknowns`/`audit_unknown_dismiss`/`audit_unknown_resolve`.

- [ ] **Step 3: Add the three CBVs**

In `inventory/views.py`, after `AuditAbandonView`:

```python
class AuditUnknownsView(LoginRequiredMixin, TemplateView):
    """Post-walk review of UPCs that matched no catalog Product."""

    template_name = "inventory/audit_unknowns.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["scans"] = (
            AuditUnknownScan.objects.filter(resolved=False, dismissed=False)
            .select_related("location")
            .order_by("created_at")
        )
        return context


class AuditUnknownResolveView(LoginRequiredMixin, View):
    """Hand a queued UPC into the existing add-product flow, threading the scan id
    so item creation marks this queue row resolved (see _resolve_pending_unknown)."""

    def post(self, request, pk):
        scan = get_object_or_404(
            AuditUnknownScan, pk=pk, resolved=False, dismissed=False
        )
        request.session["pending_inventory"] = {
            "upc": scan.upc,
            "sku": "",
            "shipment": None,
            "location_id": scan.location_id,
            "unknown_scan_id": scan.id,
        }
        messages.info(
            request, f"Add the product for UPC {scan.upc}, then it returns here."
        )
        return redirect("add_product_choice")


class AuditUnknownDismissView(LoginRequiredMixin, View):
    def post(self, request, pk):
        scan = get_object_or_404(AuditUnknownScan, pk=pk)
        scan.dismissed = True
        scan.save(update_fields=["dismissed"])
        messages.info(request, f"Dismissed UPC {scan.upc}.")
        return redirect("audit_unknowns")
```

Confirm `get_object_or_404` is imported in `views.py` (it is widely used; if not, add `from django.shortcuts import get_object_or_404`).

- [ ] **Step 4: Add the routes**

In `inventory/urls.py`, after the `audit/abandon/` path (line 93):

```python
    path("audit/unknowns/", AuditUnknownsView.as_view(), name="audit_unknowns"),
    path(
        "audit/unknowns/<int:pk>/resolve/",
        AuditUnknownResolveView.as_view(),
        name="audit_unknown_resolve",
    ),
    path(
        "audit/unknowns/<int:pk>/dismiss/",
        AuditUnknownDismissView.as_view(),
        name="audit_unknown_dismiss",
    ),
```

Add `AuditUnknownsView, AuditUnknownResolveView, AuditUnknownDismissView` to the existing `from .views import (...)` block (alongside `AuditAbandonView` etc.).

- [ ] **Step 5: Create the template**

Create `inventory/templates/inventory/audit_unknowns.html`:

```django
{% extends "inventory/base.html" %}

{% block content %}
<div class="container py-3">
  <h1 class="mb-3"><i class="bi bi-upc-scan"></i> Unknown UPCs</h1>
  <p class="text-muted">
    Spools scanned during an audit whose UPC matched no product in the catalog.
    Add each one (it pre-fills the add-product form with the UPC and location), or
    dismiss a mis-scan.
  </p>

  {% if scans %}
    <table class="table align-middle">
      <thead>
        <tr><th>UPC</th><th>Location</th><th>Scanned</th><th class="text-end">Actions</th></tr>
      </thead>
      <tbody>
        {% for scan in scans %}
          <tr>
            <td><code>{{ scan.upc }}</code></td>
            <td>{{ scan.location.name|default:"—" }}</td>
            <td>{{ scan.created_at|date:"Y-m-d H:i" }}</td>
            <td class="text-end">
              <form class="d-inline" method="post"
                    action="{% url 'audit_unknown_resolve' scan.pk %}">
                {% csrf_token %}
                <button class="btn btn-sm btn-primary" type="submit">
                  <i class="bi bi-plus-circle"></i> Add to inventory
                </button>
              </form>
              <form class="d-inline" method="post"
                    action="{% url 'audit_unknown_dismiss' scan.pk %}">
                {% csrf_token %}
                <button class="btn btn-sm btn-outline-secondary" type="submit">
                  Dismiss
                </button>
              </form>
            </td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  {% else %}
    <div class="alert alert-success">No unknown UPCs to review.</div>
  {% endif %}

  <a class="btn btn-outline-secondary" href="{% url 'audit_console' %}">
    <i class="bi bi-arrow-left"></i> Back to audit
  </a>
</div>
{% endblock content %}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.AuditUnknownsPageTests -v2`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add inventory/views.py inventory/urls.py inventory/templates/inventory/audit_unknowns.html inventory/tests.py
git commit -m "feat: /audit/unknowns review page (list, resolve handoff, dismiss)"
```

---

## Task 5: Close the resolution loop — `_resolve_pending_unknown`

**Files:**
- Modify: `inventory/views.py` (`AddInventoryView.post` item-create ~line 376; `AddInventoryView` GET/`get_initial`; `BaseAddProductView.form_valid` ~line 933; new helper)
- Test: `inventory/tests.py` (new class `AuditResolveLoopTests`)

- [ ] **Step 1: Write the failing tests**

Append to `inventory/tests.py`:

```python
class AuditResolveLoopTests(TestCase):
    def setUp(self):
        self.client = Client()
        User.objects.create_user(username="rl", password="pass")
        self.client.login(username="rl", password="pass")
        self.loc = Location.objects.create(
            name="RL1", kind=Location.Kind.SHELF,
            default_status=InventoryItem.Status.NEW,
        )
        self.session = AuditSession.objects.create()
        self.scan = AuditUnknownScan.objects.create(
            session=self.session, upc="800000000001", location=self.loc
        )

    def test_in_catalog_add_marks_resolved(self):
        # Product now exists in the catalog (added since the scan).
        Filament.objects.create(name="PLA RL", upc="800000000001")
        # Resolve handoff stashes pending_inventory incl. unknown_scan_id.
        self.client.post(reverse("audit_unknown_resolve", args=[self.scan.pk]))
        # The matched-product path of AddInventoryView creates the item.
        self.client.post(reverse("add_inventory"), {"upc": "800000000001"})
        self.scan.refresh_from_db()
        self.assertTrue(self.scan.resolved)
        self.assertIsNotNone(self.scan.resolved_item)
        self.assertEqual(self.scan.resolved_item.product.upc, "800000000001")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.AuditResolveLoopTests -v2`
Expected: FAIL — `scan.resolved` stays `False` (no resolution hook yet).

- [ ] **Step 3: Add the helper**

In `inventory/views.py`, near the other audit helpers (`_active_location` ~line 1121):

```python
def _resolve_pending_unknown(request, item):
    """If the current pending_inventory carries an unknown_scan_id, mark that
    AuditUnknownScan resolved against the freshly created item. No-op otherwise."""
    pending = request.session.get("pending_inventory") or {}
    scan_id = pending.get("unknown_scan_id")
    if not scan_id:
        return
    AuditUnknownScan.objects.filter(pk=scan_id, resolved=False).update(
        resolved=True, resolved_item=item
    )
```

- [ ] **Step 4: Wire it into the matched-product path (`AddInventoryView.post`)**

In `inventory/views.py` `AddInventoryView.post`, right after the `new_item = InventoryItem.objects.create(...)` (line 376-380) and before the barcode print, add:

```python
        new_item = InventoryItem.objects.create(
            product=product,
            shipment=shipment,
            location=location,
        )
        _resolve_pending_unknown(request, new_item)
```

Note: `AddInventoryView.post` builds the form from `request.POST`; `location` comes from the posted form. The resolve handoff stores `location_id` in `pending_inventory` but does **not** auto-fill the form's location — that's fine for the test (UPC match path creates the item regardless of location). The `unknown_scan_id` is read straight from the session by the helper.

- [ ] **Step 5: Wire it into the new-product path (`BaseAddProductView.form_valid`)**

In `inventory/views.py` `BaseAddProductView.form_valid` (line 933-939), the item is created from popped `pending`. Add the resolve call using that popped dict (the helper reads the session, which is already popped here, so pass the scan id explicitly via a small inline update instead):

```python
        if self.request.GET.get("from_inventory"):
            pending = self.request.session.pop("pending_inventory", None)
            if pending:
                new_item = InventoryItem.objects.create(
                    product=self.object,
                    shipment=pending.get("shipment"),
                    location_id=pending.get("location_id"),
                )
                scan_id = pending.get("unknown_scan_id")
                if scan_id:
                    AuditUnknownScan.objects.filter(
                        pk=scan_id, resolved=False
                    ).update(resolved=True, resolved_item=new_item)
                messages.success(
                    self.request, f"{self.object.name} and inventory item created."
                )
                return redirect("add_inventory")
```

(Here the session was already popped, so we use the local `pending` dict rather than `_resolve_pending_unknown`, which reads the session.)

- [ ] **Step 6: Pop a stale `unknown_scan_id` on a fresh add_inventory GET**

To avoid a stale scan id binding to an unrelated later add, clear it when the auditor lands on the add_inventory form fresh (not arriving from the resolve handoff). In `AddInventoryView.get_initial` (line 321), add at the top:

```python
    def get_initial(self):
        initial = super().get_initial()
        # Drop a stale unknown_scan_id if the user navigated here directly.
        pending = self.request.session.get("pending_inventory")
        if pending and "unknown_scan_id" in pending and not self.request.GET.get("upc"):
            pending.pop("unknown_scan_id", None)
            self.request.session["pending_inventory"] = pending
        if InventoryItem.objects.exists():
            latest = InventoryItem.objects.order_by("-id").first()
            initial["shipment"] = latest.shipment
            initial["location"] = latest.location
        return initial
```

(The resolve handoff redirects to `add_product_choice`, not `add_inventory`, so the matched-product test path posts directly to `add_inventory` without a GET; this guard only fires on an explicit no-`upc` GET visit and won't strip the id mid-handoff.)

- [ ] **Step 7: Run tests to verify they pass**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.AuditResolveLoopTests -v2`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add inventory/views.py inventory/tests.py
git commit -m "feat: mark AuditUnknownScan resolved when its add-product handoff creates the item"
```

---

## Task 6: UI surfaces — body card/badge, finalize note, admin

**Files:**
- Modify: `inventory/templates/inventory/partials/audit_body.html` (stat cards block lines 5-26; add badge)
- Modify: `inventory/templates/inventory/audit_finalize.html` (add queued-unknowns note)
- Modify: `inventory/admin.py` (register `AuditUnknownScan`)
- Test: `inventory/tests.py` (new class `AuditUiSurfaceTests`)

- [ ] **Step 1: Write the failing test**

First inspect `audit_finalize.html` to anchor the note. Then append to `inventory/tests.py`:

```python
class AuditUiSurfaceTests(TestCase):
    def setUp(self):
        self.client = Client()
        User.objects.create_user(username="ui", password="pass")
        self.client.login(username="ui", password="pass")
        self.loc = Location.objects.create(
            name="UI1", kind=Location.Kind.SHELF,
            default_status=InventoryItem.Status.NEW,
        )

    def test_finalize_notes_queued_unknowns(self):
        self.client.post(reverse("audit_start"))
        session = AuditSession.active()
        AuditUnknownScan.objects.create(
            session=session, upc="900000000001", location=self.loc
        )
        resp = self.client.get(reverse("audit_finalize"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "audit/unknowns")

    def test_body_shows_added_card(self):
        self.client.post(reverse("audit_start"))
        self.client.post(reverse("audit_scan"), {"code": f"LOC-{self.loc.pk}"})
        resp = self.client.post(
            reverse("audit_scan"), {"code": f"LOC-{self.loc.pk}"},
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(resp, "Added")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.AuditUiSurfaceTests -v2`
Expected: FAIL — finalize page has no `/audit/unknowns` link; body has no "Added" card.

- [ ] **Step 3: Add the "Added" card + "Unknowns" badge to `audit_body.html`**

In `inventory/templates/inventory/partials/audit_body.html`, add an "Added" card inside the stat-card flex row (after the "Locations done" card, before the "Unknown" card, ~line 21):

```django
  <div class="card text-center px-3 py-2">
    <div class="fw-bold fs-4">{{ tally.added }}</div>
    <div class="text-muted small">Added</div>
  </div>
```

Then, immediately after the closing `</div>` of the stat-card flex row (line 26), add the review-queue badge:

```django
{% if unknown_count %}
  <div class="mb-3">
    <a class="btn btn-sm btn-outline-warning" href="{% url 'audit_unknowns' %}">
      <i class="bi bi-upc-scan"></i> Unknown UPCs ({{ unknown_count }})
    </a>
  </div>
{% endif %}
```

- [ ] **Step 4: Add the queued-unknowns note to `audit_finalize.html`**

Open `inventory/templates/inventory/audit_finalize.html`, and inside `{% block content %}` (near the top of the summary, before the depletion list) add:

```django
{% load inventory_extras %}
{% if unknown_count %}
  <div class="alert alert-warning">
    <i class="bi bi-upc-scan"></i>
    {{ unknown_count }} unknown UPC{{ unknown_count|pluralize }} still queued —
    <a href="{% url 'audit_unknowns' %}">review them</a> after finalizing.
  </div>
{% endif %}
```

If `audit_finalize.html` doesn't already `{% load %}` a custom tag lib, omit the `{% load inventory_extras %}` line (only `pluralize` is used, which is built in). Then provide `unknown_count` to the finalize context: in `inventory/views.py` `AuditFinalizeView.get`, add it to the render context:

```python
        return render(
            request,
            "inventory/audit_finalize.html",
            {
                "session": session,
                "unknown_items": audit.session_unknown_items(session),
                "unknown_count": AuditUnknownScan.objects.filter(
                    resolved=False, dismissed=False
                ).count(),
            },
        )
```

- [ ] **Step 5: Register the admin**

In `inventory/admin.py`, add an import of `AuditUnknownScan` (to the existing models import) and register:

```python
@admin.register(AuditUnknownScan)
class AuditUnknownScanAdmin(admin.ModelAdmin):
    list_display = ("upc", "location", "created_at", "resolved", "dismissed")
    list_filter = ("resolved", "dismissed")
    search_fields = ("upc",)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.AuditUiSurfaceTests -v2`
Expected: PASS (2 tests).

- [ ] **Step 7: Full suite + Django check**

Run: `~/.venvs/inventory/bin/python manage.py test inventory -v1 && ~/.venvs/inventory/bin/python manage.py check`
Expected: all tests PASS (66 existing + new); check clean.

- [ ] **Step 8: Commit**

```bash
git add inventory/templates/inventory/partials/audit_body.html inventory/templates/inventory/audit_finalize.html inventory/views.py inventory/admin.py inventory/tests.py
git commit -m "feat: audit UI — Added card, unknown-UPC badge, finalize note, admin"
```

---

## Task 7: Pre-commit, docs, PR

**Files:**
- Modify: `readme.md`, `todo.md`, `CLAUDE.md` (Phase 6 remaining → done for inline-add)

- [ ] **Step 1: Run pre-commit on all changed files**

Run: `pre-commit run --files inventory/models.py inventory/audit.py inventory/views.py inventory/urls.py inventory/admin.py inventory/tests.py inventory/migrations/0027_audit_unknown_scan.py inventory/templates/inventory/audit_unknowns.html inventory/templates/inventory/partials/audit_body.html inventory/templates/inventory/audit_finalize.html`
Expected: black/ruff/djlint pass (ruff may auto-fix; re-stage and re-run if so).

- [ ] **Step 2: Update docs**

- `readme.md`: note inline add-item during audit + `/audit/unknowns/` review page.
- `todo.md`: mark the audit inline-add item done under Phase 6.
- `CLAUDE.md`: add a short Phase 6 follow-up note (inline add-item shipped; correct the stale "PR #113 open" line to "merged `0b354ef`, deployed; `seed_locations` run on prod 2026-06-06").

- [ ] **Step 3: Commit docs**

```bash
git add readme.md todo.md CLAUDE.md
git commit -m "docs: record audit inline add-item; correct PR #113 status"
```

- [ ] **Step 4: Push + open PR**

```bash
git push -u origin feat/audit-inline-add-item
gh pr create --base master --title "feat: inline add-item during inventory audit" \
  --body "$(cat <<'EOF'
## Summary
Lets the audit scan stream handle untracked spools without leaving the console:
- Bare-numeric scans are treated as UPCs.
- In-catalog UPC → mints an InventoryItem at the active location + prints its label (logged as a new AuditEvent.ADDED, immune to the close-location UNKNOWN sweep).
- Unknown UPC → queued to AuditUnknownScan, reviewed post-walk at /audit/unknowns/, where each row hands into the existing add-product flow and is marked resolved on item creation.

Migration 0027 (additive). Builds on the deployed audit base (#113).

## Test plan
- New test classes: model, add_or_queue service, scan-view UPC dispatch, review page, resolve loop, UI surfaces.
- Full suite green; `manage.py check` clean.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 5: Report the PR URL.**

---

## Self-review notes

- **Spec coverage:** model (T1) · parse_code/PRESENT_ACTIONS/add_or_queue (T2) · scan dispatch + print + tally (T3) · review page + resolve/dismiss (T4) · resolution loop + stale-id pop (T5) · body card/badge + finalize note + admin (T6) · pre-commit/docs/PR (T7). All spec sections mapped.
- **Type/name consistency:** `add_or_queue_upc` returns `(outcome, obj)` with `outcome ∈ {"added","queued"}` — used identically in T2 tests and T3 view. `parse_code` returns `(kind, value)` where value is `int` for loc/item, `str` for upc — T3 renames the unpack var to `value` to reflect this. `unknown_count` (context key) consistent across T3, T6. `_resolve_pending_unknown(request, item)` reads session; the new-product path uses the inline `.update()` form because the session is already popped there (documented in T5 step 5).
- **Migration:** single additive `0027` on top of deployed `0026`; no data backfill, no NOT-NULL trap.
