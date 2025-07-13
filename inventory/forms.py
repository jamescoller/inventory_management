from django import forms
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
        fields = ["shipment", "location", "serial_number"]
        help_texts = {
            "shipment": "Scan or enter shipment tracking number, or enter arrival date if no tracking is available.",
        }

        # def __init__(self, *args, **kwargs):
        #     super().__init__(*args, **kwargs)
        #     if not (product and hasattr(product, "serial_number")):
        #         self.fields.pop("serial_number", None)


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
            "material",
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
            "mfr",
            "model",
            "num_extruders",
        ]


class HardwareForm(forms.ModelForm):
    class Meta:
        model = Hardware
        fields = ["name", "upc", "sku", "price", "notes", "qty", "kind"]


class InventoryEditForm(forms.ModelForm):
    class Meta:
        model = InventoryItem
        fields = ["serial_number", "location", "status", "date_depleted"]
        widgets = {
            "status": forms.Select(attrs={"class": "form-select"}),
            "location": forms.Select(attrs={"class": "form-select"}),
            "serial_number": forms.TextInput(attrs={"class": "form-control"}),
            "date_depleted": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
        }
