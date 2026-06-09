import re

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import (
    AMS,
    Dryer,
    Filament,
    Hardware,
    InventoryItem,
    Location,
    MaintenanceEvent,
    Printer,
    PrintJob,
    PrintJobFilament,
)

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


class MaintenanceEventForm(forms.ModelForm):
    """Log a maintenance event for a machine. ``unit`` is bound from the URL by
    the view (the form is always reached from a specific machine's item page), so
    it is not a user-editable field. ``part`` is limited to Hardware products."""

    class Meta:
        model = MaintenanceEvent
        fields = [
            "kind",
            "severity",
            "occurred_at",
            "title",
            "detail",
            "part",
            "cost",
            "downtime_hours",
            "resolved",
        ]
        widgets = {
            "occurred_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "detail": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["occurred_at"].input_formats = [
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d %H:%M:%S",
        ]
        # Only Hardware products are valid parts (screws, hotends, belts, …).
        self.fields["part"].queryset = Hardware.objects.all().order_by("name")
        self.fields["part"].required = False


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


def _printer_items():
    """InventoryItems whose product is a Printer (the machines jobs run on)."""
    return InventoryItem.objects.filter(
        product__polymorphic_ctype__model="printer"
    ).select_related("product")


def _filament_spool_items():
    """Active filament-spool InventoryItems eligible to be consumed by a job."""
    return (
        InventoryItem.objects.filter(product__polymorphic_ctype__model="filament")
        .exclude(status__in=(InventoryItem.Status.DEPLETED, InventoryItem.Status.SOLD))
        .select_related("product")
    )


class PrintJobForm(forms.ModelForm):
    class Meta:
        model = PrintJob
        fields = [
            "printer",
            "name",
            "started_at",
            "ended_at",
            "duration_s",
            "result",
            "notes",
        ]
        widgets = {
            "started_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "ended_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }
        help_texts = {
            "duration_s": "Print duration in seconds (or fill start + end).",
            "name": "gcode / 3mf file name.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["printer"].queryset = _printer_items()
        for f in ("started_at", "ended_at"):
            self.fields[f].input_formats = ["%Y-%m-%dT%H:%M"]


class PrintJobFilamentForm(forms.ModelForm):
    class Meta:
        model = PrintJobFilament
        fields = ["item", "ams_slot", "grams_used", "percent_used"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item"].queryset = _filament_spool_items()
        self.fields["ams_slot"].queryset = Location.objects.filter(
            kind=Location.Kind.AMS_SLOT
        )
        self.fields["ams_slot"].required = False


# Inline formset: the filament lines edited alongside a PrintJob. extra=3 gives a
# few blank rows for the common multi-color case; all are optional.
PrintJobFilamentFormSet = forms.inlineformset_factory(
    PrintJob,
    PrintJobFilament,
    form=PrintJobFilamentForm,
    extra=3,
    can_delete=True,
)


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
