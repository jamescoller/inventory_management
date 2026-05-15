from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0019_alter_filament_color_alter_filament_color_family_and_more"),
    ]

    operations = [
        # Remove redundant boolean columns (now derived as @property from status)
        migrations.RemoveField(model_name="inventoryitem", name="depleted"),
        migrations.RemoveField(model_name="inventoryitem", name="in_use"),
        migrations.RemoveField(model_name="inventoryitem", name="sold"),
        # Remove Order and Shipment models (no views, no FKs from live models)
        migrations.DeleteModel(name="Shipment"),
        migrations.DeleteModel(name="Order"),
    ]
