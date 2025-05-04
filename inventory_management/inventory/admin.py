from django.contrib import admin
from polymorphic.admin import PolymorphicParentModelAdmin, PolymorphicChildModelAdmin, PolymorphicChildModelFilter
from .models import *

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
class HardwareAdmin(ProductChildAdmin):
    base_model = Dryer
    show_in_index = True

@admin.register(AMS)
class HardwareAdmin(ProductChildAdmin):
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
    child_models = (Filament, Printer, Hardware, Dryer, AMS,)
    list_display = ('name', 'upc', 'category')

@admin.register(Order)
class OrderParentAdmin(PolymorphicParentModelAdmin):
    base_model = Order
    child_models = (Shipment,)
    show_in_index = True

# ----- InventoryItem Admin -----

@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = ('product', 'tracking_number', 'timestamp')

@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ('name')