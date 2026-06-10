"""Bambu MQTT telemetry consumer: one auto-reconnecting paho client per enabled
PrinterDevice. Read-only — delegates all DB work to inventory.telemetry."""

import json
import logging
import ssl
import time

import paho.mqtt.client as mqtt
from django.core.management.base import BaseCommand
from django.db.utils import OperationalError

from inventory.models import PrinterDevice
from inventory.telemetry import handle_message

logger = logging.getLogger("inventory")

PUSHALL = json.dumps(
    {
        "pushing": {
            "sequence_id": "0",
            "command": "pushall",
            "version": 1,
            "push_target": 1,
        }
    }
)


class Command(BaseCommand):
    help = (
        "Run the Bambu MQTT telemetry consumer (one client per enabled PrinterDevice)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Connect, then return immediately instead of looping (for smoke checks).",
        )

    def handle(self, *args, **options):
        once = options["once"]
        while True:
            devices = self._wait_for_devices()
            if devices:
                break
            # Idle-wait rather than exit: with restart:unless-stopped, exiting here
            # would spin-restart the container until devices are seeded.
            self.stdout.write("No enabled PrinterDevice rows; nothing to do.")
            if once:
                return
            time.sleep(30)
        clients = []
        for dev in devices:
            client = self.make_client(dev)
            client.loop_start()
            clients.append(client)
        self.stdout.write(
            self.style.SUCCESS(
                f"Telemetry consumer running for {len(clients)} printer(s)."
            )
        )
        try:
            if options["once"]:
                return
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            pass
        finally:
            for client in clients:
                client.loop_stop()
                client.disconnect()

    def _wait_for_devices(self, attempts=30, delay=2):
        """Retry until the schema exists (the telemetry container may start before
        web finishes running migrations)."""
        for _ in range(attempts):
            try:
                return list(PrinterDevice.objects.filter(enabled=True))
            except OperationalError:
                time.sleep(delay)
        return []

    def make_client(self, device):
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id=f"inv-telemetry-{device.serial}"
        )
        client.username_pw_set("bblp", device.access_code)
        client.tls_set(cert_reqs=ssl.CERT_NONE)
        client.tls_insecure_set(True)
        client.reconnect_delay_set(min_delay=1, max_delay=120)
        client.user_data_set(device)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect
        try:
            client.connect_async(device.ip_address, 8883, keepalive=60)
        except Exception:  # noqa: BLE001 - offline printer: loop_start will retry
            logger.exception("connect_async failed for %s", device.serial)
        return client

    @staticmethod
    def _on_connect(client, device, flags, reason_code, properties=None):
        if reason_code != 0:
            logger.warning("MQTT connect rc=%s for %s", reason_code, device.serial)
            return
        client.subscribe(f"device/{device.serial}/report")
        client.publish(f"device/{device.serial}/request", PUSHALL)
        logger.info("MQTT connected + subscribed: %s", device.serial)

    @staticmethod
    def _on_message(client, device, msg):
        handle_message(device, msg.payload)

    @staticmethod
    def _on_disconnect(client, device, *args):
        logger.info("MQTT disconnected from %s (will auto-reconnect)", device.serial)
