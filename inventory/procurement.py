"""Procurement / receiving service for purchase orders.

Mirrors :mod:`inventory.audit`: the logic lives here as small functions plus a
:class:`ProcurementError`; the views (a thin :class:`ReceivingScanView`) call in
and stay lean. State mutations to :class:`InventoryItem` go through the
:mod:`inventory.items` move service — never an ad-hoc ``save()`` + flag dance.

Receiving flow (mirrors the audit ``add_or_queue_upc`` gesture, bound to a PO):

1. Resolve the catalog :class:`Product` from a scanned UPC.
2. Find the matching open :class:`PurchaseOrderLine` (same product,
   ``qty_received < qty_ordered``); ambiguity -> :class:`ProcurementError`.
3. If the line is ``track_individually``: mint an :class:`InventoryItem` into the
   receiving rack via :func:`items.move_to`, stamp ``unit_cost``/``source_line``
   from the line, and bump the line's ``qty_received``. (Label printing stays in
   the view, like :class:`~inventory.views.AddInventoryView`.)
4. Else (cost-only consumable): bump ``qty_received`` only — no item is minted.
5. Recompute the PO status (all lines full -> RECEIVED, some -> PARTIAL).

Spend reporting unions tracked items' ``unit_cost`` with cost-only lines' totals;
see :func:`spend_summary`.
"""

import logging
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.db.models import F, Sum

from . import items
from .models import (
    InventoryItem,
    Product,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseReceiptLine,
)

logger = logging.getLogger("inventory")


class ProcurementError(Exception):
    """User-facing error raised when a receiving scan cannot be processed."""


@dataclass
class ReceiveResult:
    """Outcome of a single receiving scan.

    Attributes:
        line: The :class:`PurchaseOrderLine` the scan was applied to.
        item: The minted :class:`InventoryItem` for tracked goods, else None.
        tracked: True if an item was minted (``line.track_individually``).
        message: A user-facing summary of what happened.
    """

    line: PurchaseOrderLine
    item: InventoryItem | None
    tracked: bool
    message: str


def open_lines_for(order, product=None):
    """Open lines on ``order`` (``qty_received < qty_ordered``).

    Filtered to ``product`` when given. Ordered by id so the lowest line fills
    first when several match the same product.
    """
    qs = order.lines.filter(qty_received__lt=F("qty_ordered"))
    if product is not None:
        qs = qs.filter(product=product)
    return qs.order_by("id")


def _match_open_line(order, product):
    """Return the single open line on ``order`` for ``product``.

    Raises :class:`ProcurementError` when there is no open line, or when more
    than one open line matches (the operator must disambiguate by hand).
    """
    open_lines = list(open_lines_for(order, product))
    if not open_lines:
        raise ProcurementError(
            f"{product.name} has no open line on this order (already fully received?)."
        )
    if len(open_lines) > 1:
        raise ProcurementError(
            f"{product.name} matches multiple open lines on this order; "
            "receive against a specific line in the admin."
        )
    return open_lines[0]


@transaction.atomic
def receive_line_unit(receipt, line, *, location):
    """Receive one unit against ``line`` as part of ``receipt``.

    For a tracked line, mints an :class:`InventoryItem` at ``location`` via
    :func:`items.move_to` (stamping ``unit_cost``/``source_line`` from the line)
    and returns it; for a cost-only line, mints nothing. Either way the line's
    ``qty_received`` is bumped by one, a :class:`PurchaseReceiptLine` is recorded,
    and the PO status is recomputed.

    The caller (view) owns label printing for the tracked branch.
    """
    item = None
    if line.track_individually:
        item = InventoryItem(
            product=line.product,
            unit_cost=line.unit_cost,
            source_line=line,
        )
        # move_to is the single placement chokepoint: it sets the location,
        # derives status from the rack's default, and saves. The receiving rack
        # is a leaf (not a container) so the move guard passes.
        result = items.move_to(item, location, skip_drying_check=True)
        if not result.ok:
            raise ProcurementError(result.message)
        item = result.item

    line.qty_received = F("qty_received") + 1
    line.save(update_fields=["qty_received"])
    line.refresh_from_db(fields=["qty_received"])

    PurchaseReceiptLine.objects.create(receipt=receipt, order_line=line, qty_received=1)
    line.order.recompute_status()

    if item is not None:
        msg = f"Received {line.product.name} (INV-{item.pk}) at {location.name}."
    else:
        msg = f"Received 1x {line.product.name} (cost-only)."
    return ReceiveResult(line=line, item=item, tracked=item is not None, message=msg)


def receive_scan(receipt, upc, location):
    """Resolve ``upc`` to an open line on the receipt's order and receive one unit.

    Mirrors the audit UPC gesture. Raises :class:`ProcurementError` when the UPC
    is unknown or matches no/ambiguous open line.
    """
    if location is None:
        raise ProcurementError("Set a receiving location first.")
    product = Product.objects.filter(upc=upc).first()
    if product is None:
        raise ProcurementError(
            f"No catalog product has UPC {upc}. Add the product first."
        )
    line = _match_open_line(receipt.order, product)
    return receive_line_unit(receipt, line, location=location)


def reconcile(order):
    """Ordered-vs-received summary for a PO.

    Returns a dict with per-line rows and order-level totals, all from cheap
    Python over the prefetched lines (a PO has few lines):

        {
            "order": <PurchaseOrder>,
            "lines": [{"line", "ordered", "received", "outstanding",
                       "line_total", "received_total"}, ...],
            "qty_ordered", "qty_received", "qty_outstanding",
            "subtotal", "received_value",
        }
    """
    rows = []
    qty_ordered = qty_received = qty_outstanding = 0
    subtotal = received_value = Decimal("0")
    for line in order.lines.select_related("product").all():
        rows.append(
            {
                "line": line,
                "ordered": line.qty_ordered,
                "received": line.qty_received,
                "outstanding": line.qty_outstanding,
                "line_total": line.line_total,
                "received_total": line.received_total,
            }
        )
        qty_ordered += line.qty_ordered
        qty_received += line.qty_received
        qty_outstanding += line.qty_outstanding
        subtotal += line.line_total
        received_value += line.received_total
    return {
        "order": order,
        "lines": rows,
        "qty_ordered": qty_ordered,
        "qty_received": qty_received,
        "qty_outstanding": qty_outstanding,
        "subtotal": subtotal,
        "received_value": received_value,
    }


def spend_summary():
    """Total spend, unioning tracked-item costs with cost-only line totals.

    Tracked goods carry their own ``unit_cost`` on each :class:`InventoryItem`
    (so the figure reflects what physically exists, surviving PO edits). Cost-only
    consumables mint no items, so their spend is taken from the line
    (``qty_received * unit_cost``) — counting *received* units, not ordered, so a
    partially-received consumable line isn't over-counted. Returns a dict:

        {"tracked_spend", "consumable_spend", "total_spend",
         "tracked_count", "consumable_lines"}

    All sums are DB aggregations.
    """
    tracked = InventoryItem.objects.exclude(unit_cost__isnull=True).aggregate(
        total=Sum("unit_cost"), count=Sum(1)
    )
    tracked_spend = tracked["total"] or Decimal("0")
    tracked_count = tracked["count"] or 0

    consumable_lines = PurchaseOrderLine.objects.filter(
        track_individually=False, qty_received__gt=0
    )
    consumable_spend = consumable_lines.aggregate(
        total=Sum(F("qty_received") * F("unit_cost"))
    )["total"] or Decimal("0")

    return {
        "tracked_spend": tracked_spend,
        "consumable_spend": consumable_spend,
        "total_spend": tracked_spend + consumable_spend,
        "tracked_count": tracked_count,
        "consumable_lines": consumable_lines.count(),
    }


def spend_by_supplier():
    """Per-supplier received spend (ordered, received value), for the report table.

    Received value = sum over the supplier's lines of ``qty_received *
    unit_cost`` (tracked and cost-only alike — both have a per-line unit_cost),
    so it matches what was actually delivered. DB aggregation grouped by supplier.
    """
    return (
        PurchaseOrder.objects.values("supplier__id", "supplier__name")
        .annotate(
            ordered_value=Sum(F("lines__qty_ordered") * F("lines__unit_cost")),
            received_value=Sum(F("lines__qty_received") * F("lines__unit_cost")),
        )
        .order_by("supplier__name")
    )
