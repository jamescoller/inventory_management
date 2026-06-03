from django.core.management.base import BaseCommand

from inventory.models import InventoryItem, Location

Kind = Location.Kind
Status = InventoryItem.Status

# How many of each physical unit/rack to create, and the default status for the
# leaf locations under them.
RECEIVING_RACKS = 2
SHELVES_PER_RACK = 5
DRY_STORAGE_SHELVES = 5
AMS_UNITS = 8
DRYER_UNITS = 3
SLOTS_PER_UNIT = 4


class Command(BaseCommand):
    help = (
        "Seed the physical location hierarchy (receiving racks + shelves, dry "
        "storage, AMS units + slots, dryer units + slots). Idempotent: safe to "
        "re-run; existing locations (matched by name) are left untouched. AMS/dryer "
        "slot `unit` links are left blank for manual admin linking."
    )

    def handle(self, *args, **options):
        self.created = 0
        self.skipped = 0

        # Receiving racks -> shelves
        for r in range(1, RECEIVING_RACKS + 1):
            rack = self._ensure(f"Receiving Rack {r}", Kind.RACK)
            for s in range(1, SHELVES_PER_RACK + 1):
                self._ensure(
                    f"Receiving Rack {r} / Shelf {s}",
                    Kind.SHELF,
                    parent=rack,
                    default_status=Status.NEW,
                )

        # Dry storage shelves (flat; the legacy "Dry Storage" location may already
        # exist — it keeps its name and is left as-is).
        for s in range(1, DRY_STORAGE_SHELVES + 1):
            self._ensure(
                f"Dry Storage / Shelf {s}",
                Kind.DRY_STORAGE,
                default_status=Status.STORED,
            )

        # AMS units -> slots
        for u in range(1, AMS_UNITS + 1):
            unit = self._ensure(f"AMS {u}", Kind.AMS)
            for slot in range(1, SLOTS_PER_UNIT + 1):
                self._ensure(
                    f"AMS {u} / Slot {slot}",
                    Kind.AMS_SLOT,
                    parent=unit,
                    slot_index=slot,
                    default_status=Status.IN_USE,
                )

        # Dryer units -> slots
        for u in range(1, DRYER_UNITS + 1):
            unit = self._ensure(f"Dryer {u}", Kind.DRYER)
            for slot in range(1, SLOTS_PER_UNIT + 1):
                self._ensure(
                    f"Dryer {u} / Slot {slot}",
                    Kind.DRYER_SLOT,
                    parent=unit,
                    slot_index=slot,
                    default_status=Status.DRYING,
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Seed complete: {self.created} created, {self.skipped} already present."
            )
        )

    def _ensure(self, name, kind, parent=None, slot_index=None, default_status=None):
        obj, created = Location.objects.get_or_create(
            name=name,
            defaults={
                "kind": kind,
                "parent": parent,
                "slot_index": slot_index,
                "default_status": default_status,
            },
        )
        if created:
            self.created += 1
        else:
            self.skipped += 1
        return obj
