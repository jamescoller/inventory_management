import re

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import AMS, Dryer, Filament, Hardware, InventoryItem, Location, Printer

# Statuses a user may set by hand. UNKNOWN is audit-internal; DEPLETED/SOLD have
# dedicated actions that also clear the location.
_USER_SETTABLE_STATUSES = [
    (value, label)
    for value, label in InventoryItem.Status.choices
    if value
    not in (
        InventoryItem.Status.UNKNOWN,
        InventoryItem.Status.DEPLETED,
        InventoryItem.Status.SOLD,
    )
]


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["location"].queryset = Location.assignable()


class MoveItemForm(forms.ModelForm):
    class Meta:
        model = InventoryItem
        fields = ["location", "status"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["location"].queryset = Location.assignable()
        self.fields["status"].choices = _USER_SETTABLE_STATUSES


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
            "weight",
            "has_spool",
        ]

    def clean_hex_code(self):
        hex_code = self.cleaned_data.get("hex_code", "")
        if not hex_code:
            return hex_code
        rev_code = hex_code.strip().lower().lstrip("#")
        if not re.fullmatch(r"(?:[0-9a-fA-F]{3}){1,2}", rev_code):
            raise forms.ValidationError(
                "Invalid hex color code. Use 3 or 6 hex digits (e.g. #F0F or #FF00FF)."
            )
        return f"#{rev_code}"


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
            "bed_length_mm",
            "bed_width_mm",
            "max_height_mm",
        ]


class HardwareForm(forms.ModelForm):
    class Meta:
        model = Hardware
        fields = ["name", "upc", "sku", "price", "notes", "qty", "kind"]


class InventoryEditForm(forms.ModelForm):
    class Meta:
        model = InventoryItem
        fields = ["serial_number", "location", "date_depleted"]
        widgets = {
            "location": forms.Select(attrs={"class": "form-select"}),
            "serial_number": forms.TextInput(attrs={"class": "form-control"}),
            "date_depleted": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["location"].queryset = Location.assignable()
