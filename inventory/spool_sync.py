"""Pure matcher for the Bambu spool-sync dry-run (Phase 16.3, trust gate).

Reads the AMSChannelState telemetry mirror + inventory via the ORM and produces
*proposed* writes — it never writes. The (device, ams_index) -> AMS-serial bridge
is passed in (fetched live by inventory.bambu_mqtt); see
docs/superpowers/specs/2026-06-21-spool-sync-dryrun-design.md.
"""

import dataclasses

from django.utils import timezone

from .models import (
    AMS,
    AMSChannelState,
    Filament,
    InventoryItem,
    Location,
    PrinterDevice,
)

ALL_ZEROS = "0" * 32
_HEXDIGITS = set("0123456789abcdef")


def normalize_hex(value):
    """Return a 6-char lowercase RGB hex (drops '#' and any alpha), or None."""
    if not value:
        return None
    h = str(value).strip().lstrip("#").lower()
    if len(h) < 6:
        return None
    h = h[:6]
    if any(c not in _HEXDIGITS for c in h):
        return None
    return h


def classify_tray(tray_uuid, tray_type, color_hex):
    """BAMBU (real RFID), NON_BAMBU (roll present, no RFID), or EMPTY."""
    uuid = (tray_uuid or "").strip()
    if uuid and uuid != ALL_ZEROS:
        return "BAMBU"
    if (tray_type or "").strip() or normalize_hex(color_hex):
        return "NON_BAMBU"
    return "EMPTY"


def material_matches(tray_type, filament):
    """Advisory: is the telemetry material consistent with the spool's? None if unknown."""
    if not tray_type or filament is None or filament.material is None:
        return None
    mat = filament.material
    haystack = f"{mat.name} {mat.material_type}".lower()
    return tray_type.strip().lower() in haystack


def resolve_ams_item(serial):
    """The AMS unit InventoryItem whose serial_number matches (case-insensitive)."""
    if not serial:
        return None
    for item in InventoryItem.objects.filter(serial_number__iexact=serial):
        if isinstance(item.product.get_real_instance(), AMS):
            return item
    return None


def slot_for(ams_item, tray_index):
    """The ams_slot Location for this unit at slot_index = tray_index + 1."""
    return Location.objects.filter(
        kind=Location.Kind.AMS_SLOT, unit=ams_item, slot_index=tray_index + 1
    ).first()


def spools_in_slot(slot):
    """In-stock InventoryItems in this slot (excludes DEPLETED/SOLD/UNKNOWN)."""
    return list(
        InventoryItem.objects.filter(location=slot).exclude(
            status__in=InventoryItem.STICKY_STATUSES
        )
    )


def filament_of(item):
    """The real Filament product for an item, or None (polymorphic-safe)."""
    product = item.product.get_real_instance()
    return product if isinstance(product, Filament) else None


@dataclasses.dataclass
class Proposal:
    device: str
    ams_index: int
    tray_index: int
    tray_uuid: str
    item_id: int
    item_label: str
    write_serial: str | None
    write_percent_from: int | None
    write_percent_to: int | None
    material_match: bool | None
    color_telemetry: str | None
    color_inventory: str | None
    color_match: bool


@dataclasses.dataclass
class Flag:
    category: str
    device: str
    ams_index: int
    tray_index: int
    detail: str
    item_id: int | None = None


@dataclasses.dataclass
class SyncReport:
    generated_at: str
    ams_bridge: dict
    proposals: list
    flags: list
    counts: dict


_COUNT_KEYS = (
    "match",
    "non_bambu_ok",
    "color_mismatch",
    "missing_item",
    "inventory_only",
    "serial_conflict",
    "unmapped_ams",
    "missing_slot",
    "slot_overfilled",
    "empty_skipped",
)


def build_report(ams_serial_map, *, generated_at=None):
    """Categorize every AMS tray against inventory and return proposed writes.

    ``ams_serial_map``: {(device_id, ams_index): ams_serial}. Reads only; never
    mutates inventory.
    """
    proposals, flags = [], []
    counts = {k: 0 for k in _COUNT_KEYS}
    bridge = {}

    for device in PrinterDevice.objects.filter(enabled=True).order_by("name"):
        dev_bridge = bridge.setdefault(device.name, {})
        channels = AMSChannelState.objects.filter(device=device).order_by(
            "ams_index", "tray_index"
        )
        for ch in channels:
            kind = classify_tray(ch.tray_uuid, ch.tray_type, ch.color_hex)
            serial = ams_serial_map.get((device.id, ch.ams_index))
            ams_item = resolve_ams_item(serial) if serial else None
            dev_bridge[ch.ams_index] = {
                "serial": serial,
                "item_id": ams_item.id if ams_item else None,
                "matched": ams_item is not None,
            }

            if ams_item is None:
                if kind == "EMPTY":
                    counts["empty_skipped"] += 1
                else:
                    counts["unmapped_ams"] += 1
                    why = (
                        f"serial {serial!r} not in inventory"
                        if serial
                        else "no get_version AMS module"
                    )
                    flags.append(
                        Flag(
                            "UNMAPPED_AMS",
                            device.name,
                            ch.ams_index,
                            ch.tray_index,
                            f"ams_index {ch.ams_index}: {why}.",
                        )
                    )
                continue

            slot = slot_for(ams_item, ch.tray_index)
            if slot is None:
                if kind == "EMPTY":
                    counts["empty_skipped"] += 1
                else:
                    counts["missing_slot"] += 1
                    flags.append(
                        Flag(
                            "MISSING_SLOT",
                            device.name,
                            ch.ams_index,
                            ch.tray_index,
                            f"No ams_slot for {ams_item} slot {ch.tray_index + 1}.",
                            item_id=ams_item.id,
                        )
                    )
                continue

            spools = spools_in_slot(slot)

            if kind == "EMPTY":
                if spools:
                    counts["inventory_only"] += 1
                    flags.append(
                        Flag(
                            "INVENTORY_ONLY",
                            device.name,
                            ch.ams_index,
                            ch.tray_index,
                            f"AMS slot empty but inventory has {spools[0]}.",
                            item_id=spools[0].id,
                        )
                    )
                else:
                    counts["empty_skipped"] += 1
                continue

            if not spools:
                counts["missing_item"] += 1
                flags.append(
                    Flag(
                        "MISSING_ITEM",
                        device.name,
                        ch.ams_index,
                        ch.tray_index,
                        f"AMS sees a {ch.tray_type or '?'} roll but {slot.name} is empty.",
                    )
                )
                continue
            if len(spools) > 1:
                counts["slot_overfilled"] += 1
                flags.append(
                    Flag(
                        "SLOT_OVERFILLED",
                        device.name,
                        ch.ams_index,
                        ch.tray_index,
                        f"{len(spools)} in-stock items in {slot.name}; reconcile to 1:1.",
                        item_id=spools[0].id,
                    )
                )
                continue

            item = spools[0]
            fil = filament_of(item)
            color_t = normalize_hex(ch.color_hex)
            color_f = normalize_hex(getattr(fil, "hex_code", None)) if fil else None
            color_match = bool(color_t and color_f and color_t == color_f)
            existing = (item.serial_number or "").strip()

            if (
                kind == "BAMBU"
                and existing
                and existing.lower() != ch.tray_uuid.strip().lower()
            ):
                counts["serial_conflict"] += 1
                flags.append(
                    Flag(
                        "SERIAL_CONFLICT",
                        device.name,
                        ch.ams_index,
                        ch.tray_index,
                        f"{item} already has serial {existing!r}; not overwriting.",
                        item_id=item.id,
                    )
                )
                continue

            if not color_match:
                counts["color_mismatch"] += 1
                flags.append(
                    Flag(
                        "COLOR_MISMATCH",
                        device.name,
                        ch.ams_index,
                        ch.tray_index,
                        f"AMS #{color_t or '?'} ({ch.tray_type}) vs inventory "
                        f"#{color_f or '?'}; verify the slot's item.",
                        item_id=item.id,
                    )
                )
                continue

            if kind == "NON_BAMBU":
                counts["non_bambu_ok"] += 1
                continue

            # BAMBU confident match -> propose writes
            counts["match"] += 1
            write_serial = ch.tray_uuid if not existing else None
            cur_int = int(item.percent_remaining or 0)
            write_pct = (
                ch.remain_pct
                if (
                    ch.remain_pct is not None
                    and ch.remain_pct >= 0
                    and ch.remain_pct != cur_int
                )
                else None
            )
            if write_serial is not None or write_pct is not None:
                proposals.append(
                    Proposal(
                        device=device.name,
                        ams_index=ch.ams_index,
                        tray_index=ch.tray_index,
                        tray_uuid=ch.tray_uuid,
                        item_id=item.id,
                        item_label=str(item),
                        write_serial=write_serial,
                        write_percent_from=cur_int if write_pct is not None else None,
                        write_percent_to=write_pct,
                        material_match=material_matches(ch.tray_type, fil),
                        color_telemetry=color_t,
                        color_inventory=color_f,
                        color_match=color_match,
                    )
                )

    return SyncReport(
        generated_at=generated_at or timezone.now().isoformat(),
        ams_bridge=bridge,
        proposals=proposals,
        flags=flags,
        counts=counts,
    )
