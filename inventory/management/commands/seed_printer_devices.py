"""Seed the 4 Bambu PrinterDevice rows (identity only — access codes are filled
by James via admin or the --codes arg; never committed in code)."""

from django.core.management.base import BaseCommand

from inventory.models import PrinterDevice

# serial -> (name, ip, model)  — from docs/bambu-mqtt-integration.md §6
PRINTERS = {
    "0948CD531200537": ("H2Laser", "10.10.30.11", "H2D"),
    "0948AD532400186": ("H2Dreamy", "10.10.30.12", "H2D"),
    "00M09D461201098": ("RuPaul", "10.10.30.13", "X1C"),
    "00M09D460801722": ("Scooby Doo", "10.10.30.14", "X1C"),
}


class Command(BaseCommand):
    help = "Idempotently seed the Bambu PrinterDevice rows."

    def add_arguments(self, parser):
        parser.add_argument(
            "--codes",
            nargs="*",
            default=[],
            metavar="SERIAL=CODE",
            help="Optional access codes, e.g. --codes 0948CD531200537=0e25e952 ...",
        )

    def handle(self, *args, **options):
        codes = dict(pair.split("=", 1) for pair in options["codes"])
        created = 0
        for serial, (name, ip, model) in PRINTERS.items():
            dev, was_created = PrinterDevice.objects.get_or_create(
                serial=serial,
                defaults={"name": name, "ip_address": ip, "model_name": model},
            )
            created += was_created
            if serial in codes:
                dev.access_code = codes[serial]
                dev.save(update_fields=["access_code"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Seed complete: {created} created, "
                f"{len(PRINTERS) - created} already present."
            )
        )
