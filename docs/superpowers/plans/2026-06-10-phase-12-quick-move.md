# Phase 12 — Quick-Move & Phone Scanning — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A phone-first quick scan-to-move flow (scan item → scan/pick destination → `move_to`, with evict-when-full and one-tap deplete), plus QR labels, an in-app camera scanner, and an installable PWA.

**Architecture:** Mirror the audit subsystem — a `quickmove.py` service holds the resolution/evict logic, thin HTMX CBVs render a state-driven body partial. All `InventoryItem` mutations go through the existing `inventory.items` service (`move_to`/`deplete`). Scanned-code parsing reuses `audit.parse_code` / `audit.resolve_serial`. State is carried client-side in a hidden form field (no server session).

**Tech Stack:** Django 6, HTMX (already loaded globally), Bootstrap 5 (Zephyr via CDN), `qrcode` (new dep) + Pillow for labels, `@zxing/browser` (vendored UMD) for the camera. No npm/bundler.

**Reference spec:** `docs/superpowers/specs/2026-06-10-phase-12-quick-move-design.md`.

**No DB migration** — Phase 12 adds no model fields (`Location.capacity` shipped in 11.3). If any step generates one, something is wrong; stop and reconcile.

**Branch:** work on `feat/phase-12-quick-move` (already created; the spec is its first commit).

---

## File Structure

- **Create** `inventory/quickmove.py` — resolution + evict service (Task 3).
- **Create** `inventory/templates/inventory/quick_move.html` — page shell (Task 4).
- **Create** `inventory/templates/inventory/partials/quick_move_body.html` — state-driven HTMX fragment (Task 4).
- **Create** `inventory/templates/inventory/partials/scanner_modal.html` — shared camera modal (Task 5).
- **Create** `inventory/static/inventory/js/scanner.js` — zxing camera wrapper (Task 5).
- **Create** `inventory/static/inventory/js/quick_move.js` — page glue (Task 5).
- **Create** `inventory/static/inventory/js/vendor/zxing-browser.min.js` — vendored UMD (Task 5, downloaded).
- **Create** `inventory/static/inventory/manifest.json` + `images/icon-192.png` + `images/icon-512.png` (Task 6).
- **Modify** `inventory_management_site/settings.py` — `SITE_BASE_URL`, `CSRF_TRUSTED_ORIGINS` (Task 1).
- **Modify** `docker-compose.yml` — `SITE_BASE_URL` env on `web` (Task 1).
- **Modify** `requirements.txt` — add `qrcode` (Task 2).
- **Modify** `inventory/barcode_utils.py` — QR rendering + label layout + `label_qr_url` (Task 2).
- **Modify** `inventory/admin.py:507-513` — QR on LOC- labels (Task 2).
- **Modify** `inventory/views.py` — `QuickMoveView`, `QuickMoveScanView` (Task 4).
- **Modify** `inventory/urls.py` — `move/`, `move/scan/` routes (Task 4).
- **Modify** `inventory/templates/inventory/base.html` — manifest/theme-color links, scanner modal include (Tasks 5,6).
- **Modify** `inventory/templates/inventory/navigation.html` — Move nav link (Task 7).
- **Modify** `inventory/templates/inventory/audit_console.html` — camera button + scanner scripts (Task 5).
- **Modify** `inventory/tests.py` — tests appended per task.
- **Modify** `readme.md`, `todo.md` — Task 7.

**Run all commands from the repo root with the project venv:** `~/.venvs/inventory/bin/python`. Run a single test class with `~/.venvs/inventory/bin/python manage.py test inventory.tests.<ClassName> -v 2`.

---

## Task 1: Settings & config groundwork

**Files:**
- Modify: `inventory_management_site/settings.py:161-172` (CSRF) and after the `ENABLE_BARCODE_PRINTING` block (`:38`)
- Modify: `docker-compose.yml:17-22` (web `environment:`)
- Test: `inventory/tests.py`

- [ ] **Step 1: Write the failing test**

Append to `inventory/tests.py`:

```python
class SiteBaseUrlSettingTests(TestCase):
    def test_site_base_url_default_is_https_host(self):
        from django.conf import settings

        self.assertTrue(settings.SITE_BASE_URL.startswith("https://"))
        self.assertIn("inventory.home.collerco.com", settings.SITE_BASE_URL)

    def test_https_origin_is_csrf_trusted(self):
        from django.conf import settings

        self.assertIn(
            "https://inventory.home.collerco.com", settings.CSRF_TRUSTED_ORIGINS
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.SiteBaseUrlSettingTests -v 2`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'SITE_BASE_URL'` (and the CSRF assertion fails).

- [ ] **Step 3: Add the setting**

In `inventory_management_site/settings.py`, immediately after the `ENABLE_BARCODE_PRINTING = config(...)` line (around `:38`), add:

```python
# Public base URL used to build absolute links encoded in QR labels (Phase 12).
# Non-secret; overridable per-environment via docker-compose `environment:`.
SITE_BASE_URL = config(
    "SITE_BASE_URL", default="https://inventory.home.collerco.com"
)
```

In the same file, add the HTTPS origin to `CSRF_TRUSTED_ORIGINS` (the `# Via NGINX` group, around `:171`):

```python
    # Via NGINX
    "http://inventory.home",
    "https://inventory.home.collerco.com",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.SiteBaseUrlSettingTests -v 2`
Expected: PASS (2 tests).

- [ ] **Step 5: Wire the compose env var**

In `docker-compose.yml`, inside the `web` service `environment:` block (after the `SQLITE_DB_PATH` line, ~`:22`), add:

```yaml
      # Absolute base URL embedded in QR labels (Phase 12). Non-secret → lives in
      # version control here, not the root-owned ~/.env_inventory.
      - SITE_BASE_URL=https://inventory.home.collerco.com
```

Run: `docker compose config -q` (syntax check only). Expected: no output, exit 0. *(If `docker` is unavailable on this LXC, skip — the GitHub Actions runner validates on deploy.)*

- [ ] **Step 6: Commit**

```bash
git add inventory_management_site/settings.py docker-compose.yml inventory/tests.py
git commit -m "feat: SITE_BASE_URL + HTTPS CSRF origin for Phase 12 quick-move"
```

---

## Task 2: QR labels in barcode_utils

**Files:**
- Modify: `requirements.txt:12-16`
- Modify: `inventory/barcode_utils.py` (LabelProfile `:77-148`, `create_label_image` `:244-303`, new helpers, `generate_and_print_barcode` `:562-648`, `generate_and_print_label` `:460-482`, `__all__` `:651`)
- Modify: `inventory/admin.py:506-513`
- Test: `inventory/tests.py`

- [ ] **Step 1: Add the dependency**

In `requirements.txt`, after the `python-barcode>=0.16.1` line, add:

```
qrcode>=8.0
```

Install it into the venv:

Run: `~/.venvs/inventory/bin/python -m pip install 'qrcode>=8.0'`
Expected: `Successfully installed qrcode-...` (pure-Python; reuses the existing Pillow).

- [ ] **Step 2: Write the failing test for the QR URL builder**

Append to `inventory/tests.py`:

```python
class LabelQrTests(TestCase):
    def test_label_qr_url_builds_absolute_barcode_url(self):
        from inventory.barcode_utils import label_qr_url

        url = label_qr_url("INV-563")
        self.assertEqual(
            url, "https://inventory.home.collerco.com/barcode/INV-563/"
        )

    def test_create_label_image_with_qr_matches_profile_size(self):
        from inventory.barcode_utils import DEFAULT_PROFILE, create_label_image

        img = create_label_image(
            "INV-563", text="INV-563", qr_value="https://x/barcode/INV-563/"
        )
        self.assertEqual(img.size, DEFAULT_PROFILE.canvas_size_px)
        self.assertEqual(img.mode, "1")

    def test_create_label_image_without_qr_still_renders(self):
        from inventory.barcode_utils import DEFAULT_PROFILE, create_label_image

        img = create_label_image("INV-563", text="INV-563")
        self.assertEqual(img.size, DEFAULT_PROFILE.canvas_size_px)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.LabelQrTests -v 2`
Expected: FAIL — `ImportError: cannot import name 'label_qr_url'`.

- [ ] **Step 4: Add `include_qr` to LabelProfile**

In `inventory/barcode_utils.py`, add a field to the `LabelProfile` dataclass (after `side_margin_mm: float = 2.0`, `:94`):

```python
    side_margin_mm: float = 2.0
    include_qr: bool = True
```

- [ ] **Step 5: Add the QR URL builder and renderer**

In `inventory/barcode_utils.py`, add these functions just above `create_label_image` (`:244`):

```python
def label_qr_url(value: str) -> str:
    """Absolute URL encoded in a label's QR code, e.g.
    'https://host/barcode/INV-563/'. Decoded by BarcodeRedirectView; a phone's
    native camera opens it directly, the in-app scanner strips it back to the code.
    """
    from django.urls import reverse

    base = getattr(settings, "SITE_BASE_URL", "").rstrip("/")
    return f"{base}{reverse('barcode_redirect', args=[value])}"


def _render_qr(data: str, side_px: int) -> Image.Image:
    """Render a 1-bit square QR image of the given pixel side."""
    import qrcode

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=1,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("1")
    return img.resize((side_px, side_px), resample=Image.NEAREST)
```

- [ ] **Step 6: Teach `create_label_image` the two-column QR layout**

Replace the body of `create_label_image` (`:244-303`) with this. It keeps the existing single-column path when `qr_value` is absent or `include_qr` is False, and renders QR-left / Code128+text-right otherwise:

```python
def create_label_image(
    data: str,
    text: str | None = None,
    profile: LabelProfile | None = None,
    qr_value: str | None = None,
) -> Image.Image:
    """
    Build a full label image in mode '1'.

    - data: exact string encoded in the Code128 barcode (e.g. "INV-739").
    - text: optional human-readable label (defaults to `data`).
    - profile: LabelProfile controlling layout and size.
    - qr_value: optional URL to render as a QR code on the left of the label. Only
      drawn when given AND profile.include_qr is True.
    """
    if profile is None:
        profile = DEFAULT_PROFILE

    canvas_width, canvas_height = profile.canvas_size_px
    label_img = Image.new("1", (canvas_width, canvas_height), 1)
    margin = profile.side_margin_px

    draw_qr = bool(qr_value) and profile.include_qr
    if draw_qr:
        qr_side = canvas_height - 2 * margin
        qr_img = _render_qr(qr_value, qr_side)
        label_img.paste(qr_img, (margin, margin))
        barcode_left = margin + qr_side + margin
    else:
        barcode_left = margin

    barcode_area_width = canvas_width - barcode_left - margin
    barcode_height_px = int(canvas_height * profile.barcode_area_ratio)

    barcode_img = generate_barcode_to_fit(
        data=data,
        max_width_px=barcode_area_width,
        target_height_px=barcode_height_px,
        dpi=profile.dpi,
    )

    barcode_x = barcode_left + (barcode_area_width - barcode_img.width) // 2
    barcode_y = 0
    label_img.paste(barcode_img, (barcode_x, barcode_y))

    if text is None:
        text = data
    if text:
        drawer = ImageDraw.Draw(label_img)
        font = _get_default_font()
        text_y_top = barcode_y + barcode_img.height + 2
        if text_y_top < canvas_height:
            text_center_x = barcode_left + barcode_area_width // 2
            drawer.text(
                (text_center_x, text_y_top), text, font=font, anchor="ma", fill=0
            )

    # Do NOT rotate; brother_ql.convert(..., rotate="auto") handles it.
    return label_img
```

- [ ] **Step 7: Run the label tests to verify they pass**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.LabelQrTests -v 2`
Expected: PASS (3 tests).

- [ ] **Step 8: Thread `qr_value` through the print helpers and INV/LOC callers**

In `inventory/barcode_utils.py`, update `generate_and_print_label` (`:460`) to accept and forward `qr_value`:

```python
def generate_and_print_label(
    data: str,
    text: str | None = None,
    profile: LabelProfile | None = None,
    qr_value: str | None = None,
    **print_kwargs,
) -> HttpResponse:
    img = create_label_image(data=data, text=text, profile=profile, qr_value=qr_value)
    if settings.ENABLE_BARCODE_PRINTING:
        print_label_image(img, **print_kwargs)
    else:
        logger.info("[TEST MODE] Skipping actual label print for item %s", data)

    response = HttpResponse(content_type="image/png")
    img.save(response, format="PNG")
    return response
```

In `generate_and_print_barcode` (`:645`), pass the QR URL for the unique (INV-) path. Replace the final `response = generate_and_print_label(...)` call with:

```python
    qr_value = label_qr_url(data) if mode_lower in ("unique", "inv", "inventory") else None
    response = generate_and_print_label(
        data=data, text=text, profile=profile, qr_value=qr_value, **print_kwargs
    )
    return response
```

In `inventory/admin.py:513`, add the QR to LOC- labels:

```python
                from .barcode_utils import generate_and_print_label, label_qr_url

                generate_and_print_label(
                    data=f"LOC-{loc.pk}",
                    text=loc.name,
                    qr_value=label_qr_url(f"LOC-{loc.pk}"),
                )
```

(Adjust the existing `from .barcode_utils import generate_and_print_label` line at `:508` to also import `label_qr_url`, or use the inline import shown.)

- [ ] **Step 9: Write a test that the INV barcode carries a QR, and run it**

Append to `inventory/tests.py`:

```python
class GenerateBarcodeQrTests(TestCase):
    def test_unique_mode_embeds_qr(self):
        from unittest.mock import patch

        from inventory.barcode_utils import generate_and_print_barcode
        from inventory.models import Filament, InventoryItem

        product = Filament.objects.create(name="PLA QR", upc="700000000777")
        item = InventoryItem.objects.create(product=product)
        with patch("inventory.barcode_utils.create_label_image") as mock_create:
            mock_create.return_value.save = lambda *a, **k: None
            generate_and_print_barcode(item, mode="unique")
        _, kwargs = mock_create.call_args
        self.assertEqual(
            kwargs["qr_value"],
            f"https://inventory.home.collerco.com/barcode/INV-{item.id}/",
        )
```

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.GenerateBarcodeQrTests inventory.tests.LabelQrTests -v 2`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add requirements.txt inventory/barcode_utils.py inventory/admin.py inventory/tests.py
git commit -m "feat: render a URL QR code alongside Code128 on labels (Phase 12)"
```

---

## Task 3: `quickmove.py` service

**Files:**
- Create: `inventory/quickmove.py`
- Test: `inventory/tests.py`

- [ ] **Step 1: Write the failing tests**

Append to `inventory/tests.py`:

```python
class QuickMoveServiceTests(TestCase):
    def setUp(self):
        from inventory.models import Filament, InventoryItem, Location

        self.shelf = Location.objects.create(
            name="QM Shelf", kind=Location.Kind.SHELF,
            default_status=InventoryItem.Status.STORED,
        )
        self.slot = Location.objects.create(
            name="QM Slot", kind=Location.Kind.AMS_SLOT,
            default_status=InventoryItem.Status.IN_USE,
        )  # capacity defaults to 1
        self.ams = Location.objects.create(name="QM AMS", kind=Location.Kind.AMS)
        self.ams_slot1 = Location.objects.create(
            name="QM AMS s1", kind=Location.Kind.AMS_SLOT, parent=self.ams,
            slot_index=1, default_status=InventoryItem.Status.IN_USE,
        )
        product = Filament.objects.create(name="PLA QM", upc="700000000010")
        self.item = InventoryItem.objects.create(product=product, location=self.shelf)

    def test_resolve_active_item_from_inv_code(self):
        from inventory import quickmove

        self.assertEqual(quickmove.resolve_active_item(f"INV-{self.item.pk}"), self.item)

    def test_resolve_active_item_strips_url(self):
        from inventory import quickmove

        url = f"https://inventory.home.collerco.com/barcode/INV-{self.item.pk}/"
        self.assertEqual(quickmove.resolve_active_item(url), self.item)

    def test_resolve_active_item_rejects_location(self):
        from inventory import quickmove

        with self.assertRaises(quickmove.QuickMoveError):
            quickmove.resolve_active_item(f"LOC-{self.shelf.pk}")

    def test_resolve_destination_leaf(self):
        from inventory import quickmove

        dest = quickmove.resolve_destination(f"LOC-{self.shelf.pk}")
        self.assertEqual(dest.location, self.shelf)
        self.assertFalse(dest.needs_slot_pick)

    def test_resolve_destination_container_needs_slot_pick(self):
        from inventory import quickmove

        dest = quickmove.resolve_destination(f"LOC-{self.ams.pk}")
        self.assertEqual(dest.location, self.ams)
        self.assertTrue(dest.needs_slot_pick)

    def test_attempt_move_ok_sets_location_and_derives_status(self):
        from inventory import quickmove
        from inventory.models import InventoryItem

        outcome = quickmove.attempt_move(self.item, self.slot)
        self.assertEqual(outcome.kind, "ok")
        self.item.refresh_from_db()
        self.assertEqual(self.item.location_id, self.slot.id)
        self.assertEqual(self.item.status, InventoryItem.Status.IN_USE)

    def test_attempt_move_full_returns_occupant(self):
        from inventory import quickmove
        from inventory.models import Filament, InventoryItem

        sitting = InventoryItem.objects.create(
            product=Filament.objects.create(name="Occ", upc="700000000011"),
            location=self.slot,
        )
        outcome = quickmove.attempt_move(self.item, self.slot)
        self.assertEqual(outcome.kind, "full")
        self.assertEqual(outcome.occupant, sitting)

    def test_evict_and_place_deplete_old(self):
        from inventory import quickmove
        from inventory.models import Filament, InventoryItem

        occ = InventoryItem.objects.create(
            product=Filament.objects.create(name="Empty", upc="700000000012"),
            location=self.slot,
        )
        result, evicted = quickmove.evict_and_place(
            occ, self.item, self.slot, deplete_old=True
        )
        self.assertTrue(result.ok)
        self.assertIsNone(evicted)
        occ.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(occ.status, InventoryItem.Status.DEPLETED)
        self.assertEqual(self.item.location_id, self.slot.id)

    def test_evict_and_place_rehome_old_returns_evicted(self):
        from inventory import quickmove
        from inventory.models import Filament, InventoryItem

        occ = InventoryItem.objects.create(
            product=Filament.objects.create(name="Move", upc="700000000013"),
            location=self.slot,
        )
        result, evicted = quickmove.evict_and_place(
            occ, self.item, self.slot, deplete_old=False
        )
        self.assertTrue(result.ok)
        self.assertEqual(evicted, occ)
        occ.refresh_from_db()
        self.assertIsNone(occ.location_id)  # unassigned, awaiting the chain
        self.item.refresh_from_db()
        self.assertEqual(self.item.location_id, self.slot.id)

    def test_unknown_item_stays_unknown_after_move(self):
        from inventory import quickmove
        from inventory.models import InventoryItem

        self.item.status = InventoryItem.Status.UNKNOWN
        self.item.save()
        quickmove.attempt_move(self.item, self.slot)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, InventoryItem.Status.UNKNOWN)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.QuickMoveServiceTests -v 2`
Expected: FAIL — `ModuleNotFoundError: No module named 'inventory.quickmove'`.

- [ ] **Step 3: Write the service**

Create `inventory/quickmove.py`:

```python
"""Quick scan-to-move service.

Resolves scanned codes into the item being moved or its destination, classifies a
move outcome (ok / full), and orchestrates the evict-then-place chain. Mirrors
:mod:`inventory.audit`: logic lives here, thin CBVs call it. Every mutation goes
through :mod:`inventory.items` (``move_to`` / ``deplete``) — no flags touched here.
Code parsing reuses :func:`inventory.audit.parse_code` / ``resolve_serial``.
"""

from dataclasses import dataclass
from urllib.parse import urlparse

from . import audit, items
from .models import InventoryItem, Location


class QuickMoveError(Exception):
    """User-facing error raised when a scan can't be processed in the move flow."""


def strip_url(raw):
    """Return the trailing code of a ``/barcode/<code>/`` URL, else the raw text.

    A native-camera URL-QR decodes to e.g.
    ``https://host/barcode/INV-563/``; the in-app scanner feeds that here and we
    reduce it to ``INV-563`` so it parses like any other scan.
    """
    text = (raw or "").strip()
    if "://" in text:
        parts = [p for p in urlparse(text).path.split("/") if p]
        if len(parts) >= 2 and parts[0].lower() == "barcode":
            return parts[1]
    return text


def _item_by_serial(value):
    """A single non-unit :class:`InventoryItem` whose serial matches ``value``, or None."""
    if not value or value.isdigit():
        return None
    matches = list(
        InventoryItem.objects.filter(serial_number__iexact=value)
        .exclude(serial_number="")
        .select_related("product", "location")
    )
    if len(matches) != 1:
        return None
    item = matches[0]
    return None if audit._is_unit_item(item) else item


def resolve_active_item(raw):
    """Resolve a scan to the item being moved.

    Accepts an ``INV-`` code, a barcode URL-QR, or a unique spool serial. Raises
    :class:`QuickMoveError` for a location scan, a UPC, an unknown code, a missing
    item, or a machine unit (which is not movable contents).
    """
    code = strip_url(raw)
    try:
        kind, value = audit.parse_code(code)
    except audit.AuditError:
        item = _item_by_serial(code)
        if item is None:
            raise QuickMoveError(f"Unrecognized code {raw!r}. Scan an item (INV-…/QR).")
        return item
    if kind == "loc":
        raise QuickMoveError("That's a location — scan an item first.")
    if kind == "upc":
        raise QuickMoveError(f"UPC {value} isn't a tracked item — add it via Audit.")
    item = (
        InventoryItem.objects.filter(pk=value)
        .select_related("product", "location")
        .first()
    )
    if item is None:
        raise QuickMoveError(f"No item with id {value}.")
    if audit._is_unit_item(item):
        raise QuickMoveError(
            f"{item.product.name} is a machine unit, not movable contents."
        )
    return item


@dataclass
class Destination:
    location: Location
    needs_slot_pick: bool = False


def resolve_destination(raw):
    """Resolve a scan to a destination. A container flags ``needs_slot_pick``.

    Accepts a ``LOC-`` code or a unit serial (via :func:`audit.resolve_serial`).
    Raises :class:`QuickMoveError` for an item/UPC scan or an unknown location.
    """
    code = strip_url(raw)
    try:
        kind, value = audit.parse_code(code)
    except audit.AuditError:
        try:
            location = audit.resolve_serial(code)
        except audit.AuditError as exc:
            raise QuickMoveError(str(exc))
        return Destination(location, needs_slot_pick=location.is_container)
    if kind == "item":
        raise QuickMoveError("That's an item — scan a destination location (LOC-…).")
    if kind == "upc":
        raise QuickMoveError("That's a UPC — scan a destination location (LOC-…).")
    location = Location.objects.filter(pk=value).first()
    if location is None:
        raise QuickMoveError(f"No location with id {value}.")
    return Destination(location, needs_slot_pick=location.is_container)


def occupant_at(location):
    """The single active (non-terminal) occupant of a leaf location, or None."""
    return (
        InventoryItem.objects.filter(location=location)
        .exclude(status__in=items.TERMINAL_STATUSES)
        .select_related("product")
        .first()
    )


@dataclass
class MoveOutcome:
    kind: str  # "ok" | "full" | "error"
    result: object = None
    occupant: object = None
    message: str = ""


def attempt_move(item, location):
    """Place ``item`` at a leaf ``location`` via ``items.move_to`` (capacity enforced).

    Classifies a rejection without string-matching: ``move_to`` only refuses for a
    container or for capacity; containers are handled upstream by
    :func:`resolve_destination`, so a rejection here is capacity → ``full`` with the
    occupant.
    """
    result = items.move_to(item, location, enforce_capacity=True)
    if result.ok:
        return MoveOutcome("ok", result=result)
    occupant = occupant_at(location)
    if occupant is not None:
        return MoveOutcome("full", occupant=occupant, message=result.message)
    return MoveOutcome("error", message=result.message)


def evict_and_place(occupant, incoming, dest, *, deplete_old):
    """Free ``dest`` of ``occupant`` then place ``incoming``.

    ``deplete_old=True`` marks the occupant DEPLETED (the spool ran out — the common
    AMS swap); otherwise it's unassigned (location cleared) and returned so the
    caller can chain it as the next active item. Returns ``(place_result, evicted)``.
    """
    if deplete_old:
        items.deplete(occupant, reason="swap")
        evicted = None
    else:
        items.move_to(occupant, None, skip_drying_check=True)
        evicted = occupant
    result = items.move_to(incoming, dest, enforce_capacity=True)
    return result, evicted
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.QuickMoveServiceTests -v 2`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add inventory/quickmove.py inventory/tests.py
git commit -m "feat: quickmove service — scan resolution + evict/place chain (Phase 12)"
```

---

## Task 4: Views, URLs, and templates

**Files:**
- Modify: `inventory/views.py` (add the two CBVs; reuse `_slot_map_for_unit`, `items`, `quickmove`)
- Modify: `inventory/urls.py` (import + 2 routes)
- Create: `inventory/templates/inventory/quick_move.html`
- Create: `inventory/templates/inventory/partials/quick_move_body.html`
- Test: `inventory/tests.py`

- [ ] **Step 1: Write the failing view tests**

Append to `inventory/tests.py`:

```python
class QuickMoveViewTests(TestCase):
    def setUp(self):
        from inventory.models import Filament, InventoryItem, Location

        self.client = Client()
        User.objects.create_user(username="qm", password="pass")
        self.client.login(username="qm", password="pass")
        self.shelf = Location.objects.create(
            name="QMV Shelf", kind=Location.Kind.SHELF,
            default_status=InventoryItem.Status.STORED,
        )
        self.slot = Location.objects.create(
            name="QMV Slot", kind=Location.Kind.AMS_SLOT,
            default_status=InventoryItem.Status.IN_USE,
        )
        self.product = Filament.objects.create(name="PLA QMV", upc="700000000020")
        self.item = InventoryItem.objects.create(
            product=self.product, location=self.shelf
        )

    def _scan(self, **data):
        return self.client.post(
            reverse("quick_move_scan"), data, HTTP_HX_REQUEST="true"
        )

    def test_get_page(self):
        resp = self.client.get(reverse("quick_move"))
        self.assertEqual(resp.status_code, 200)

    def test_scan_item_then_destination_moves(self):
        from inventory.models import InventoryItem

        r1 = self._scan(code=f"INV-{self.item.pk}", active_item_id="")
        self.assertEqual(r1.status_code, 200)
        r2 = self._scan(code=f"LOC-{self.slot.pk}", active_item_id=str(self.item.pk))
        self.assertEqual(r2.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.location_id, self.slot.id)
        self.assertEqual(self.item.status, InventoryItem.Status.IN_USE)

    def test_scan_into_full_slot_shows_confirm(self):
        from inventory.models import Filament, InventoryItem

        InventoryItem.objects.create(
            product=Filament.objects.create(name="Sitting", upc="700000000021"),
            location=self.slot,
        )
        resp = self._scan(code=f"LOC-{self.slot.pk}", active_item_id=str(self.item.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "is full")
        # Not moved yet.
        self.item.refresh_from_db()
        self.assertEqual(self.item.location_id, self.shelf.id)

    def test_evict_deplete_then_place(self):
        from inventory.models import Filament, InventoryItem

        occ = InventoryItem.objects.create(
            product=Filament.objects.create(name="Empty", upc="700000000022"),
            location=self.slot,
        )
        resp = self._scan(
            action="evict", deplete_old="1", active_item_id=str(self.item.pk),
            dest_id=str(self.slot.pk), occupant_id=str(occ.pk),
        )
        self.assertEqual(resp.status_code, 200)
        occ.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(occ.status, InventoryItem.Status.DEPLETED)
        self.assertEqual(self.item.location_id, self.slot.id)

    def test_evict_rehome_chains_old_item(self):
        from inventory.models import Filament, InventoryItem

        occ = InventoryItem.objects.create(
            product=Filament.objects.create(name="Rehome", upc="700000000023"),
            location=self.slot,
        )
        resp = self._scan(
            action="evict", deplete_old="0", active_item_id=str(self.item.pk),
            dest_id=str(self.slot.pk), occupant_id=str(occ.pk),
        )
        self.assertEqual(resp.status_code, 200)
        # The evicted item is now the active one to re-home.
        self.assertContains(resp, f"INV-{occ.pk}")
        occ.refresh_from_db()
        self.assertIsNone(occ.location_id)

    def test_deplete_active_from_card(self):
        from inventory.models import InventoryItem

        resp = self._scan(action="deplete_active", active_item_id=str(self.item.pk))
        self.assertEqual(resp.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, InventoryItem.Status.DEPLETED)

    def test_requires_login(self):
        self.client.logout()
        resp = self.client.get(reverse("quick_move"))
        self.assertEqual(resp.status_code, 302)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.QuickMoveViewTests -v 2`
Expected: FAIL — `NoReverseMatch: 'quick_move' is not a valid view function or pattern name`.

- [ ] **Step 3: Add the views**

In `inventory/views.py`, confirm `quickmove` is importable (add `from . import quickmove` next to the existing `from . import items` / `from . import audit` imports near the top). Then add these two classes (place them just after `LocationDetailView`, around `:1615`):

```python
class QuickMoveView(LoginRequiredMixin, TemplateView):
    """Phone-first quick scan-to-move page. The interactive body is an HTMX
    fragment (see QuickMoveScanView); this just renders the idle shell."""

    template_name = "inventory/quick_move.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["state"] = "idle"
        return ctx


class QuickMoveScanView(LoginRequiredMixin, View):
    """Input-agnostic scan/action endpoint for the quick-move flow.

    State is carried client-side via the hidden ``active_item_id`` field, so a
    typed entry, USB wedge, or camera decode all POST the same payload. Returns the
    ``quick_move_body.html`` fragment on an HX request; falls back to the full page
    otherwise.
    """

    def post(self, request):
        action = request.POST.get("action", "")
        if action == "reset":
            return self._render(request, state="idle")
        if action == "show_item":
            item = self._item(request.POST.get("active_item_id"))
            if item is None:
                return self._render(request, state="idle")
            return self._render(request, state="item", active_item=item)
        if action == "deplete_active":
            item = self._item(request.POST.get("active_item_id"))
            if item is None:
                return self._render(request, state="idle")
            items.deplete(item, reason="quick-move")
            return self._render(
                request, state="idle",
                last_result=("success", f"Depleted {item.product.name}."),
            )
        if action == "evict":
            return self._evict(request)

        # A scan (no action): resolve item if none active, else a destination.
        active = self._item(request.POST.get("active_item_id"))
        code = request.POST.get("code", "")
        if active is None:
            return self._scan_item(request, code)
        return self._scan_destination(request, active, code)

    # --- helpers ---------------------------------------------------------
    def _item(self, raw_id):
        if not raw_id:
            return None
        return (
            InventoryItem.objects.filter(pk=raw_id)
            .select_related("product", "location")
            .first()
        )

    def _scan_item(self, request, code):
        try:
            item = quickmove.resolve_active_item(code)
        except quickmove.QuickMoveError as exc:
            return self._render(request, state="idle", last_result=("danger", str(exc)))
        return self._render(
            request, state="item", active_item=item,
            last_result=(
                "info",
                f"Moving {item.product.name} (INV-{item.pk}). Scan a destination.",
            ),
        )

    def _scan_destination(self, request, active, code):
        try:
            dest = quickmove.resolve_destination(code)
        except quickmove.QuickMoveError as exc:
            return self._render(
                request, state="item", active_item=active,
                last_result=("danger", str(exc)),
            )
        if dest.needs_slot_pick:
            return self._render(
                request, state="container", active_item=active, dest=dest.location,
                slot_rows=_slot_map_for_unit(dest.location),
                last_result=("info", f"{dest.location.name}: pick a slot."),
            )
        # Mirror the edit view: an error-level drying warning blocks the move.
        warning = active.filament_drying_warning(dest.location)
        if warning and warning[0] == "error":
            return self._render(
                request, state="item", active_item=active,
                last_result=("danger", warning[1]),
            )
        outcome = quickmove.attempt_move(active, dest.location)
        if outcome.kind == "ok":
            return self._placed(request, active, dest.location, outcome.result)
        if outcome.kind == "full":
            return self._render(
                request, state="full", active_item=active, dest=dest.location,
                occupant=outcome.occupant,
                last_result=("warning", f"{dest.location.name} is full."),
            )
        return self._render(
            request, state="item", active_item=active,
            last_result=("danger", outcome.message),
        )

    def _placed(self, request, item, dest, result):
        tag, msg = "success", f"Moved {item.product.name} to {dest.name}."
        if result.drying_warning:
            level, wmsg, _ = result.drying_warning
            msg = f"{msg} — {wmsg}"
            if level in ("warning", "error"):
                tag = "warning"
        return self._render(request, state="idle", last_result=(tag, msg))

    def _evict(self, request):
        incoming = self._item(request.POST.get("active_item_id"))
        occupant = self._item(request.POST.get("occupant_id"))
        dest = Location.objects.filter(pk=request.POST.get("dest_id") or 0).first()
        deplete_old = request.POST.get("deplete_old") == "1"
        if not (incoming and occupant and dest):
            return self._render(
                request, state="idle",
                last_result=("danger", "Lost track of the swap — rescan the item."),
            )
        result, evicted = quickmove.evict_and_place(
            occupant, incoming, dest, deplete_old=deplete_old
        )
        if not result.ok:
            return self._render(request, state="idle", last_result=("danger", result.message))
        if evicted is None:
            return self._render(
                request, state="idle",
                last_result=(
                    "success",
                    f"Depleted {occupant.product.name}; placed "
                    f"{incoming.product.name} in {dest.name}.",
                ),
            )
        return self._render(
            request, state="item", active_item=evicted,
            last_result=(
                "success",
                f"Placed {incoming.product.name} in {dest.name}. Now scan where "
                f"{evicted.product.name} (INV-{evicted.pk}) goes.",
            ),
        )

    def _render(self, request, *, state, active_item=None, dest=None,
                occupant=None, slot_rows=None, last_result=None):
        context = {
            "state": state,
            "active_item": active_item,
            "dest": dest,
            "occupant": occupant,
            "slot_rows": slot_rows,
            "last_result": last_result,
        }
        if request.headers.get("HX-Request"):
            return render(request, "inventory/partials/quick_move_body.html", context)
        return render(request, "inventory/quick_move.html", context)
```

If `TemplateView` / `View` aren't already imported in `views.py`, add them to the `from django.views.generic import ...` / `from django.views import View` imports (the audit CBVs already use `View`, and other views use `TemplateView`, so both are present — verify).

- [ ] **Step 4: Add the URLs**

In `inventory/urls.py`, add to the import block (`:4-53`): `QuickMoveScanView,` and `QuickMoveView,` (keep alphabetical-ish with the others). Add these routes near the `edit/`/`location/` group (after `:87`):

```python
    path("move/", QuickMoveView.as_view(), name="quick_move"),
    path("move/scan/", QuickMoveScanView.as_view(), name="quick_move_scan"),
```

- [ ] **Step 5: Create the page shell**

Create `inventory/templates/inventory/quick_move.html`:

```django
{% extends "inventory/base.html" %}
{% load static %}

{% block content %}
<div class="container py-3" style="max-width: 640px;">
  <h1 class="h4 mb-3"><i class="bi bi-arrow-left-right"></i> Quick Move</h1>
  <div id="quick-move-body">
    {% include "inventory/partials/quick_move_body.html" %}
  </div>
</div>
{% endblock content %}

{% block extra_scripts %}
  <script src="{% static 'inventory/js/vendor/zxing-browser.min.js' %}"></script>
  <script src="{% static 'inventory/js/scanner.js' %}"></script>
  <script src="{% static 'inventory/js/quick_move.js' %}"></script>
{% endblock extra_scripts %}
```

- [ ] **Step 6: Create the body partial**

Create `inventory/templates/inventory/partials/quick_move_body.html`:

```django
{% if last_result %}
  <div class="alert alert-{{ last_result.0 }} py-2">{{ last_result.1 }}</div>
{% endif %}

<form id="qm-scan-form" class="mb-3"
      hx-post="{% url 'quick_move_scan' %}"
      hx-target="#quick-move-body" hx-swap="innerHTML"
      hx-on::after-request="if(event.detail.successful){var c=this.querySelector('input[name=code]');c.value='';c.focus();}">
  {% csrf_token %}
  <input type="hidden" name="active_item_id" value="{{ active_item.id|default:'' }}">
  <div class="input-group input-group-lg">
    <span class="input-group-text"><i class="bi bi-upc-scan"></i></span>
    <input type="text" name="code" class="form-control" autocomplete="off" autofocus
           placeholder="{% if active_item %}Scan destination (LOC-… / serial){% else %}Scan an item (INV-… / QR){% endif %}">
    <button class="btn btn-outline-secondary" type="button" id="qm-camera-btn"
            data-scan-mode="feed" data-scan-target="#qm-scan-form" title="Scan with camera">
      <i class="bi bi-camera"></i>
    </button>
    <button class="btn btn-primary" type="submit">Go</button>
  </div>
</form>

{% if state == "item" %}
  <div class="card mb-3">
    <div class="card-body">
      <h5 class="card-title mb-1">{{ active_item.product.name }}</h5>
      <div class="text-muted small mb-3">
        INV-{{ active_item.pk }} ·
        <span class="badge bg-secondary">{{ active_item.get_status_display }}</span> ·
        {{ active_item.location.name|default:"no location" }}
        {% if active_item.percent_remaining is not None %} · {{ active_item.percent_remaining }}%{% endif %}
      </div>
      <div class="d-flex gap-2 flex-wrap">
        <a class="btn btn-sm btn-outline-primary" href="{% url 'inventory_edit' active_item.id %}">
          <i class="bi bi-pencil"></i> Edit
        </a>
        <form hx-post="{% url 'quick_move_scan' %}" hx-target="#quick-move-body" hx-swap="innerHTML">
          {% csrf_token %}
          <input type="hidden" name="action" value="deplete_active">
          <input type="hidden" name="active_item_id" value="{{ active_item.id }}">
          <button class="btn btn-sm btn-outline-danger" type="submit"><i class="bi bi-x-octagon"></i> Deplete</button>
        </form>
        <form hx-post="{% url 'quick_move_scan' %}" hx-target="#quick-move-body" hx-swap="innerHTML">
          {% csrf_token %}
          <input type="hidden" name="action" value="reset">
          <button class="btn btn-sm btn-outline-secondary" type="submit">Cancel</button>
        </form>
      </div>
    </div>
  </div>
{% endif %}

{% if state == "container" %}
  <div class="card mb-3">
    <div class="card-header">{{ dest.name }} — pick a slot</div>
    <div class="card-body d-flex flex-wrap gap-2">
      {% for row in slot_rows %}
        {% if row.item %}
          <div class="border rounded p-2 text-muted small text-center" style="width: 8rem;">
            Slot {{ row.location.slot_index|default:"–" }}<br>{{ row.item.product.name }}<br>
            <span class="badge bg-secondary">full</span>
          </div>
        {% else %}
          <form hx-post="{% url 'quick_move_scan' %}" hx-target="#quick-move-body" hx-swap="innerHTML">
            {% csrf_token %}
            <input type="hidden" name="active_item_id" value="{{ active_item.id }}">
            <input type="hidden" name="code" value="LOC-{{ row.location.pk }}">
            <button class="btn btn-outline-primary text-center" style="width: 8rem; height: 5rem;" type="submit">
              Slot {{ row.location.slot_index|default:"–" }}<br>(empty)
            </button>
          </form>
        {% endif %}
      {% endfor %}
    </div>
  </div>
{% endif %}

{% if state == "full" %}
  <div class="card border-warning mb-3">
    <div class="card-header">
      {{ dest.name }} is full — {{ occupant.product.name }} (INV-{{ occupant.pk }}) is here
    </div>
    <div class="card-body d-flex flex-column gap-2">
      <form hx-post="{% url 'quick_move_scan' %}" hx-target="#quick-move-body" hx-swap="innerHTML">
        {% csrf_token %}
        <input type="hidden" name="action" value="evict">
        <input type="hidden" name="deplete_old" value="1">
        <input type="hidden" name="active_item_id" value="{{ active_item.id }}">
        <input type="hidden" name="dest_id" value="{{ dest.id }}">
        <input type="hidden" name="occupant_id" value="{{ occupant.id }}">
        <button class="btn btn-danger w-100" type="submit">
          Evict &amp; place — {{ occupant.product.name }} is empty (deplete it)
        </button>
      </form>
      <form hx-post="{% url 'quick_move_scan' %}" hx-target="#quick-move-body" hx-swap="innerHTML">
        {% csrf_token %}
        <input type="hidden" name="action" value="evict">
        <input type="hidden" name="deplete_old" value="0">
        <input type="hidden" name="active_item_id" value="{{ active_item.id }}">
        <input type="hidden" name="dest_id" value="{{ dest.id }}">
        <input type="hidden" name="occupant_id" value="{{ occupant.id }}">
        <button class="btn btn-outline-primary w-100" type="submit">
          Evict &amp; place — re-home {{ occupant.product.name }} (scan where it goes next)
        </button>
      </form>
      <form hx-post="{% url 'quick_move_scan' %}" hx-target="#quick-move-body" hx-swap="innerHTML">
        {% csrf_token %}
        <input type="hidden" name="action" value="show_item">
        <input type="hidden" name="active_item_id" value="{{ active_item.id }}">
        <button class="btn btn-outline-secondary w-100" type="submit">Pick another slot</button>
      </form>
    </div>
  </div>
{% endif %}
```

- [ ] **Step 7: Run the view tests to verify they pass**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.QuickMoveViewTests -v 2`
Expected: PASS (7 tests).

- [ ] **Step 8: Commit**

```bash
git add inventory/views.py inventory/urls.py inventory/templates/inventory/quick_move.html inventory/templates/inventory/partials/quick_move_body.html inventory/tests.py
git commit -m "feat: quick-move views, URLs, and HTMX flow templates (Phase 12)"
```

---

## Task 5: Camera scanner (zxing) + camera buttons

> No automated tests (browser/getUserMedia). Verify manually on `https://inventory.home.collerco.com` from a phone.

**Files:**
- Create: `inventory/static/inventory/js/vendor/zxing-browser.min.js` (downloaded)
- Create: `inventory/static/inventory/js/scanner.js`
- Create: `inventory/static/inventory/js/quick_move.js`
- Create: `inventory/templates/inventory/partials/scanner_modal.html`
- Modify: `inventory/templates/inventory/base.html` (include the modal)
- Modify: `inventory/templates/inventory/audit_console.html` (camera button + scripts)

- [ ] **Step 1: Vendor the zxing UMD build**

Run:

```bash
mkdir -p inventory/static/inventory/js/vendor
curl -fsSL https://cdn.jsdelivr.net/npm/@zxing/browser@0.1.5/umd/zxing-browser.min.js \
  -o inventory/static/inventory/js/vendor/zxing-browser.min.js
test -s inventory/static/inventory/js/vendor/zxing-browser.min.js && echo OK
```

Expected: `OK` and a non-empty file. (Pinned to 0.1.5; the UMD global is `ZXingBrowser`.)

- [ ] **Step 2: Create the scanner module**

Create `inventory/static/inventory/js/scanner.js`:

```javascript
/* Reusable camera barcode scanner built on the vendored @zxing/browser UMD build.
   Used by quick-move and the audit console. getUserMedia requires a secure context
   (HTTPS or localhost), so we feature-detect and degrade gracefully on plain HTTP. */
(function (global) {
  "use strict";
  var Scanner = {};
  var controls = null;

  Scanner.supported = function () {
    return !!(
      global.isSecureContext &&
      navigator.mediaDevices &&
      navigator.mediaDevices.getUserMedia &&
      global.ZXingBrowser
    );
  };

  function stripBarcodeUrl(text) {
    try {
      if (text.indexOf("://") !== -1) {
        var path = new URL(text).pathname; // /barcode/INV-563/
        var parts = path.split("/").filter(Boolean);
        if (parts.length >= 2 && parts[0].toLowerCase() === "barcode") {
          return parts[1];
        }
      }
    } catch (e) {
      /* not a URL — fall through */
    }
    return (text || "").trim();
  }

  Scanner.open = function (opts) {
    // opts: { mode: "feed" | "navigate", onCode: function(code) }
    var modalEl = document.getElementById("scanner-modal");
    var video = document.getElementById("scanner-video");
    if (!modalEl || !video || !Scanner.supported()) {
      return;
    }
    var bsModal = global.bootstrap.Modal.getOrCreateInstance(modalEl);
    bsModal.show();
    var reader = new global.ZXingBrowser.BrowserMultiFormatReader();
    reader.decodeFromVideoDevice(undefined, video, function (result, err, ctrl) {
      controls = ctrl;
      if (result) {
        var raw = result.getText();
        if (controls) controls.stop();
        bsModal.hide();
        if (opts.mode === "navigate") {
          global.location.href = raw;
        } else if (typeof opts.onCode === "function") {
          opts.onCode(stripBarcodeUrl(raw));
        }
      }
    });
    modalEl.addEventListener(
      "hidden.bs.modal",
      function () {
        if (controls) controls.stop();
      },
      { once: true }
    );
  };

  global.Scanner = Scanner;
})(window);
```

- [ ] **Step 3: Create the page glue**

Create `inventory/static/inventory/js/quick_move.js`:

```javascript
/* Wires camera buttons (any element with data-scan-target) to the Scanner module
   and refocuses the scan input after each HTMX swap. Re-runs after swaps so the
   buttons rendered inside the body partial get wired too. */
(function () {
  "use strict";

  function wire(root) {
    var scope = root || document;
    var buttons = scope.querySelectorAll("[data-scan-target]");
    Array.prototype.forEach.call(buttons, function (btn) {
      if (btn.dataset.scanWired) return;
      btn.dataset.scanWired = "1";
      if (!window.Scanner || !window.Scanner.supported()) {
        btn.disabled = true;
        btn.title =
          "Camera needs HTTPS — type, use a USB wedge, or scan the QR with your phone's camera.";
        return;
      }
      btn.addEventListener("click", function () {
        var form = document.querySelector(btn.dataset.scanTarget);
        if (!form) return;
        window.Scanner.open({
          mode: btn.dataset.scanMode || "feed",
          onCode: function (code) {
            var input = form.querySelector("input[name=code]");
            input.value = code;
            if (window.htmx) {
              window.htmx.trigger(form, "submit");
            } else {
              form.requestSubmit();
            }
          },
        });
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    wire(document);
  });
  document.body.addEventListener("htmx:afterSwap", function (e) {
    wire(e.target);
  });
  document.body.addEventListener("htmx:afterSettle", function () {
    var input = document.querySelector("#quick-move-body input[name=code]");
    if (input) input.focus();
  });
})();
```

- [ ] **Step 4: Create the shared scanner modal**

Create `inventory/templates/inventory/partials/scanner_modal.html`:

```django
<div class="modal fade" id="scanner-modal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog modal-dialog-centered">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title"><i class="bi bi-camera"></i> Scan</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
      </div>
      <div class="modal-body text-center">
        <video id="scanner-video" style="width: 100%; border-radius: .5rem;" muted playsinline></video>
        <p class="text-muted small mt-2 mb-0">Point the camera at an INV / LOC QR or barcode.</p>
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 5: Include the modal app-wide**

In `inventory/templates/inventory/base.html`, add the include just before the closing `{% block content %}`/scripts — insert after the `{% endblock content %}` line (`:61`) and before the first `<script>` (`:63`):

```django
  {% endblock content %}

  {% include "inventory/partials/scanner_modal.html" %}

  <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
```

- [ ] **Step 6: Add the camera to the audit console**

In `inventory/templates/inventory/audit_console.html`, add a camera button into the existing scan input-group (after the `<input ... name="code" ...>` at `:49-50`, before the submit button at `:51`):

```django
        <button class="btn btn-outline-light" type="button" id="audit-camera-btn"
                data-scan-mode="feed" data-scan-target="#scan-form" title="Scan with camera">
          <i class="bi bi-camera"></i>
        </button>
        <button class="btn btn-primary" type="submit">Scan</button>
```

Then add an `extra_scripts` block at the end of `audit_console.html` (after `{% endblock content %}`):

```django
{% block extra_scripts %}
  <script src="{% static 'inventory/js/vendor/zxing-browser.min.js' %}"></script>
  <script src="{% static 'inventory/js/scanner.js' %}"></script>
  <script src="{% static 'inventory/js/quick_move.js' %}"></script>
{% endblock extra_scripts %}
```

`audit_console.html` already `{% extends %}` base; add `{% load static %}` after the extends line if not present.

- [ ] **Step 7: Verify nothing broke (no JS test, run the existing suites + check)**

Run: `~/.venvs/inventory/bin/python manage.py check`
Expected: `System check identified no issues`.

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.QuickMoveViewTests inventory.tests.AuditViewTests -v 2`
Expected: PASS (the camera markup is inert server-side).

- [ ] **Step 8: Commit**

```bash
git add inventory/static/inventory/js/vendor/zxing-browser.min.js inventory/static/inventory/js/scanner.js inventory/static/inventory/js/quick_move.js inventory/templates/inventory/partials/scanner_modal.html inventory/templates/inventory/base.html inventory/templates/inventory/audit_console.html
git commit -m "feat: in-app zxing camera scanner for quick-move + audit (Phase 12)"
```

---

## Task 6: PWA manifest + icons

**Files:**
- Create: `inventory/static/inventory/images/icon-192.png`, `icon-512.png` (generated)
- Create: `inventory/static/inventory/manifest.json`
- Modify: `inventory/templates/inventory/base.html` (manifest + theme-color links)
- Test: `inventory/tests.py`

- [ ] **Step 1: Generate the PWA icons from the existing app icon**

Run (one-off generation with Pillow, already installed):

```bash
~/.venvs/inventory/bin/python -c "
from PIL import Image
src = Image.open('inventory/static/inventory/images/invIcon.png').convert('RGBA')
for size in (192, 512):
    src.resize((size, size), Image.LANCZOS).save(
        f'inventory/static/inventory/images/icon-{size}.png')
print('icons written')
"
ls -1 inventory/static/inventory/images/icon-*.png
```

Expected: `icons written` and both files listed.

- [ ] **Step 2: Create the manifest**

Create `inventory/static/inventory/manifest.json`:

```json
{
  "name": "Inventory Manager",
  "short_name": "Inventory",
  "start_url": "/",
  "scope": "/",
  "display": "standalone",
  "background_color": "#ffffff",
  "theme_color": "#3459e6",
  "icons": [
    {
      "src": "/static/inventory/images/icon-192.png",
      "sizes": "192x192",
      "type": "image/png",
      "purpose": "any maskable"
    },
    {
      "src": "/static/inventory/images/icon-512.png",
      "sizes": "512x512",
      "type": "image/png",
      "purpose": "any maskable"
    }
  ]
}
```

- [ ] **Step 3: Write the failing test**

Append to `inventory/tests.py`:

```python
class PwaManifestTests(TestCase):
    def test_manifest_is_valid_and_complete(self):
        import json
        from pathlib import Path

        from django.conf import settings

        path = (
            Path(settings.BASE_DIR)
            / "inventory/static/inventory/manifest.json"
        )
        data = json.loads(path.read_text())
        self.assertEqual(data["start_url"], "/")
        self.assertEqual(data["display"], "standalone")
        sizes = {icon["sizes"] for icon in data["icons"]}
        self.assertEqual(sizes, {"192x192", "512x512"})

    def test_icons_exist(self):
        from pathlib import Path

        from django.conf import settings

        base = Path(settings.BASE_DIR) / "inventory/static/inventory/images"
        self.assertTrue((base / "icon-192.png").exists())
        self.assertTrue((base / "icon-512.png").exists())
```

- [ ] **Step 4: Run test to verify it passes (files already created)**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.PwaManifestTests -v 2`
Expected: PASS (2 tests). *(If `settings.BASE_DIR` points one level up such that the path misses, adjust the path to match `BASE_DIR`; confirm with `~/.venvs/inventory/bin/python -c "from django.conf import settings; print(settings.BASE_DIR)"` and fix the test's relative path before committing.)*

- [ ] **Step 5: Link the manifest in base.html**

In `inventory/templates/inventory/base.html`, inside `<head>`, after the apple-touch-icon link (`:11`):

```django
  <link rel="apple-touch-icon" href="{% static 'inventory/images/apple-touch-icon.png' %}">
  <link rel="manifest" href="{% static 'inventory/manifest.json' %}">
  <meta name="theme-color" content="#3459e6">
  <meta name="apple-mobile-web-app-capable" content="yes">
```

- [ ] **Step 6: Commit**

```bash
git add inventory/static/inventory/manifest.json inventory/static/inventory/images/icon-192.png inventory/static/inventory/images/icon-512.png inventory/templates/inventory/base.html inventory/tests.py
git commit -m "feat: installable PWA manifest + icons (Phase 12)"
```

---

## Task 7: Nav link, full validation, and docs

**Files:**
- Modify: `inventory/templates/inventory/navigation.html:32-36`
- Modify: `readme.md`, `todo.md`

- [ ] **Step 1: Add the Move nav link**

In `inventory/templates/inventory/navigation.html`, add a list item before the Audit link (`:32`):

```django
					<li class="nav-item">
						<a class="nav-link" href="{% url 'quick_move' %}">
							<i class="bi bi-arrow-left-right" aria-hidden="true"></i> Move
						</a>
					</li>
					<li class="nav-item">
						<a class="nav-link" href="{% url 'audit_console' %}">
```

- [ ] **Step 2: Run the full inventory test suite**

Run: `~/.venvs/inventory/bin/python manage.py test inventory -v 1`
Expected: PASS, `OK`, total count = prior 304 + the new tests (≈ 330). Zero failures.

- [ ] **Step 3: Run Django checks**

Run: `~/.venvs/inventory/bin/python manage.py check && ~/.venvs/inventory/bin/python manage.py makemigrations --dry-run --check`
Expected: `System check identified no issues`; the migration check exits 0 with **no** pending migrations (Phase 12 added no model fields).

- [ ] **Step 4: Run pre-commit on the changed files**

Run:
```bash
~/.venvs/inventory/bin/pre-commit run --files \
  inventory/quickmove.py inventory/views.py inventory/urls.py inventory/barcode_utils.py \
  inventory/admin.py inventory/tests.py inventory_management_site/settings.py \
  inventory/templates/inventory/quick_move.html \
  inventory/templates/inventory/partials/quick_move_body.html \
  inventory/templates/inventory/partials/scanner_modal.html \
  inventory/templates/inventory/base.html inventory/templates/inventory/navigation.html \
  inventory/templates/inventory/audit_console.html \
  inventory/static/inventory/js/scanner.js inventory/static/inventory/js/quick_move.js
```
Expected: all hooks Pass (black/ruff may reformat — re-stage and re-run if so). Note: `zxing-browser.min.js` is vendored; if a hook flags it, add it to the relevant exclude or skip with `--no-verify` on the final commit only if necessary.

- [ ] **Step 5: Update docs**

In `todo.md`, mark Phase 12.2 and 12.3 items `[x]` (the `## Phase 12` section and the `### 12.2`/`### 12.3` blocks), and fix the inaccurate PWA claim in `### 12.3` ("manifest + icons already exist" → note the manifest+service-worker were created in this work, service worker intentionally omitted).

In `readme.md`, add a one-line feature bullet for Quick Move + phone scanning if the feature list is user-facing (check first; only if it warrants it).

- [ ] **Step 6: Commit and push**

```bash
git add inventory/templates/inventory/navigation.html todo.md readme.md
git commit -m "feat: Move nav link + docs for Phase 12 quick-move & scanning"
git push -u origin feat/phase-12-quick-move
```

- [ ] **Step 7: Open the PR**

```bash
gh pr create --base master --head feat/phase-12-quick-move \
  --title "feat: quick scan-to-move + phone camera/QR + PWA (Phase 12)" \
  --body "Implements todo.md Phase 12.2 + 12.3. See docs/superpowers/specs/2026-06-10-phase-12-quick-move-design.md.

Flags for review: new \`qrcode\` dependency (image rebuild); \`SITE_BASE_URL\` added to docker-compose web env (confirm host); \`https://inventory.home.collerco.com\` added to CSRF_TRUSTED_ORIGINS. Camera needs HTTPS (now live) — verify on a phone; QR-on-17x54 legibility is a real-print check (size up the label profile if tight)."
```

---

## Self-Review

**1. Spec coverage** (against `2026-06-10-phase-12-quick-move-design.md`):
- §4 service module → Task 3. ✓
- §4 CBVs + URLs + templates → Task 4. ✓
- §5 state machine (idle/item/container/full, evict-deplete + evict-rehome chain, deplete-on-card, drying error-block, sticky-preserve) → Task 3 (logic) + Task 4 (view/templates/tests). ✓
- §6 scanner.js + zxing vendor + secure-context gate + audit reuse → Task 5. ✓
- §7 QR labels (qrcode dep, URL content, layout, profile flag, INV + LOC callers) → Task 2. ✓
- §8 PWA manifest-only + icons + base.html links → Task 6. ✓
- §9 SITE_BASE_URL + CSRF origin + compose env + qrcode dep flag + no migration → Tasks 1, 2, 7. ✓
- §10 testing (service, views, labels, manifest; no camera tests) → Tasks 2,3,4,6. ✓
- §11 out of scope (no service worker, no omni-box, no HTTPS infra) → respected. ✓

**2. Placeholder scan:** no TBD/TODO; every code step shows complete code; the two "adjust if…" notes (compose `docker` availability, `BASE_DIR` path) are real environment guards with concrete fallback commands, not deferred work.

**3. Type/name consistency:** `resolve_active_item`, `resolve_destination`→`Destination(location, needs_slot_pick)`, `attempt_move`→`MoveOutcome(kind, result, occupant, message)`, `evict_and_place(...)→(result, evicted)`, `occupant_at`, `QuickMoveError` are used identically across Task 3 (service), Task 3 tests, and Task 4 (views). View action vocabulary (`reset`/`show_item`/`deplete_active`/`evict` + `deplete_old`) matches between `QuickMoveScanView` and the body partial's hidden inputs. `create_label_image(..., qr_value=)`, `label_qr_url`, `LabelProfile.include_qr` consistent across Task 2 impl, callers, and tests. Template/JS contract: `data-scan-target="#qm-scan-form"`/`data-scan-mode` consumed by `quick_move.js`; `#scanner-modal`/`#scanner-video` consumed by `scanner.js` and provided by `scanner_modal.html`. ✓
