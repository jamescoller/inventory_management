"""Live Bambu MQTT helper for the spool-sync dry-run: fetch the AMS hardware
serials via the `get_version` command (the deterministic (device, ams_index) ->
AMS unit bridge). Read-only; mirrors the connection params of the telemetry
consumer (run_telemetry_consumer.py). Only `parse_ams_modules` is unit-tested.
"""

import json
import logging
import re
import ssl
import time

import paho.mqtt.client as mqtt

logger = logging.getLogger("inventory")

# A get_version module is an AMS iff its name is ams/N (AMS-Lite), n3f/N (H2D AMS
# 2 Pro) or n3s/N (H2D AMS-HT). The captured group is the telemetry ams_index.
_AMS_MODULE = re.compile(r"^(?:ams|n3f|n3s)/(\d+)$")
GET_VERSION = json.dumps({"info": {"sequence_id": "0", "command": "get_version"}})


def parse_ams_modules(modules):
    """{ams_index: sn} from a get_version `info.module` list."""
    out = {}
    for module in modules or []:
        match = _AMS_MODULE.match(str(module.get("name", "")))
        sn = module.get("sn")
        if match and sn and sn != "N/A":
            out[int(match.group(1))] = sn
    return out


def fetch_ams_serials(device, *, timeout=15):
    """Connect to one printer, request get_version, return {ams_index: sn}.

    Returns {} on connect failure or timeout — the caller treats absent indices
    as UNMAPPED_AMS rather than crashing.
    """
    result = {}
    done = {"flag": False}

    def on_connect(client, userdata, flags, reason_code, properties=None):
        if reason_code != 0:
            logger.warning(
                "get_version connect rc=%s for %s", reason_code, device.serial
            )
            done["flag"] = True
            return
        client.subscribe(f"device/{device.serial}/report")
        client.publish(f"device/{device.serial}/request", GET_VERSION)

    def on_message(client, userdata, msg):
        try:
            info = (json.loads(msg.payload) or {}).get("info")
        except (ValueError, TypeError):
            return
        if isinstance(info, dict) and isinstance(info.get("module"), list):
            result.update(parse_ams_modules(info["module"]))
            done["flag"] = True
            client.disconnect()

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, client_id=f"inv-syncprobe-{device.serial}"
    )
    client.username_pw_set("bblp", device.access_code)
    client.tls_set(cert_reqs=ssl.CERT_NONE)
    client.tls_insecure_set(True)
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(device.ip_address, 8883, keepalive=30)
    except OSError:
        logger.warning("get_version connect failed for %s", device.serial)
        return {}
    client.loop_start()
    ticks = timeout * 2
    while ticks > 0 and not done["flag"]:
        time.sleep(0.5)
        ticks -= 1
    client.loop_stop()
    try:
        client.disconnect()
    except Exception:  # noqa: BLE001
        pass
    return result


def fetch_ams_serials_all(devices):
    """{(device.id, ams_index): sn} across all given devices."""
    out = {}
    for device in devices:
        for ams_index, sn in fetch_ams_serials(device).items():
            out[(device.id, ams_index)] = sn
    return out
