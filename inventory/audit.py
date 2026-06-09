"""
Reconciliation state machine for inventory-audit mode.

The auditor scans a location barcode (``LOC-<pk>``) to set focus, then scans the
item tags (``INV-<pk>``) physically present there. Reconciliation is *per-location
immediate*:

- Scanning an item already at the active location confirms it present.
- Scanning an item recorded elsewhere moves it to the active location (reviving it
  if it was UNKNOWN/DEPLETED/SOLD).
- Closing a location (explicitly, automatically when focus moves, or at finalize)
  flags any item still recorded there but not scanned this session as
  :attr:`InventoryItem.Status.UNKNOWN`, keeping its location.
- Finalizing confirms the session's still-UNKNOWN items as DEPLETED.

All durable state lives in :class:`AuditEvent` rows; the *active location* is
ephemeral UI focus held in the request session by the views. Every mutation here is
idempotent so the explicit/auto/finalize close paths can overlap safely.
"""

import logging

from django.db import transaction

from . import items
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

logger = logging.getLogger("inventory")

# Actions that mean "the item was physically accounted for at a location".
PRESENT_ACTIONS = (
    AuditEvent.Action.SCANNED_PRESENT,
    AuditEvent.Action.MOVED_IN,
    AuditEvent.Action.ADDED,
)


class AuditError(Exception):
    """User-facing error raised when a scan cannot be processed."""


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


def start_session(user):
    """Open a new audit session, refusing if one is already active."""
    if AuditSession.active():
        raise AuditError("An audit is already in progress.")
    owner = user if (user and user.is_authenticated) else None
    return AuditSession.objects.create(user=owner)


def _is_unit_item(item):
    """True if this item is itself a physical AMS/dryer/printer unit, or is linked as
    a slot's ``unit`` — such items are containers and must never be moved into a slot.
    """
    if isinstance(item.product, (AMS, Dryer, Printer)):
        return True
    return Location.objects.filter(unit=item).exists()


def focus_leaves(location):
    """The assignable leaf locations reconciled when ``location`` is focused.

    A leaf location is itself; a *container* (AMS/dryer/rack) expands to its
    assignable child slots so the whole unit can be audited at once. Ordered by
    slot index so a move-in lands in the lowest slot.
    """
    if location.is_container:
        return list(
            location.children.filter(kind__in=Location.ASSIGNABLE_KINDS).order_by(
                "slot_index", "name"
            )
        )
    return [location]


def resolve_serial(value):
    """Resolve a scanned serial number to the :class:`Location` to focus.

    The serial belongs to a tracked unit's :class:`InventoryItem`. We follow the
    ``Location.unit`` links from that item to its slots: an AMS/dryer focuses the
    whole unit (its parent container, audited slot-by-slot together); a single-slot
    unit such as a printer focuses that leaf directly.

    Note: serials are matched case-insensitively. A purely numeric scan is treated
    as a UPC by :func:`parse_code` and never reaches here, so serials must contain
    at least one non-digit (Bambu unit serials do). Raises :class:`AuditError` when
    the serial is unknown, ambiguous, or not linked to any location.
    """
    items = list(
        InventoryItem.objects.filter(serial_number__iexact=value).exclude(
            serial_number=""
        )
    )
    if not items:
        raise AuditError(f"No tracked unit has serial {value!r}.")
    if len(items) > 1:
        raise AuditError(f"Serial {value!r} matches multiple items; scan a LOC code.")

    item = items[0]
    slot_locs = list(Location.objects.filter(unit=item).select_related("parent"))
    if not slot_locs:
        raise AuditError(
            f"Serial {value!r} is a known unit but isn't linked to any location. "
            "Link it in the admin or scan the LOC barcode."
        )

    # Prefer the shared parent container so the whole unit audits together.
    parent_ids = {loc.parent_id for loc in slot_locs if loc.parent_id}
    parents = list(
        Location.objects.filter(id__in=parent_ids, kind__in=Location.CONTAINER_KINDS)
    )
    if len(parents) == 1:
        return parents[0]
    if len(slot_locs) == 1:
        return slot_locs[0]
    raise AuditError(
        f"Serial {value!r} maps to several locations; scan the specific LOC barcode."
    )


def visit_location(session, location, previous_location=None):
    """Set focus to ``location``, auto-closing ``previous_location`` if different.

    ``location`` may be a leaf or a container (the latter audits all its slots at
    once). Returns the location. Raises :class:`AuditError` if a container has no
    auditable slots.
    """
    if previous_location and previous_location.id != location.id:
        close_location(session, previous_location)
    if location.is_container and not focus_leaves(location):
        raise AuditError(f"{location.name} has no storage slots to audit.")
    AuditEvent.objects.create(
        session=session, location=location, action=AuditEvent.Action.VISITED
    )
    return location


def scan_item(session, location, item):
    """Reconcile a scanned item against the active focus (a leaf or whole unit).

    Returns the :class:`AuditEvent.Action` taken. Raises :class:`AuditError` if no
    location is active or the item is a unit container.
    """
    if location is None:
        raise AuditError("Scan a location barcode first.")
    if _is_unit_item(item):
        raise AuditError(
            f"{item.product.name} is a tracked unit (AMS/dryer/printer), "
            "not slot contents — it isn't audited this way."
        )

    leaves = focus_leaves(location)
    leaf_ids = {leaf.id for leaf in leaves}
    if not leaf_ids:
        raise AuditError(f"{location.name} has no storage slots to audit.")

    sticky = item.status in InventoryItem.STICKY_STATUSES

    if item.location_id in leaf_ids and not sticky:
        # Already in the focused unit and in a normal state: confirm presence at the
        # specific slot it sits in (deduplicated).
        present = AuditEvent.objects.filter(
            session=session,
            item=item,
            location_id=item.location_id,
            action=AuditEvent.Action.SCANNED_PRESENT,
        ).exists()
        if not present:
            AuditEvent.objects.create(
                session=session,
                item=item,
                location_id=item.location_id,
                action=AuditEvent.Action.SCANNED_PRESENT,
            )
        return AuditEvent.Action.SCANNED_PRESENT

    # Item is elsewhere, or reviving from a sticky status -> bring it into the unit.
    # For a multi-slot unit it lands in the lowest slot; correct the slot later if
    # needed.
    target = leaves[0]
    revived = sticky
    # Reviving clears terminal timestamps so the item rejoins normal inventory.
    item.date_depleted = None
    item.date_sold = None
    # Derive the destination's default status explicitly so a sticky item is
    # revived (the model guard would otherwise keep it sticky). ``update_status``
    # reads ``item.location``, so point it at the target first. ``items.move_to``
    # owns the _skip_status_from_location flag. Capacity is not enforced here: an
    # audit scan reflects physical reality, so it must place the item regardless.
    item.location = target
    items.move_to(
        item,
        target,
        status=item.update_status(),
        skip_drying_check=True,
        enforce_capacity=False,
    )

    action = AuditEvent.Action.REVIVED if revived else AuditEvent.Action.MOVED_IN
    AuditEvent.objects.create(
        session=session, item=item, location=target, action=action
    )
    return action


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
    # Derive the destination's default status explicitly; ``items.move_to`` owns
    # the flag dance and the save. Capacity is not enforced on the audit path.
    items.move_to(
        item,
        location,
        status=item.update_status(),
        skip_drying_check=True,
        enforce_capacity=False,
    )
    AuditEvent.objects.create(
        session=session, item=item, location=location, action=AuditEvent.Action.ADDED
    )
    return "added", item


def close_location(session, location):
    """Idempotently reconcile a focus (a leaf or a whole unit's slots).

    Flags every item still recorded under ``location`` but not scanned
    present/moved-in this session as UNKNOWN (keeping its location). Returns the
    list of newly flagged items. A no-op if it was already closed this session.
    """
    if location is None:
        return []
    leaves = focus_leaves(location)
    leaf_ids = [leaf.id for leaf in leaves]
    if not leaf_ids:
        return []
    if AuditEvent.objects.filter(
        session=session, location=location, action=AuditEvent.Action.CLOSED
    ).exists():
        return []

    scanned_ids = list(
        AuditEvent.objects.filter(
            session=session, location_id__in=leaf_ids, action__in=PRESENT_ACTIONS
        ).values_list("item_id", flat=True)
    )

    flagged = []
    with transaction.atomic():
        unscanned = InventoryItem.objects.filter(location_id__in=leaf_ids).exclude(
            id__in=scanned_ids
        )
        for item in unscanned:
            # UNKNOWN is sticky and not terminal: set_status keeps the location.
            items.set_status(item, InventoryItem.Status.UNKNOWN)
            AuditEvent.objects.create(
                session=session,
                item=item,
                location=item.location,
                action=AuditEvent.Action.FLAGGED_UNKNOWN,
            )
            flagged.append(item)
        # The CLOSED marker is keyed to the focus (leaf or container) for idempotency.
        AuditEvent.objects.create(
            session=session, location=location, action=AuditEvent.Action.CLOSED
        )
    return flagged


def location_present_count(session, location):
    """Distinct items scanned present/moved-in/added under ``location`` this session."""
    leaf_ids = [leaf.id for leaf in focus_leaves(location)]
    return (
        AuditEvent.objects.filter(
            session=session, location_id__in=leaf_ids, action__in=PRESENT_ACTIONS
        )
        .values("item_id")
        .distinct()
        .count()
    )


def session_added_items(session):
    """Items created via an ADDED scan this session that still exist."""
    added_ids = list(
        AuditEvent.objects.filter(
            session=session, action=AuditEvent.Action.ADDED
        ).values_list("item_id", flat=True)
    )
    return (
        InventoryItem.objects.filter(id__in=added_ids)
        .select_related("product", "location")
        .distinct()
    )


def undo_added(session, item):
    """Delete an item that was mistakenly ADDED during this session (e.g. a UPC
    scanned instead of an INV tag). Deleting cascades its audit events.

    Raises :class:`AuditError` if the item wasn't added this session or is linked to
    a location as a tracked unit.
    """
    if not AuditEvent.objects.filter(
        session=session, item=item, action=AuditEvent.Action.ADDED
    ).exists():
        raise AuditError(
            "That item wasn't added during this audit, so it can't be removed here."
        )
    if Location.objects.filter(unit=item).exists():
        raise AuditError("That item is a tracked unit and can't be removed here.")
    item.delete()
    return True


def session_unknown_items(session):
    """Items this session flagged UNKNOWN that are *still* UNKNOWN now.

    Excludes any that were later re-scanned (revived) at another location.
    """
    flagged_ids = list(
        AuditEvent.objects.filter(
            session=session, action=AuditEvent.Action.FLAGGED_UNKNOWN
        ).values_list("item_id", flat=True)
    )
    return (
        InventoryItem.objects.filter(
            id__in=flagged_ids, status=InventoryItem.Status.UNKNOWN
        )
        .select_related("product", "location")
        .distinct()
    )


def finalize(session, active_location=None, keep_unknown_ids=None):
    """Close any open location, then resolve the session's still-UNKNOWN items.

    By default each still-UNKNOWN item is marked DEPLETED. Items whose id is in
    ``keep_unknown_ids`` are intentionally left UNKNOWN ("in limbo") for later
    follow-up — e.g. something found out of place mid-audit. Returns the list of
    depleted items and marks the session FINALIZED.
    """
    if active_location is not None:
        close_location(session, active_location)

    keep = {int(i) for i in (keep_unknown_ids or [])}
    depleted = []
    with transaction.atomic():
        for item in session_unknown_items(session):
            if item.id in keep:
                continue  # left UNKNOWN on purpose
            items.deplete(item)  # status DEPLETED, clears location + date
            depleted.append(item)
        session.mark_finished(AuditSession.State.FINALIZED)
    return depleted


def abandon(session):
    """End the session without depleting; UNKNOWN items remain for manual cleanup."""
    session.mark_finished(AuditSession.State.ABANDONED)
