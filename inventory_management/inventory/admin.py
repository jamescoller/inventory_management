from django.contrib import admin
from .models import InventoryItem, Category, Location

admin.site.register(InventoryItem)
admin.site.register(Category)
admin.site.register(Location)