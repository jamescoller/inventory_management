from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from .models import *


class UserRegisterForm(UserCreationForm):
    email = forms.EmailField()

    class Meta:
        model = User
        fields = ["username", "email", "password1", "password2"]


class InventoryItemForm(forms.ModelForm):
    upc = forms.CharField(required=False, help_text="Scan or enter UPC (preferred).")
    sku = forms.CharField(required=False, help_text="Enter SKU if UPC is unavailable.")

    class Meta:
        model = InventoryItem
        fields = ["shipment", "location", "status", "serial_number"]
        help_texts = {
            "shipment": "Scan or enter shipment tracking number, or enter arrival date if no tracking is available.",
        }

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            product = self.instance.product if self.instance else None
            if not (product and hasattr(product, "serial_number")):
                self.fields.pop("serial_number", None)


class MoveItemForm(forms.ModelForm):
    class Meta:
        model = InventoryItem
        fields = ["location", "status"]


class FilamentForm(forms.ModelForm):
    class Meta:
        model = Filament
        fields = [
            "name",
            "upc",
            "sku",
            "price",
            "notes",
            "category",
            "material",
            "material_type",
            "color",
            "hex_code",
        ]


class AMSForm(forms.ModelForm):
    class Meta:
        model = AMS
        fields = [
            "name",
            "upc",
            "sku",
            "price",
            "notes",
            "category",
            "mfr",
            "model",
            "num_slots",
        ]


class DryerForm(forms.ModelForm):
    class Meta:
        model = Dryer
        fields = [
            "name",
            "upc",
            "sku",
            "price",
            "notes",
            "category",
            "mfr",
            "model",
            "num_slots",
            "max_temp_degC",
        ]


class PrinterForm(forms.ModelForm):
    class Meta:
        model = Printer
        fields = [
            "name",
            "upc",
            "sku",
            "price",
            "notes",
            "category",
            "mfr",
            "model",
            "num_extruders",
        ]


class HardwareForm(forms.ModelForm):
    class Meta:
        model = Hardware
        fields = ["name", "upc", "sku", "price", "notes", "category", "usage"]


class InventoryEditForm(forms.ModelForm):
    class Meta:
        model = InventoryItem
        fields = ["location", "status", "date_depleted"]
