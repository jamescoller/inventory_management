# Generated by Django 4.2.20 on 2025-05-25 02:34

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0010_inventoryitem_serial_number"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="ams",
            options={"verbose_name": "AMS", "verbose_name_plural": "AMS"},
        ),
        migrations.AlterModelOptions(
            name="dryer",
            options={"verbose_name": "Dryer", "verbose_name_plural": "Dryers"},
        ),
        migrations.AlterModelOptions(
            name="filament",
            options={"verbose_name": "Filament", "verbose_name_plural": "Filaments"},
        ),
        migrations.AlterModelOptions(
            name="hardware",
            options={"verbose_name": "Hardware", "verbose_name_plural": "Hardware"},
        ),
        migrations.AlterModelOptions(
            name="inventoryitem",
            options={
                "verbose_name": "Inventory Item",
                "verbose_name_plural": "Inventory Items",
            },
        ),
        migrations.AlterModelOptions(
            name="location",
            options={"verbose_name": "Location", "verbose_name_plural": "Locations"},
        ),
        migrations.AlterModelOptions(
            name="order",
            options={"verbose_name": "Order", "verbose_name_plural": "Orders"},
        ),
        migrations.AlterModelOptions(
            name="printer",
            options={"verbose_name": "Printer", "verbose_name_plural": "Printers"},
        ),
        migrations.AlterModelOptions(
            name="product",
            options={
                "ordering": ["sku"],
                "verbose_name": "Product",
                "verbose_name_plural": "Products",
            },
        ),
        migrations.AlterModelOptions(
            name="shipment",
            options={"verbose_name": "Shipment", "verbose_name_plural": "Shipments"},
        ),
    ]
