import os
import subprocess

from django.contrib import admin
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path
from django.utils.html import format_html
from polymorphic.admin import PolymorphicChildModelAdmin, PolymorphicParentModelAdmin

from .forms import InventoryItemForm
from .models import (
    AMS,
    Dryer,
    Filament,
    Hardware,
    InventoryItem,
    Location,
    Material,
    Printer,
    Product,
)

LOG_PATH = os.path.join(os.path.dirname(__file__), "../inventory.log")

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


# ----- Polymorphic Child Admins -----


class ProductChildAdmin(PolymorphicChildModelAdmin):
    base_model = Product


@admin.register(Filament)
class FilamentAdmin(ProductChildAdmin):
    base_model = Filament
    show_in_index = True
    list_display = ["name", "material", "color", "hex_code", "get_sku", "color_family"]
    list_filter = ["material", "color_family"]
    search_fields = ["name", "notes", "color", "color_family", "hex_code", "get_sku"]
    actions = ["bulk_update_material"]
    fields = [
        "color",
        "hex_code",
        "material",
        "weight",
        "has_spool",
        "notes",
        "color_family",
    ]

    def get_sku(self, obj):
        return obj.sku

    get_sku.short_description = "SKU"  # Column header in admin

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "bulk-update-material/",
                self.admin_site.admin_view(self.bulk_update_material_view),
                name="bulk_update_material",
            ),
        ]
        return custom_urls + urls

    # @admin.action(description="Set filament material for selected items")
    def bulk_update_material(self, request, queryset):
        # Store selected items in session
        selected = request.POST.getlist("_selected_action")
        request.session["selected_filaments"] = selected

        return HttpResponseRedirect("bulk-update-material/")

    bulk_update_material.short_description = "Update material for selected filaments"

    def bulk_update_material_view(self, request):
        # Get the list of selected items from session
        selected_filaments = request.session.get("selected_filaments", [])
        queryset = self.model.objects.filter(pk__in=selected_filaments)

        # Handle form submission
        if request.method == "POST" and "apply" in request.POST:
            material_id = request.POST.get("new_matl")
            try:
                material = Material.objects.get(pk=material_id)
                queryset.update(material=material)
                self.message_user(
                    request, f"Successfully updated {queryset.count()} filaments."
                )
                return HttpResponseRedirect("../")
            except (Material.DoesNotExist, ValidationError) as e:
                self.message_user(
                    request, f"Error updating materials: {str(e)}", level="ERROR"
                )

        # Prepare context for template
        context = {
            "title": "Update Material",
            "queryset": queryset,
            "materials": Material.objects.all().order_by("name"),
            "opts": self.model._meta,
            "app_label": self.model._meta.app_label,
        }

        # Render form template
        return TemplateResponse(
            request,
            "admin/inventory/filament/bulk_update_material.html",
            context,
        )


@admin.register(Printer)
class PrinterAdmin(ProductChildAdmin):
    base_model = Printer
    show_in_index = True
    fields = [
        "mfr",
        "model",
        "sku",
        "upc",
        "num_extruders",
        "bed_length_mm",
        "bed_width_mm",
        "max_height_mm",
        "print_volume_m3",
    ]


@admin.register(Hardware)
class HardwareAdmin(ProductChildAdmin):
    base_model = Hardware
    show_in_index = True
    fields = [
        "qty",
        "kind",
    ]


@admin.register(Dryer)
class DryerAdmin(ProductChildAdmin):
    base_model = Dryer
    show_in_index = True
    fields = ["mfr", "model", "num_slots", "max_temp_degC"]


@admin.register(AMS)
class AMSAdmin(ProductChildAdmin):
    base_model = AMS
    show_in_index = True
    fields = [
        "mfr",
        "model",
        "num_slots",
    ]


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
    fields = ["sku", "upc"]


# ----- InventoryItem Admin -----


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    form = InventoryItemForm

    change_list_template = "admin/inventory/inventoryitem/change_list.html"

    # this controls which columns show up in the changelist
    list_display = (
        "product",
        "shipment",
        "date_added",
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
    ]

    readonly_fields = ("display_product_details",)

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("product__polymorphic_ctype", "location")
        )

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "product",
                    "shipment",
                    "location",
                    "status",
                    "date_depleted",
                    "serial_number",
                    "display_product_details",
                )
            },
        ),
    )

    def get_fields(self, request, obj=None):
        fields = []
        if isinstance(obj, InventoryItem):
            fields.append(
                ["product", "shipment", "location", "status", "date_depleted"]
            )
        if obj and hasattr(obj.product, "serial_number"):
            fields.append("serial_number")
        fields.append("display_product_details")
        return fields

    def display_product_details(self, obj):
        product = obj.product.get_real_instance()
        details = []
        if isinstance(product, Filament):
            details.append(f"Material: {product.material}")
            details.append(f"Color: {product.color} ({product.hex_code})")
            details.append(f"SKU: {product.sku}")
            details.append(f"UPC: {product.upc}")
        elif isinstance(product, Printer):
            details.append(f"MFR: {product.mfr}")
            details.append(f"Model: {product.model}")
            if obj.serial_number:
                details.append(f"Serial: {obj.serial_number}")
        elif isinstance(product, Hardware):
            details.append(f"Kind: {product.get_kind_display()}")
            if product.qty:
                details.append(f"Qty: {product.qty}")
        elif isinstance(product, Dryer):
            details.append(f"MFR: {product.mfr}")
            details.append(f"Model: {product.model}")
            if obj.serial_number:
                details.append(f"Serial: {obj.serial_number}")
        elif isinstance(product, AMS):
            details.append(f"MFR: {product.mfr}")
            details.append(f"Model: {product.model}")
            if obj.serial_number:
                details.append(f"Serial: {obj.serial_number}")
        return " | ".join(details)

    display_product_details.short_description = "Product Details"

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
        return real._meta.verbose_name.title()

    get_product_type.short_description = "Product Type"

    # Lets customize some of the admin actions that come in the drop down at the top of the admin screen
    # Explicitly declare the admin actions below
    actions = ["mark_depleted"]

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "view-log/",
                self.admin_site.admin_view(self.view_log),
                name="inventory-log",
            ),
        ]
        return custom_urls + urls

    def view_log(self, request):
        try:
            output = subprocess.check_output(
                ["tail", "-n", "200", LOG_PATH], text=True, stderr=subprocess.DEVNULL
            )
            raw_lines = output.splitlines()
        except (subprocess.CalledProcessError, FileNotFoundError):
            raw_lines = ["Log file not found."]

        formatted_lines = [
            {"lineno": i + 1, "line": line} for i, line in enumerate(raw_lines)
        ]

        context = {
            "title": "Inventory Log",
            "log_lines": formatted_lines,
        }

        return TemplateResponse(
            request, "admin/inventory/inventoryitem/log_view.html", context
        )

    @admin.action(description="Mark selected items as Depleted")
    def mark_depleted(self, request, queryset):
        count = 0
        for item in queryset:
            item.mark_depleted()
            item.save()
            count += 1
        self.message_user(request, f"{count} items marked as Depleted.")


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ["name", "kind", "parent", "slot_index", "default_status", "unit"]
    list_filter = ["kind", "default_status"]
    list_select_related = ["parent", "unit"]
    search_fields = ["name"]
    autocomplete_fields = ["parent", "unit"]
    actions = ["print_location_labels"]

    @admin.action(description="Print location labels (LOC-<id>)")
    def print_location_labels(self, request, queryset):
        from .barcode_utils import generate_and_print_label

        printed = 0
        for loc in queryset:
            try:
                generate_and_print_label(data=f"LOC-{loc.pk}", text=loc.name)
                printed += 1
            except Exception as exc:  # noqa: BLE001 - surface to admin, keep going
                self.message_user(
                    request, f"Failed to print {loc.name}: {exc}", level="error"
                )
        self.message_user(request, f"Printed {printed} location label(s).")


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "material_type",
        "mfr",
        "print_temp_min_degC",
        "print_temp_max_degC",
        "print_temp_ideal_degC",
        "dry_temp_min_degC",
        "dry_temp_max_degC",
        "dry_temp_ideal_degC",
        "dry_time_hrs",
        "ams_capable",
        "drying_required",
        "notes",
    ]
    # name is the list_display_links field (clickable link); only material_type
    # is editable inline — Django disallows editing the first list_display field
    # unless list_display_links is explicitly set to something else.
    list_display_links = ["name"]
    list_editable = ["material_type"]
    list_filter = ["mfr", "ams_capable", "drying_required"]
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "name",
                    "material_type",
                    "mfr",
                    "print_temp_min_degC",
                    "print_temp_max_degC",
                    "print_temp_ideal_degC",
                    "dry_temp_min_degC",
                    "dry_temp_max_degC",
                    "dry_temp_ideal_degC",
                    "dry_time_hrs",
                    "ams_capable",
                    "drying_required",
                    "notes",
                )
            },
        ),
        (
            "Guide Properties",
            {
                "fields": (
                    "description",
                    "uv_resistant",
                    "flexible",
                    "high_strength",
                    "heat_resistant",
                    "food_safe",
                    "easy_to_print",
                    "budget_friendly",
                    "impact_resistant",
                    "requires_enclosure",
                )
            },
        ),
    )
