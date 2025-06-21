import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import InventoryItem

logger = logging.getLogger("inventory")


@receiver(post_save, sender=InventoryItem)
def log_inventory_events(sender, instance, created, **kwargs):
    if created:
        logger.info(f"Added {instance.product.name} (ID: {instance.id}) to inventory")
    else:
        logger.info(
            f"Updated inventory for {instance.product.name} (ID: {instance.id})"
        )

        # Check for a depleted status change
        try:
            old_instance = InventoryItem.objects.get(pk=instance.pk)
            if (
                old_instance.status != instance.status
                and instance.status == InventoryItem.StatusChoices.DEPLETED
            ):
                logger.info(
                    f"InventoryItem {instance.id} DEPLETED at location '{instance.location}'"
                )
        except InventoryItem.DoesNotExist:
            pass  # Rare edge case; silently ignore
