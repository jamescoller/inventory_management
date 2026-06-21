"""Dry-run Bambu spool sync (Phase 16.3 trust gate): propose serial_number /
percent_remaining writes from AMS telemetry — ZERO inventory writes. Writes a
JSON artifact + prints a summary. `--apply` is intentionally blocked.
"""

import dataclasses
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from inventory import bambu_mqtt, spool_sync
from inventory.models import PrinterDevice


class Command(BaseCommand):
    help = "Dry-run Bambu spool sync: propose serial/percent writes (zero inventory writes)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="(blocked) live writes are not enabled in this phase.",
        )
        parser.add_argument(
            "--out-dir",
            default=None,
            help="Artifact dir (default: <BASE_DIR>/telemetry_review).",
        )

    def handle(self, *args, **options):
        if options["apply"]:
            raise CommandError("live writes not enabled (16.3 go-live)")

        out_dir = Path(
            options["out_dir"] or (Path(settings.BASE_DIR) / "telemetry_review")
        )
        devices = list(PrinterDevice.objects.filter(enabled=True))
        self.stdout.write(f"Probing get_version on {len(devices)} printer(s)…")
        serial_map = bambu_mqtt.fetch_ams_serials_all(devices)
        report = spool_sync.build_report(serial_map)

        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = report.generated_at.translate({ord(c): None for c in ":-"})[:15]
        path = out_dir / f"spool-sync-{stamp}.json"
        path.write_text(json.dumps(dataclasses.asdict(report), indent=2))

        self._print_summary(report)
        self.stdout.write(self.style.SUCCESS(f"Report: {path}"))

    def _print_summary(self, report):
        self.stdout.write("\n== Spool sync (DRY-RUN — no writes) ==")
        for key, value in report.counts.items():
            self.stdout.write(f"  {key:16} {value}")
        if report.proposals:
            self.stdout.write("\n-- Proposed writes --")
            for p in report.proposals:
                bits = []
                if p.write_serial:
                    bits.append(f"serial←{p.write_serial}")
                if p.write_percent_to is not None:
                    bits.append(f"%←{p.write_percent_from}→{p.write_percent_to}")
                self.stdout.write(
                    f"  {p.device} ams{p.ams_index}/t{p.tray_index} {p.item_label}: "
                    f"{', '.join(bits)}"
                )
        if report.flags:
            self.stdout.write("\n-- Flags --")
            for f in report.flags:
                self.stdout.write(
                    f"  [{f.category}] {f.device} ams{f.ams_index}/t{f.tray_index}: {f.detail}"
                )
