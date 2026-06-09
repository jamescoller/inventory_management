"""Move / deplete / status service for :class:`InventoryItem`.

This is the **single chokepoint** for changing an item's location or status. It
owns the ``_skip_status_from_location`` transient flag and the sticky-status
semantics that were previously copy-pasted across :mod:`inventory.audit`,
:class:`~inventory.views.BulkUpdateView`, and
:meth:`~inventory.admin.InventoryItemAdmin.mark_depleted`.

Design mirrors :mod:`inventory.audit`: pure-ish functions plus a small
:class:`Result` type; callers (views/audit/admin) stay thin and never touch the
model's transient flags directly.

The model-level guard in :meth:`InventoryItem.save` stays the source of truth for
sticky statuses (``DEPLETED``/``SOLD``/``UNKNOWN`` never silently recompute from a
destination's ``default_status``). This module simply drives that mechanism
consistently:

- :func:`move_to` — the **one** place that sets ``_skip_status_from_location``
  (when an explicit ``status=`` is supplied). With ``status=None`` it lets the
  model derive status from ``location.default_status`` via the existing save path.
- :func:`deplete` — wraps :meth:`InventoryItem.mark_depleted` + save.
- :func:`set_status` — the single explicit-status setter (sticky-safe).

The move guard (container rejection + slot capacity) lives in :func:`move_to`, so
no view/audit code re-implements it.
"""

from dataclasses import dataclass

from .models import InventoryItem

# Statuses that mean the item no longer physically occupies a location. Used to
# decide whether an item counts against a destination's capacity. UNKNOWN is
# *not* here: an item flagged unknown is still physically sitting in its slot.
TERMINAL_STATUSES = (InventoryItem.Status.DEPLETED, InventoryItem.Status.SOLD)


@dataclass
class Result:
    """Outcome of a move/deplete/set_status operation.

    Attributes:
        ok: True if the operation was applied and the item saved.
        item: The (possibly mutated, saved) :class:`InventoryItem`.
        message: A user-facing message — the rejection reason when ``ok`` is
            False, otherwise empty.
        drying_warning: For :func:`move_to`, the
            ``(level, message, needs_ack)`` tuple from
            :meth:`InventoryItem.filament_drying_warning`, or None. Callers flash
            it exactly as the edit view does today.
        reason: Free-text reason threaded through :func:`deplete` (no schema in
            v1; surfaced here for callers/history to stash).
    """

    ok: bool
    item: InventoryItem
    message: str = ""
    drying_warning: tuple[str, str, bool] | None = None
    reason: str = ""


def _active_count_at(location, *, exclude_pk=None):
    """Count items currently at ``location`` with a non-terminal status.

    ``exclude_pk`` skips the item being moved so re-placing an item already in the
    slot never trips its own capacity.
    """
    qs = InventoryItem.objects.filter(location=location).exclude(
        status__in=TERMINAL_STATUSES
    )
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    return qs.count()


def _check_move_guard(item, location, *, enforce_capacity=True):
    """Validate that ``item`` may be placed at ``location``.

    Returns a rejection message string, or None if the move is allowed. This is
    the single home for the two guards previously duplicated in views/audit:
    container rejection and slot-capacity rejection.

    ``enforce_capacity=False`` skips only the capacity check (audit reconcile
    reflects physical reality: if a scan says the item is there, capacity must
    yield). The container guard always applies.
    """
    if location is None:
        return None  # clearing a location (e.g. deplete) is always allowed

    if location.is_container:
        return f"{location.name} is a container and can't hold items."

    capacity = location.capacity
    if enforce_capacity and capacity is not None:
        occupied = _active_count_at(location, exclude_pk=item.pk)
        if occupied >= capacity:
            return (
                f"{location.name} is full "
                f"({occupied}/{capacity}) — nothing can be added until something leaves."
            )
    return None


def move_to(
    item, location, *, status=None, skip_drying_check=False, enforce_capacity=True
):
    """Move ``item`` to ``location``, the single chokepoint for placement.

    Behavior:
        - Enforces the move guard (container + slot-capacity rejection). On
          rejection the item is **not** mutated or saved and a
          ``Result(ok=False, message=...)`` is returned; callers must check
          ``result.ok``.
        - Sets ``item.location = location``.
        - If ``status`` is given, sets it explicitly and bypasses the model's
          location->status derivation (via ``_skip_status_from_location``). This
          is also how a sticky item is intentionally revived.
        - If ``status`` is None, leaves the model's existing mechanism to derive
          status from ``location.default_status`` (sticky statuses still skip the
          recompute, per the model guard).
        - Unless ``skip_drying_check``, computes
          ``item.filament_drying_warning(location)`` and returns it in the Result
          so views can flash it exactly as today. (This is advisory only here; the
          edit view remains responsible for blocking on an ``error``-level
          warning before calling :func:`move_to`.)
        - Saves the item.

    Args:
        item: The :class:`InventoryItem` to move.
        location: Destination :class:`Location` (a leaf), or None to clear.
        status: Optional explicit :class:`InventoryItem.Status` to set.
        skip_drying_check: When True, do not compute/return a drying warning.
        enforce_capacity: When False, skip the slot-capacity guard (the audit
            reconcile path passes False: a physical scan overrides capacity). The
            container guard always applies.

    Returns:
        Result: ``ok=True`` with the saved item (and any ``drying_warning``) on
        success; ``ok=False`` with ``message`` on a guard rejection.
    """
    rejection = _check_move_guard(item, location, enforce_capacity=enforce_capacity)
    if rejection is not None:
        return Result(ok=False, item=item, message=rejection)

    drying_warning = None
    if location is not None and not skip_drying_check:
        drying_warning = item.filament_drying_warning(location)

    item.location = location
    if status is not None:
        item.status = status
        # We chose the status explicitly — bypass the model's location-derived
        # recompute (this is also the only sanctioned way to revive a sticky item).
        item._skip_status_from_location = True
    # When status is None the model derives it from location.default_status on
    # save (sticky statuses are skipped by the model-level guard).
    item.save()

    return Result(ok=True, item=item, drying_warning=drying_warning)


def deplete(item, *, reason=""):
    """Mark ``item`` DEPLETED (terminal), clearing its location.

    Wraps :meth:`InventoryItem.mark_depleted` (sets DEPLETED, clears location, sets
    ``date_depleted``) + save with the correct sticky semantics. ``reason`` is
    accepted for future use (no schema for it in v1) and echoed back on the
    Result for callers/history to stash.
    """
    item.mark_depleted()
    # mark_depleted already set a sticky status; the flag makes the intent explicit
    # and keeps deplete from depending on save-order subtleties.
    item._skip_status_from_location = True
    item.save()
    return Result(ok=True, item=item, reason=reason)


def set_status(item, status):
    """Set ``item.status`` explicitly without deriving from its location.

    The single sanctioned setter: it sets ``_skip_status_from_location`` so the
    model never recomputes status from the current location, then saves. SOLD and
    DEPLETED still clear the location via the model's ``mark_*`` hooks on save.
    """
    item.status = status
    item._skip_status_from_location = True
    item.save()
    return Result(ok=True, item=item)
