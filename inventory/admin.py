from django.contrib import admin
from django.utils.html import format_html
from django import forms
from polymorphic.admin import (
    PolymorphicParentModelAdmin,
    PolymorphicChildModelAdmin,
    PolymorphicChildModelFilter,
)
from .models import *


# ----- Specialty Classes for Specific Views ----------


# This allows for the inventory item page in the admin view to show these fields all in the same line as a table
class InventoryItemInline(admin.TabularInline):  # or admin.StackedInline
    model = InventoryItem
    extra = 0
    fields = ("shipment", "location", "status", "date_depleted")
    readonly_fields = ("date_depleted",)


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
    list_display = (
        "product",
        "shipment",
        "timestamp",
        "status_badge",
        "location",
        "date_depleted",
    )
    list_filter = ("status", "location")

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


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ["name", "default_status"]
    list_filter = ["default_status"]
