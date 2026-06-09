"""Print-job consumption and per-printer utilization service.

Mirrors :mod:`inventory.audit` / :mod:`inventory.items`: the logic lives here,
views stay thin. This module owns two responsibilities:

- :func:`complete_job` — apply a :class:`~inventory.models.PrintJob`'s filament
  consumption to the referenced spools. For each
  :class:`~inventory.models.PrintJobFilament` line it computes a percentage of the
  spool used, decrements ``InventoryItem.percent_remaining`` (floored at 0), and
  when a spool reaches the depletion threshold it is retired through the
  Phase-11.3 :func:`inventory.items.deplete` primitive (which owns the
  sticky-status flag dance). It never sets DEPLETED by hand.
- :func:`printer_utilization` / :func:`utilization_summary` — DB-aggregated
  utilization (hours, job count, success %, kg by material/color). No Python-side
  table scans.

**Depletion threshold:** a spool is depleted when its post-decrement
``percent_remaining`` is ``<= DEPLETE_AT_PERCENT`` (0). A line that doesn't fully
consume a spool only decrements it; ``items.deplete`` is called *only* on the line
that drives the spool to zero, so a single spool spread across two jobs depletes
exactly once.
"""

from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils.timezone import now

from . import items
from .models import Filament, InventoryItem, PrintJob, PrintJobFilament

# A spool at or below this remaining percentage is considered consumed.
DEPLETE_AT_PERCENT = Decimal("0")

# Statuses for which a spool is already gone — never re-deplete or re-decrement.
_TERMINAL = (InventoryItem.Status.DEPLETED, InventoryItem.Status.SOLD)


def line_percent_used(line):
    """Percentage of the spool consumed by ``line``.

    Prefers ``grams_used`` when the spool's catalog ``Filament.weight`` (kg) is
    known: ``grams / (weight_kg * 1000) * 100``. Falls back to the explicit
    ``percent_used``. Returns a :class:`~decimal.Decimal` (0 if neither is usable).
    """
    if line.grams_used is not None:
        product = line.item.product.get_real_instance()
        weight_kg = getattr(product, "weight", None)
        if weight_kg:
            grams_total = Decimal(weight_kg) * Decimal(1000)
            if grams_total > 0:
                return Decimal(line.grams_used) / grams_total * Decimal(100)
    if line.percent_used is not None:
        return Decimal(line.percent_used)
    return Decimal(0)


@transaction.atomic
def complete_job(job):
    """Apply ``job``'s filament consumption to its spools; idempotent.

    For each :class:`PrintJobFilament` line: decrement the spool's
    ``percent_remaining`` by :func:`line_percent_used` (floored at 0) and, if the
    spool reaches the depletion threshold, retire it via :func:`items.deplete`.
    Already-terminal spools are skipped. Marks the job ``completed`` and stamps
    ``ended_at`` if unset; a second call is a no-op (so the same POST can't
    double-decrement).

    Returns the list of :class:`InventoryItem` spools depleted by this call.
    """
    if job.completed:
        return []

    depleted = []
    for line in job.filaments.select_related("item"):
        item = line.item
        if item.status in _TERMINAL:
            continue

        delta = line_percent_used(line)
        current = Decimal(item.percent_remaining or 0)
        remaining = current - delta
        if remaining < 0:
            remaining = Decimal(0)

        if remaining <= DEPLETE_AT_PERCENT:
            # Drive the spool to zero, then retire it through the one sanctioned
            # primitive (it sets the sticky flag + clears the location).
            item.percent_remaining = Decimal(0)
            items.deplete(item, reason=f"print job {job.pk}")
            depleted.append(item)
        else:
            item.percent_remaining = remaining
            item.save(update_fields=["percent_remaining", "last_modified"])

    job.completed = True
    if job.ended_at is None:
        job.ended_at = now()
    job.save(update_fields=["completed", "ended_at"])
    return depleted


def printer_utilization(printer, *, since=None):
    """Utilization stats for a single printer :class:`InventoryItem`.

    Returns a dict: ``jobs``, ``hours`` (Sum of duration), ``success`` count,
    ``success_rate`` (0-100 or None), and ``grams`` consumed — all via DB
    aggregation. ``since`` filters on ``started_at`` (None = all-time).
    """
    job_qs = PrintJob.objects.filter(printer=printer)
    if since is not None:
        job_qs = job_qs.filter(started_at__gte=since)

    agg = job_qs.aggregate(
        jobs=Count("id"),
        seconds=Sum("duration_s"),
        success=Count("id", filter=Q(result=PrintJob.Result.SUCCESS)),
    )
    grams = (
        PrintJobFilament.objects.filter(job__in=job_qs).aggregate(g=Sum("grams_used"))[
            "g"
        ]
        or 0
    )
    jobs = agg["jobs"] or 0
    success = agg["success"] or 0
    seconds = agg["seconds"] or 0
    return {
        "jobs": jobs,
        "hours": round(seconds / 3600, 1) if seconds else 0.0,
        "success": success,
        "success_rate": round(success / jobs * 100, 1) if jobs else None,
        "grams": float(grams),
        "kg": round(float(grams) / 1000, 2),
    }


def consumption_by_material():
    """Total grams consumed grouped by (material, color), via DB aggregation.

    Joins ``PrintJobFilament -> item.product -> Filament.material`` so only
    filament spools contribute. Returns a list of dicts sorted by grams desc.
    """
    filament_ids = Filament.objects.values_list("id", flat=True)
    rows = (
        PrintJobFilament.objects.filter(
            item__product_id__in=filament_ids, grams_used__isnull=False
        )
        .values(
            "item__product__filament__material__name",
            "item__product__filament__color",
            "item__product__filament__color_family",
        )
        .annotate(grams=Sum("grams_used"))
        .order_by("-grams")
    )
    out = []
    for r in rows:
        grams = float(r["grams"] or 0)
        out.append(
            {
                "material": r["item__product__filament__material__name"] or "—",
                "color": r["item__product__filament__color"] or "",
                "color_family": r["item__product__filament__color_family"] or "",
                "grams": round(grams, 1),
                "kg": round(grams / 1000, 3),
            }
        )
    return out


def utilization_summary(*, since=None):
    """Per-printer utilization rows for the fleet-wide utilization view.

    One row per printer :class:`InventoryItem` that has at least one job, each row
    being :func:`printer_utilization` plus identity fields. Built from a single
    grouped query (no per-printer N+1).
    """
    job_qs = PrintJob.objects.all()
    if since is not None:
        job_qs = job_qs.filter(started_at__gte=since)

    base = (
        job_qs.values("printer_id")
        .annotate(
            jobs=Count("id"),
            seconds=Sum("duration_s"),
            success=Count("id", filter=Q(result=PrintJob.Result.SUCCESS)),
        )
        .order_by()
    )
    # Grams per printer in one query, summed across the printer's job filaments.
    grams_map = defaultdict(float)
    for row in (
        PrintJobFilament.objects.filter(job__in=job_qs)
        .values("job__printer_id")
        .annotate(g=Sum("grams_used"))
    ):
        grams_map[row["job__printer_id"]] = float(row["g"] or 0)

    printer_ids = [r["printer_id"] for r in base]
    printers = {
        p.id: p
        for p in InventoryItem.objects.filter(id__in=printer_ids).select_related(
            "product"
        )
    }

    rows = []
    for r in base:
        pid = r["printer_id"]
        jobs = r["jobs"] or 0
        success = r["success"] or 0
        seconds = r["seconds"] or 0
        grams = grams_map.get(pid, 0.0)
        printer = printers.get(pid)
        rows.append(
            {
                "printer_id": pid,
                "printer": printer,
                "printer_name": (
                    str(printer.product.get_real_instance()) if printer else f"#{pid}"
                ),
                "serial_number": printer.serial_number if printer else "",
                "jobs": jobs,
                "hours": round(seconds / 3600, 1) if seconds else 0.0,
                "success": success,
                "success_rate": round(success / jobs * 100, 1) if jobs else None,
                "grams": round(grams, 1),
                "kg": round(grams / 1000, 2),
            }
        )
    rows.sort(key=lambda x: (-x["hours"], -x["jobs"]))
    return rows
