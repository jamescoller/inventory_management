from django.core.management.base import BaseCommand

from inventory.models import Filament


class Command(BaseCommand):
    help = "Updates color families for all existing filaments"

    def handle(self, *args, **kwargs):
        filaments = Filament.objects.all()
        updated_count = 0

        for filament in filaments:
            old_family = filament.color_family
            new_family = filament.get_color_family()

            if new_family and old_family != new_family:
                filament.color_family = new_family
                filament.save(update_fields=["color_family"])
                updated_count += 1
                self.stdout.write(
                    f"Updated {filament.name}: {old_family} -> {new_family}"
                )

        self.stdout.write(
            self.style.SUCCESS(f"Successfully updated {updated_count} filaments")
        )
