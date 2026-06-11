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
            raise QuickMoveError(
                f"Unrecognized code {raw!r}. Scan an item (INV-…/QR)."
            ) from None
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
            raise QuickMoveError(str(exc)) from exc
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
