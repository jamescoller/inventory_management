from django.contrib import admin
from polymorphic.admin import PolymorphicParentModelAdmin, PolymorphicChildModelAdmin, PolymorphicChildModelFilter
from .models import *

class ProductChildAdmin(PolymorphicChildModelAdmin):
    base_model = Product

    base_form = ...
    base_fieldsets = (
        ...
    )

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

# @admin.register(Product)
# class ProductParentAdmin(PolymorphicParentModelAdmin):
#     base_model = Product
#     child_models = (Filament, Printer, Hardware, Dryer, AMS)

class OrderChildAdmin(PolymorphicChildModelAdmin):
    base_model = Order

    base_form = ...
    base_fieldsets = (
        ...
    )

@admin.register(Shipment)
class ShipmentAdmin(ProductChildAdmin):
    base_model = Shipment
    show_in_index = True

@admin.register(Order)
class OrderParentAdmin(PolymorphicParentModelAdmin):
    base_model = Order
    child_models = Shipment
    show_in_index = True

admin.site.register(InventoryItem)
admin.site.register(Location)