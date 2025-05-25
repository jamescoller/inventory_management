from django.contrib import admin
from django.utils.html import format_html
from django import forms
from django.contrib.admin import AllValuesFieldListFilter
from polymorphic.admin import (
    PolymorphicParentModelAdmin,
    PolymorphicChildModelAdmin,
    PolymorphicChildModelFilter,
)
from django.contrib.contenttypes.models import ContentType
from .models import *


# ----- Specialty Classes for Specific Views ----------


# This allows for the inventory item page in the admin view to show these fields all in the same line as a table
class InventoryItemInline(admin.TabularInline):  # or admin.StackedInline
    model = InventoryItem
    extra = 0
    fields = ("shipment", "location", "status", "date_depleted")
    readonly_fields = ("date_depleted",)


# Limit what product types are shown in the product type filter
class ProductTypeFilter(admin.SimpleListFilter):
    title = "Product Type"
    parameter_name = "product_type"  # URL will be ?product_type=<ct_id>

    def lookups(self, request, model_admin):
        # Only include these five subclass ContentTypes:
        allowed = (AMS, Printer, Dryer, Filament, Hardware)
        cts = ContentType.objects.get_for_models(*allowed)
        # Return (value, label) tuples:
        return [
            (str(ct.id), model._meta.verbose_name.title()) for model, ct in cts.items()
        ]

    def queryset(self, request, queryset):
        val = self.value()
        if val:
            # Filter on the FK id for polymorphic_ctype:
            return queryset.filter(product__polymorphic_ctype_id=val)
        return queryset


# This allows us to hide the serial number field for everything except the Printer, AMS, or Dryer.
class InventoryItemForm(forms.ModelForm):
    class Meta:
        model = InventoryItem
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # figure out which product we're dealing with:
        product = None
        if self.instance and self.instance.pk:
            # editing an existing InventoryItem
            product = self.instance.product
        else:
            # creating a new one—try to grab from the POST/GET
            pid = self.data.get("product") or self.initial.get("product")
            if pid:
                try:
                    product = Product.objects.get(pk=pid)
                except Product.DoesNotExist:
                    product = None

        # if it’s not AMS, Printer or Dryer, remove the field
        allowed = (AMS, Printer, Dryer)
        if not (product and isinstance(product, allowed)):
            self.fields.pop("serial_number", None)


# ----- Polymorphic Child Admins -----


class ProductChildAdmin(PolymorphicChildModelAdmin):
    base_model = Product


@admin.register(Filament)
class FilamentAdmin(ProductChildAdmin):
    base_model = Filament
    show_in_index = True


@admin.register(Printer)
class PrinterAdmin(ProductChildAdmin):
    base_model = Printer
    show_in_index = True


@admin.register(Hardware)
class HardwareAdmin(ProductChildAdmin):
    base_model = Hardware
    show_in_index = True


@admin.register(Dryer)
class DryerAdmin(ProductChildAdmin):
    base_model = Dryer
    show_in_index = True


@admin.register(AMS)
class AMSAdmin(ProductChildAdmin):
    base_model = AMS
    show_in_index = True


class OrderChildAdmin(PolymorphicChildModelAdmin):
    base_model = Order


@admin.register(Shipment)
class ShipmentAdmin(ProductChildAdmin):
    base_model = Shipment
    show_in_index = True


# ----- Polymorphic Parent Admin -----


@admin.register(Product)
class ProductParentAdmin(PolymorphicParentModelAdmin):
    base_model = Product
    child_models = (
        Filament,
        Printer,
        Hardware,
        Dryer,
        AMS,
    )
    inlines = [InventoryItemInline]


@admin.register(Order)
class OrderParentAdmin(PolymorphicParentModelAdmin):
    base_model = Order
    child_models = (Shipment,)
    show_in_index = True


# ----- InventoryItem Admin -----


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    change_list_template = "admin/inventory/inventoryitem/change_list.html"
    # this controls which columns show up in the changelist
    list_display = (
        "product",
        "shipment",
        "timestamp",
        "status_badge",
        "location",
        "date_depleted",
        "get_product_type",
    )

    # Quick filters in the sidebar
    list_filter = (
        "status",
        "location",
        ProductTypeFilter,
    )

    # this adds the search bar and tells it what fields to search
    search_fields = [
        "product__name",  # search by the Product’s name
        "product__sku",  # or by SKU
        "product__upc",  # or by UPC
        "location__name",  # or by Location name
        "product__polymorphic_ctype__model",  # or by class name
        "serial_number",  # or by serial number
    ]

    # Incorporate the custom form from above that removes the S/N field if the class doesn't support it
    form = InventoryItemForm

    class Media:
        css = {"all": ("inventory/css/admin-badges.css",)}

    def status_badge(self, obj):
        label = obj.get_status_display().title()
        class_map = {
            obj.Status.NEW: "badge-new",
            obj.Status.IN_USE: "badge-in-use",
            obj.Status.DRYING: "badge-drying",
            obj.Status.STORED: "badge-stored",
            obj.Status.DEPLETED: "badge-depleted",
        }
        css_class = class_map.get(obj.status, "")
        return format_html('<span class="badge {}">{}</span>', css_class, label)

    status_badge.short_description = "Status"
    status_badge.admin_order_field = "status"

    def get_product_name(self, obj):
        # the usual display (what you’d get from __str__)
        return str(obj.product.get_real_instance())

    get_product_name.short_description = "Product"

    def get_product_type(self, obj):
        real = obj.product.get_real_instance()

        # returns 'Printer', 'AMS', 'Dryer', etc.
        # return real.__class__.__name__
        return real._meta.verbose_name.title()

    get_product_type.short_description = "Product Type"

    # Lets customize some of the admin actions that come in the drop down at the top of the admin screen
    # Explicitly declare the admin actions below
    actions = ["mark_depleted"]

    @admin.action(description="Mark selected items as Depleted")
    def mark_depleted(self, request, queryset):
        updated = queryset.update(status=InventoryItem.Status.DEPLETED)
        self.message_user(request, f"{updated} items marked as Depleted.")
        pass


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ["name", "default_status"]
    list_filter = ["default_status"]
