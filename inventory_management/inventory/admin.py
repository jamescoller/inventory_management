from django.contrib import admin
from .models import *

admin.site.register(InventoryItem)
admin.site.register(Location)
admin.site.register(Shipment)
admin.site.register(Filament)
admin.site.register(Printer)
admin.site.register(Dryer)
admin.site.register(AMS)
admin.site.register(Hardware)