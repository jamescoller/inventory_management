"""Rebuild the FTS5 search index from scratch (run after bulk/catalog edits)."""

from django.core.management.base import BaseCommand

from inventory.search_index import rebuild_all


class Command(BaseCommand):
    help = "Rebuild the InventoryItem FTS5 search index."

    def handle(self, *args, **options):
        count = rebuild_all()
        self.stdout.write(self.style.SUCCESS(f"Reindexed {count} item(s)."))
