"""Bambu MQTT telemetry ingest — pure logic, no network.

The MQTT transport lives in ``management/commands/run_telemetry_consumer.py``;
this module turns a parsed Bambu ``print`` report object into upserts on the
telemetry mirror tables. Bambu sends a full snapshot on ``pushall`` then partial
deltas, so ingest updates ONLY the keys present in each message — it never
null-clobbers a field the delta omitted.
"""

import logging
from decimal import Decimal, InvalidOperation

from django.utils import timezone

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
