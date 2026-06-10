"""Bambu MQTT telemetry ingest — pure logic, no network.

The MQTT transport lives in ``management/commands/run_telemetry_consumer.py``;
this module turns a parsed Bambu ``print`` report object into upserts on the
telemetry mirror tables. Bambu sends a full snapshot on ``pushall`` then partial
deltas, so ingest updates ONLY the keys present in each message — it never
null-clobbers a field the delta omitted.
"""

import json
import logging
from decimal import Decimal, InvalidOperation

from django.db import close_old_connections
from django.utils import timezone

from .models import AMSChannelState, AMSUnitState, PrinterState, TelemetrySample

logger = logging.getLogger("inventory")

SAMPLE_INTERVAL_S = 300


def _to_int(v):
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _to_decimal(v):
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _to_str(v):
    return "" if v is None else str(v)


def should_sample(prev, new_state, *, now=None, interval_s=SAMPLE_INTERVAL_S):
    """Downsample rule: sample on first-ever, on gcode_state transition, or every
    ``interval_s`` while RUNNING."""
    if now is None:
        now = timezone.now()
    if prev is None:
        return True
    if new_state != prev.gcode_state:
        return True
    if new_state == "RUNNING" and (now - prev.ts).total_seconds() >= interval_s:
        return True
    return False


# model attr -> (payload key, converter)
_PRINTER_FIELDS = {
    "gcode_state": ("gcode_state", _to_str),
    "mc_percent": ("mc_percent", _to_int),
    "layer_num": ("layer_num", _to_int),
    "total_layers": ("total_layer_num", _to_int),
    "nozzle_temp": ("nozzle_temper", _to_decimal),
    "nozzle_target": ("nozzle_target_temper", _to_decimal),
    "bed_temp": ("bed_temper", _to_decimal),
    "bed_target": ("bed_target_temper", _to_decimal),
    "remaining_min": ("mc_remaining_time", _to_int),
    "subtask_name": ("subtask_name", _to_str),
    "task_id": ("task_id", _to_str),
}
_TRAY_FIELDS = {
    "tray_uuid": ("tray_uuid", _to_str),
    "tray_info_idx": ("tray_info_idx", _to_str),
    "tray_type": ("tray_type", _to_str),
    "tray_sub_brands": ("tray_sub_brands", _to_str),
    "color_hex": ("tray_color", _to_str),
    "remain_pct": ("remain", _to_int),
}


def _apply(obj, fields, src):
    """Set obj.attr = conv(src[key]) for each mapped field present in src.
    Returns True if any field was applied."""
    changed = False
    for attr, (key, conv) in fields.items():
        if key in src:
            setattr(obj, attr, conv(src[key]))
            changed = True
    return changed


def ingest_report(device, report):
    """Delta-merge a parsed Bambu ``print`` object into the mirror tables."""
    state, _ = PrinterState.objects.get_or_create(device=device)
    changed = _apply(state, _PRINTER_FIELDS, report)
    if "hms" in report:
        state.hms_codes = report["hms"] or []
        changed = True
    if changed:
        state.save()

    ams_root = report.get("ams")
    if isinstance(ams_root, dict) and isinstance(ams_root.get("ams"), list):
        for unit in ams_root["ams"]:
            _ingest_ams_unit(device, unit)

    new_state = report.get("gcode_state")
    if new_state is not None:
        prev = TelemetrySample.objects.filter(device=device).order_by("-ts").first()
        if should_sample(prev, new_state):
            TelemetrySample.objects.create(
                device=device,
                ts=timezone.now(),
                gcode_state=new_state,
                mc_percent=_to_int(report.get("mc_percent")),
                nozzle_temp=_to_decimal(report.get("nozzle_temper")),
                bed_temp=_to_decimal(report.get("bed_temper")),
                remaining_min=_to_int(report.get("mc_remaining_time")),
            )


def _ingest_ams_unit(device, unit):
    idx = _to_int(unit.get("id"))
    if idx is None:
        return
    u, _ = AMSUnitState.objects.get_or_create(device=device, ams_index=idx)
    changed = False
    if "humidity" in unit:
        u.humidity = _to_int(unit["humidity"])
        changed = True
    if "humidity_raw" in unit:
        u.humidity_raw = _to_int(unit["humidity_raw"])
        changed = True
    if "temp" in unit:
        u.temp = _to_decimal(unit["temp"])
        changed = True
    if "dry_time" in unit:
        u.dry_time = _to_int(unit["dry_time"])
        changed = True
    ds = unit.get("dry_setting")
    if isinstance(ds, dict):
        if "dry_duration" in ds:
            u.dry_duration = _to_int(ds["dry_duration"])
            changed = True
        if "dry_temperature" in ds:
            u.dry_temperature = _to_int(ds["dry_temperature"])
            changed = True
        if "dry_filament" in ds:
            u.dry_filament = _to_str(ds["dry_filament"])
            changed = True
    if changed:
        u.save()
    trays = unit.get("tray")
    if isinstance(trays, list):
        for tray in trays:
            _ingest_tray(device, idx, tray)


def _ingest_tray(device, ams_index, tray):
    tidx = _to_int(tray.get("id"))
    if tidx is None:
        return
    ch, _ = AMSChannelState.objects.get_or_create(
        device=device, ams_index=ams_index, tray_index=tidx
    )
    if _apply(ch, _TRAY_FIELDS, tray):
        ch.save()


def handle_message(device, raw):
    """Parse a raw MQTT payload, ingest its ``print`` object, mark the device
    seen. Returns True if ingested. One bad message never kills the consumer."""
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return False
    report = payload.get("print") if isinstance(payload, dict) else None
    if not isinstance(report, dict):
        return False
    close_old_connections()
    try:
        ingest_report(device, report)
        device.last_seen_at = timezone.now()
        device.save(update_fields=["last_seen_at"])
        return True
    except Exception:  # noqa: BLE001 - resilience: don't crash the client thread
        logger.exception("telemetry ingest failed for %s", device.serial)
        return False
