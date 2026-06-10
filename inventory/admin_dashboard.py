"""Admin landing-page dashboard for django-unfold.

``dashboard_callback`` is wired via ``UNFOLD["DASHBOARD_CALLBACK"]`` and runs on
every render of ``templates/admin/index.html``. It injects a list of live KPI
cards. Each query is a single aggregate/count and guards against empty tables
(``Sum`` returns ``None`` → coalesced to 0).
"""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum

from .models import InventoryItem, MaintenanceEvent, PrinterState


def _spend_on_hand() -> Decimal:
    """Sum of ``unit_cost`` over on-hand items.

    On-hand == active == not DEPLETED and not SOLD (matches the "active" set used
    by the low-stock alerts). UNKNOWN/NEW/IN_USE/DRYING/STORED items are all
    physically present, so their cost counts. ``unit_cost`` is nullable (only
    stamped for procurement-received items); NULLs are ignored by ``Sum``.
    """
    total = InventoryItem.objects.exclude(
        status__in=[InventoryItem.Status.DEPLETED, InventoryItem.Status.SOLD]
    ).aggregate(total=Sum("unit_cost"))["total"] or Decimal("0")
    return total


def _low_stock_count() -> int:
    """Number of SKUs flagged low/out-of-stock by the public dashboard logic."""
    # Imported lazily: views.py imports heavy modules and the dashboard callback
    # runs at request time, so this keeps admin import-time cost down and avoids
    # any import cycle between admin and views.
    from .views import _build_low_stock_alerts

    return len(_build_low_stock_alerts())


def _open_faults() -> int:
    return MaintenanceEvent.objects.filter(resolved=False).count()


def _printing_now() -> int:
    return PrinterState.objects.filter(gcode_state="RUNNING").count()


def dashboard_callback(request, context):
    """Add live KPI cards to the Unfold admin index context.

    Returns the (mutated) context — Unfold expects the callback to return it.
    """
    spend = _spend_on_hand()

    context["kpi_cards"] = [
        {
            "title": "Spend on hand",
            "value": f"${spend:,.2f}",
            "icon": "payments",
            "description": "Total unit cost of active inventory",
        },
        {
            "title": "Low stock",
            "value": _low_stock_count(),
            "icon": "inventory_2",
            "description": "SKUs at or below the reorder threshold",
        },
        {
            "title": "Open faults",
            "value": _open_faults(),
            "icon": "build",
            "description": "Unresolved maintenance events",
        },
        {
            "title": "Printing now",
            "value": _printing_now(),
            "icon": "print",
            "description": "Printers currently running a job",
        },
    ]
    return context
