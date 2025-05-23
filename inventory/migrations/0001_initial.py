# Generated by Django 4.2.20 on 2025-05-04 01:35

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Location",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=200)),
            ],
            options={
                "verbose_name_plural": "locations",
            },
        ),
        migrations.CreateModel(
            name="Order",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("order_num", models.CharField(max_length=100)),
                (
                    "polymorphic_ctype",
                    models.ForeignKey(
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="polymorphic_%(app_label)s.%(class)s_set+",
                        to="contenttypes.contenttype",
                    ),
                ),
            ],
            options={
                "abstract": False,
                "base_manager_name": "objects",
            },
        ),
        migrations.CreateModel(
            name="Product",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                ("upc", models.CharField(max_length=50, unique=True)),
                ("sku", models.CharField(max_length=8)),
                ("price", models.DecimalField(decimal_places=2, max_digits=5)),
                ("notes", models.TextField(blank=True)),
                ("category", models.CharField(max_length=255)),
                (
                    "polymorphic_ctype",
                    models.ForeignKey(
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="polymorphic_%(app_label)s.%(class)s_set+",
                        to="contenttypes.contenttype",
                    ),
                ),
            ],
            options={
                "ordering": ["sku"],
            },
        ),
        migrations.CreateModel(
            name="AMS",
            fields=[
                (
                    "product_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="inventory.product",
                    ),
                ),
                ("mfr", models.CharField(default="Bambu Lab", max_length=100)),
                ("model", models.CharField(default="X1 Carbon", max_length=100)),
                ("num_slots", models.IntegerField(blank=True, default=4)),
            ],
            options={
                "abstract": False,
                "base_manager_name": "objects",
            },
            bases=("inventory.product",),
        ),
        migrations.CreateModel(
            name="Dryer",
            fields=[
                (
                    "product_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="inventory.product",
                    ),
                ),
                ("mfr", models.CharField(max_length=100)),
                ("model", models.CharField(max_length=100)),
                ("num_slots", models.IntegerField(default=1)),
                ("max_temp_degC", models.IntegerField(blank=True)),
            ],
            options={
                "abstract": False,
                "base_manager_name": "objects",
            },
            bases=("inventory.product",),
        ),
        migrations.CreateModel(
            name="Filament",
            fields=[
                (
                    "product_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="inventory.product",
                    ),
                ),
                ("material", models.CharField(max_length=50)),
                ("material_type", models.CharField(blank=True, max_length=50)),
                ("color", models.CharField(max_length=50)),
                ("hex_code", models.CharField(max_length=7)),
                ("print_temp_min_degC", models.IntegerField(blank=True)),
                ("print_temp_max_degC", models.IntegerField(blank=True)),
                ("print_temp_ideal_degC", models.IntegerField(blank=True)),
                ("dry_temp_min_degC", models.IntegerField(blank=True)),
                ("dry_temp_max_degC", models.IntegerField(blank=True)),
                ("dry_temp_ideal_degC", models.IntegerField(blank=True)),
                ("dry_time_hrs", models.IntegerField(blank=True)),
            ],
            options={
                "abstract": False,
                "base_manager_name": "objects",
            },
            bases=("inventory.product",),
        ),
        migrations.CreateModel(
            name="Hardware",
            fields=[
                (
                    "product_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="inventory.product",
                    ),
                ),
                ("usage", models.CharField(blank=True, max_length=100)),
                (
                    "kind",
                    models.IntegerField(
                        choices=[(1, "Accessory"), (2, "Parts"), (3, "Hardware")],
                        default=3,
                    ),
                ),
            ],
            options={
                "abstract": False,
                "base_manager_name": "objects",
            },
            bases=("inventory.product",),
        ),
        migrations.CreateModel(
            name="Printer",
            fields=[
                (
                    "product_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="inventory.product",
                    ),
                ),
                ("mfr", models.CharField(default="Bambu Lab", max_length=100)),
                ("model", models.CharField(default="X1 Carbon", max_length=100)),
                ("num_extruders", models.IntegerField()),
                ("bed_length_mm", models.IntegerField(blank=True)),
                ("bed_width_mm", models.IntegerField(blank=True)),
                ("max_height_mm", models.IntegerField(blank=True)),
                (
                    "print_volume_mm3",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=10),
                ),
            ],
            options={
                "abstract": False,
                "base_manager_name": "objects",
            },
            bases=("inventory.product",),
        ),
        migrations.CreateModel(
            name="Shipment",
            fields=[
                (
                    "order_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="inventory.order",
                    ),
                ),
                ("tracking", models.CharField(max_length=200)),
            ],
            options={
                "abstract": False,
                "base_manager_name": "objects",
            },
            bases=("inventory.order",),
        ),
        migrations.CreateModel(
            name="InventoryItem",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("upc", models.CharField(max_length=120)),
                ("shipment", models.CharField(blank=True, max_length=100)),
                ("timestamp", models.DateTimeField(auto_now_add=True)),
                ("date_added", models.DateTimeField(auto_now_add=True)),
                ("object_id", models.PositiveIntegerField()),
                ("last_modified", models.DateTimeField(auto_now=True)),
                ("date_depleted", models.DateTimeField(blank=True, null=True)),
                (
                    "status",
                    models.PositiveSmallIntegerField(
                        choices=[
                            (1, "new"),
                            (2, "in use"),
                            (3, "drying"),
                            (4, "stored"),
                            (5, "depleted"),
                        ],
                        default=1,
                    ),
                ),
                (
                    "content_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="contenttypes.contenttype",
                    ),
                ),
                (
                    "location",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="inventory.location",
                    ),
                ),
                (
                    "product",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="inventory.product",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
    ]
