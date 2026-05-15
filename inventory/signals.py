import logging

from django.db.models.signals import pre_save
from django.dispatch import receiver

from .models import InventoryItem

logger = logging.getLogger("inventory")


@receiver(pre_save, sender=InventoryItem)
def log_inventory_events(sender, instance, **kwargs):
    if instance.pk is None:
        logger.info(f"Adding {instance.product.name} to inventory")
        return

    try:
        old = InventoryItem.objects.get(pk=instance.pk)
    except InventoryItem.DoesNotExist:
        return

    logger.info(f"Updated inventory for {instance.product.name} (ID: {instance.pk})")

    if old.status != instance.status and instance.status == InventoryItem.Status.DEPLETED:
        logger.info(
            f"InventoryItem {instance.pk} DEPLETED at location '{old.location}'"
        )
