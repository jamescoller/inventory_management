"""
Maintenance service module — upkeep, faults, and reliability analytics for
machine :class:`InventoryItem`\\s (printers/AMS/dryers).

Follows the audit subsystem's pattern: the logic lives here as pure functions;
thin CBVs (``UnitMaintenanceView``/``MaintenanceLogCreateView``/
``MaintenanceSummaryView``) call it. A :class:`MaintenanceEvent` is the
append-only history; :class:`NozzleConfig` is the live per-printer state. A
hotend swap writes *both* — the history event and the current-state update —
mirroring the audit log-vs-state split.

The reliability report (the "rebuy / refund?" headline ask) is computed with DB
aggregations grouped by machine *model*, never a Python-side table scan.
"""

import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils.timezone import now

from .models import (
    InventoryItem,
    MaintenanceEvent,
    NozzleConfig,
    is_machine_item,
)

logger = logging.getLogger("inventory")


class MaintenanceError(Exception):
    """User-facing error raised when a maintenance action cannot be processed."""


def log_event(unit, *, kind, title, **fields):
    """Record a :class:`MaintenanceEvent` against a machine ``unit``.

    ``fields`` may carry any of ``severity``, ``detail``, ``occurred_at``,
    ``part``, ``part_item``, ``cost``, ``downtime_hours``, ``hms_code``,
    ``resolved``. Raises :class:`MaintenanceError` if ``unit`` is not a machine.
    """
    if not is_machine_item(unit):
        raise MaintenanceError(
            f"{unit.product.name} is not a machine; maintenance cannot be logged."
        )
    return MaintenanceEvent.objects.create(unit=unit, kind=kind, title=title, **fields)


def open_fault(unit, *, title, hms_code="", severity=None, **fields):
    """Open an unresolved FAULT event (the MQTT HMS writer will reuse this path)."""
    if severity is None:
        severity = MaintenanceEvent.Severity.MAJOR
    return log_event(
        unit,
        kind=MaintenanceEvent.Kind.FAULT,
        title=title,
        hms_code=hms_code,
        severity=severity,
        resolved=False,
        **fields,
    )


def resolve_fault(event):
    """Mark an open FAULT resolved. Idempotent."""
    if not event.resolved:
        event.resolved = True
        event.save(update_fields=["resolved"])
    return event


def swap_hotend(
    printer, *, nozzle_diameter_mm=None, nozzle_type="", part=None, **fields
):
    """Record a nozzle/hot-end swap: a ``HOTEND_SWAP`` history event *and* an
    update to the printer's live :class:`NozzleConfig` (created lazily).

    ``fields`` are forwarded to the event (cost, downtime_hours, detail, …).
    Returns ``(event, nozzle_config)``. Raises :class:`MaintenanceError` for a
    non-machine unit.
    """
    when = now()
    with transaction.atomic():
        event = log_event(
            printer,
            kind=MaintenanceEvent.Kind.HOTEND_SWAP,
            title=fields.pop("title", "Hotend / nozzle swap"),
            part=part,
            occurred_at=when,
            **fields,
        )
        config, _ = NozzleConfig.objects.get_or_create(printer=printer)
        if nozzle_diameter_mm is not None:
            config.nozzle_diameter_mm = nozzle_diameter_mm
        if nozzle_type:
            config.nozzle_type = nozzle_type
        config.hotend_changed_at = when
        config.save()
    return event, config


def unit_events(unit):
    """The maintenance timeline for a single unit (newest first)."""
    return (
        MaintenanceEvent.objects.filter(unit=unit)
        .select_related("part")
        .order_by("-occurred_at", "-created_at")
    )


def unit_summary(unit):
    """Aggregate maintenance stats for one unit.

    Returns a dict: ``faults`` (count of FAULT events), ``open_faults``,
    ``total_events``, ``total_cost``, ``total_downtime_hours``.
    """
    agg = MaintenanceEvent.objects.filter(unit=unit).aggregate(
        total_events=Count("id"),
        faults=Count("id", filter=Q(kind=MaintenanceEvent.Kind.FAULT)),
        open_faults=Count(
            "id",
            filter=Q(kind=MaintenanceEvent.Kind.FAULT, resolved=False),
        ),
        total_cost=Sum("cost"),
        total_downtime_hours=Sum("downtime_hours"),
    )
    return {
        "total_events": agg["total_events"] or 0,
        "faults": agg["faults"] or 0,
        "open_faults": agg["open_faults"] or 0,
        "total_cost": agg["total_cost"] or Decimal("0.00"),
        "total_downtime_hours": agg["total_downtime_hours"] or Decimal("0.00"),
    }


def model_reliability():
    """Per-model reliability rollup for the "rebuy / refund?" dashboard.

    Groups every machine :class:`InventoryItem` (printers/AMS/dryers) by its
    product *model* and aggregates fault count, total downtime, maintenance spend,
    and unit fleet size — all via DB aggregations (one query for the fleet, one
    for the maintenance rollup). Derives faults-per-unit and MTBF in days.

    MTBF here = (summed operating age of the fleet in days) / (number of faults).
    Operating age uses ``InventoryItem.date_added`` as the in-service proxy. With
    zero faults MTBF is ``None`` (infinite / not-yet-failed).

    Returns a list of dicts ordered by faults-per-unit descending (worst first),
    each: ``model``, ``ctype`` (printer/ams/dryer), ``units``, ``faults``,
    ``open_faults``, ``total_cost``, ``total_downtime_hours``,
    ``faults_per_unit``, ``mtbf_days``.
    """
    machine_models = ("printer", "ams", "dryer")

    # Fleet: count of owned units + summed in-service age, grouped by model.
    fleet = (
        InventoryItem.objects.filter(
            product__polymorphic_ctype__model__in=machine_models
        )
        .values("product__polymorphic_ctype__model")
        .annotate(units=Count("id"))
    )

    # Maintenance rollup over those same machine items, grouped by model.
    maint = (
        MaintenanceEvent.objects.filter(
            unit__product__polymorphic_ctype__model__in=machine_models
        )
        .values("unit__product__polymorphic_ctype__model")
        .annotate(
            faults=Count("id", filter=Q(kind=MaintenanceEvent.Kind.FAULT)),
            open_faults=Count(
                "id",
                filter=Q(kind=MaintenanceEvent.Kind.FAULT, resolved=False),
            ),
            total_cost=Sum("cost"),
            total_downtime_hours=Sum("downtime_hours"),
        )
    )
    maint_by_model = {
        row["unit__product__polymorphic_ctype__model"]: row for row in maint
    }

    # Summed operating age in days, grouped by model — used for MTBF. Done in
    # Python over the (small) machine fleet to stay DB-portable (SQLite lacks a
    # tidy date-diff aggregate); still O(machines), not O(events).
    today = now()
    age_days_by_model = {}
    for item in InventoryItem.objects.filter(
        product__polymorphic_ctype__model__in=machine_models
    ).select_related("product__polymorphic_ctype"):
        model = item.product.polymorphic_ctype.model
        age = (today - item.date_added).total_seconds() / 86400.0
        age_days_by_model[model] = age_days_by_model.get(model, 0.0) + max(age, 0.0)

    rows = []
    for f in fleet:
        model = f["product__polymorphic_ctype__model"]
        units = f["units"] or 0
        m = maint_by_model.get(model, {})
        faults = m.get("faults") or 0
        fleet_age_days = age_days_by_model.get(model, 0.0)
        mtbf_days = (fleet_age_days / faults) if faults else None
        rows.append(
            {
                "model": model.upper(),
                "ctype": model,
                "units": units,
                "faults": faults,
                "open_faults": m.get("open_faults") or 0,
                "total_cost": m.get("total_cost") or Decimal("0.00"),
                "total_downtime_hours": m.get("total_downtime_hours")
                or Decimal("0.00"),
                "faults_per_unit": (faults / units) if units else 0.0,
                "mtbf_days": mtbf_days,
            }
        )

    rows.sort(key=lambda r: (-r["faults_per_unit"], -r["faults"], r["model"]))
    return rows
