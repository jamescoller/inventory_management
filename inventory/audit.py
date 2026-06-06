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


def visit_location(session, location, previous_location=None):
    """Set focus to ``location``, auto-closing ``previous_location`` if different.

    Returns the location. Raises :class:`AuditError` for container kinds.
    """
    if location.is_container:
        raise AuditError(
            f"{location.name} is a container, not a scannable storage spot."
        )
    if previous_location and previous_location.id != location.id:
        close_location(session, previous_location)
    AuditEvent.objects.create(
        session=session, location=location, action=AuditEvent.Action.VISITED
    )
    return location


def scan_item(session, location, item):
    """Reconcile a scanned item against the active location.

    Returns the :class:`AuditEvent.Action` taken. Raises :class:`AuditError` if no
    location is active or the item is a unit container.
    """
    if location is None:
        raise AuditError("Scan a location barcode first.")
    if location.is_container:
        raise AuditError(f"{location.name} is a container, not a storage spot.")
    if _is_unit_item(item):
        raise AuditError(
            f"{item.product.name} is a tracked unit (AMS/dryer/printer), "
            "not slot contents — it isn't audited this way."
        )

    sticky = item.status in InventoryItem.STICKY_STATUSES

    if item.location_id == location.id and not sticky:
        # Already here and in a normal state: confirm presence (deduplicated).
        present = AuditEvent.objects.filter(
            session=session,
            item=item,
            location=location,
            action=AuditEvent.Action.SCANNED_PRESENT,
        ).exists()
        if not present:
            AuditEvent.objects.create(
                session=session,
                item=item,
                location=location,
                action=AuditEvent.Action.SCANNED_PRESENT,
            )
        return AuditEvent.Action.SCANNED_PRESENT

    # Item is elsewhere, or is reviving from a sticky status -> bring it here.
    revived = sticky
    item.location = location
    item.date_depleted = None
    item.date_sold = None
    new_status = item.update_status()
    if new_status:
        item.status = new_status
    item._skip_status_from_location = True  # status set explicitly above
    item.save()

    action = AuditEvent.Action.REVIVED if revived else AuditEvent.Action.MOVED_IN
    AuditEvent.objects.create(
        session=session, item=item, location=location, action=action
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
    new_status = item.update_status()
    if new_status:
        item.status = new_status
    item._skip_status_from_location = True  # status set explicitly above
    item.save()
    AuditEvent.objects.create(
        session=session, item=item, location=location, action=AuditEvent.Action.ADDED
    )
    return "added", item


def close_location(session, location):
    """Idempotently reconcile a location.

    Flags every item still recorded at ``location`` but not scanned present/moved-in
    this session as UNKNOWN (keeping its location). Returns the list of newly flagged
    items. A no-op if the location was already closed this session.
    """
    if location is None or location.is_container:
        return []
    if AuditEvent.objects.filter(
        session=session, location=location, action=AuditEvent.Action.CLOSED
    ).exists():
        return []

    scanned_ids = list(
        AuditEvent.objects.filter(
            session=session, location=location, action__in=PRESENT_ACTIONS
        ).values_list("item_id", flat=True)
    )

    flagged = []
    with transaction.atomic():
        unscanned = InventoryItem.objects.filter(location=location).exclude(
            id__in=scanned_ids
        )
        for item in unscanned:
            item.status = InventoryItem.Status.UNKNOWN
            item._skip_status_from_location = True
            item.save()  # sticky guard keeps location; UNKNOWN is not terminal
            AuditEvent.objects.create(
                session=session,
                item=item,
                location=location,
                action=AuditEvent.Action.FLAGGED_UNKNOWN,
            )
            flagged.append(item)
        AuditEvent.objects.create(
            session=session, location=location, action=AuditEvent.Action.CLOSED
        )
    return flagged


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


def finalize(session, active_location=None):
    """Close any open location, then deplete the session's still-UNKNOWN items.

    Returns the list of depleted items and marks the session FINALIZED.
    """
    if active_location is not None:
        close_location(session, active_location)

    depleted = []
    with transaction.atomic():
        for item in session_unknown_items(session):
            item.mark_depleted()  # status DEPLETED, clears location + date
            item._skip_status_from_location = True
            item.save()
            depleted.append(item)
        session.mark_finished(AuditSession.State.FINALIZED)
    return depleted


def abandon(session):
    """End the session without depleting; UNKNOWN items remain for manual cleanup."""
    session.mark_finished(AuditSession.State.ABANDONED)
