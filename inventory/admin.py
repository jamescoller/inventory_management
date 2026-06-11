import os
import re
import subprocess

from django.contrib import admin
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path
from django.utils.html import format_html
from polymorphic.admin import PolymorphicChildModelAdmin, PolymorphicParentModelAdmin
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin as UnfoldModelAdmin
from unfold.admin import TabularInline as UnfoldTabularInline

from . import items
from .forms import InventoryItemForm
from .models import (
    AMS,
    AMSChannelState,
    AMSUnitState,
    AuditUnknownScan,
    Dryer,
    Filament,
    Hardware,
    InventoryItem,
    Location,
    MaintenanceEvent,
    Material,
    NozzleConfig,
    Printer,
    PrinterDevice,
    PrinterState,
    PrintJob,
    PrintJobFilament,
    Product,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseReceipt,
    PurchaseReceiptLine,
    Supplier,
    TelemetrySample,
)

LOG_PATH = os.path.join(os.path.dirname(__file__), "../inventory.log")

# ----- Specialty Classes for Specific Views ----------


# This allows for the inventory item page in the admin view to show these fields all in the same line as a table
class InventoryItemInline(UnfoldTabularInline):  # or UnfoldStackedInline
    model = InventoryItem
    extra = 0
    fields = ("shipment", "location", "status", "date_depleted")
    readonly_fields = ("date_depleted",)


class MaintenanceEventInline(UnfoldTabularInline):
    """Maintenance timeline shown on a machine's InventoryItem admin page."""

    model = MaintenanceEvent
    fk_name = "unit"
    extra = 0
    fields = (
        "occurred_at",
        "kind",
        "severity",
        "title",
        "part",
        "cost",
        "downtime_hours",
        "resolved",
    )
    autocomplete_fields = ("part",)
    ordering = ("-occurred_at",)


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


class ProductChildAdmin(PolymorphicChildModelAdmin, UnfoldModelAdmin):
    # MRO: polymorphic first (its change_form/history/delete templates +
    # get_form/render_change_form child-fieldset logic must win), Unfold's
    # ModelAdmin last (it sets no templates; its form-widget styling comes from
    # FormFieldModelAdminMixin.formfield_for_dbfield, which polymorphic does not
    # override, so admin form fields still get Unfold styling). Mirrors the
    # SimpleHistoryAdmin + ModelAdmin ordering Unfold documents.
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
    search_fields = ["name", "sku", "upc"]
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
class ProductParentAdmin(PolymorphicParentModelAdmin, UnfoldModelAdmin):
    # See ProductChildAdmin: polymorphic first (its change_list_template wins),
    # Unfold's ModelAdmin last for styling.
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
class InventoryItemAdmin(SimpleHistoryAdmin, UnfoldModelAdmin):
    # SimpleHistoryAdmin first, Unfold ModelAdmin last — the exact ordering from
    # Unfold's django-simple-history integration docs.
    form = InventoryItemForm
    inlines = [MaintenanceEventInline]

    change_list_template = "admin/inventory/inventoryitem/change_list.html"
    # Unfold renders this partial directly above the result list (Unfold dropped
    # Django's content_title block, so the status-badge legend rides here now).
    list_before_template = "admin/inventory/inventoryitem/status_legend.html"

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

    # Match the level keyword anywhere on a line (Django's and the app's log
    # formats differ, so keep it tolerant). Used to drive the level filter.
    _LOG_LEVEL_RE = re.compile(r"\b(DEBUG|INFO|WARNING|ERROR|CRITICAL)\b")

    def view_log(self, request):
        try:
            lines = int(request.GET.get("lines", 1000))
        except (TypeError, ValueError):
            lines = 1000
        lines = max(50, min(lines, 5000))  # bound the tail
        try:
            output = subprocess.check_output(
                ["tail", "-n", str(lines), LOG_PATH],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            raw_lines = output.splitlines()
        except (subprocess.CalledProcessError, FileNotFoundError):
            raw_lines = ["Log file not found."]

        formatted_lines = []
        for i, line in enumerate(raw_lines):
            match = self._LOG_LEVEL_RE.search(line)
            formatted_lines.append(
                {
                    "lineno": i + 1,
                    "level": match.group(1) if match else "",
                    "line": line,
                }
            )

        context = {
            "title": "Inventory Log",
            "log_lines": formatted_lines,
            "shown": len(formatted_lines),
        }

        return TemplateResponse(
            request, "admin/inventory/inventoryitem/log_view.html", context
        )

    @admin.action(description="Mark selected items as Depleted")
    def mark_depleted(self, request, queryset):
        count = 0
        for item in queryset:
            items.deplete(item)
            count += 1
        self.message_user(request, f"{count} items marked as Depleted.")


@admin.register(Location)
class LocationAdmin(UnfoldModelAdmin):
    list_display = ["name", "kind", "parent", "slot_index", "default_status", "unit"]
    list_filter = ["kind", "default_status"]
    list_select_related = ["parent", "unit"]
    search_fields = ["name"]
    autocomplete_fields = ["parent"]
    actions = ["print_location_labels", "print_unit_labels"]

    # Polymorphic product types that represent a trackable physical machine a
    # slot can belong to. Filament/Hardware are never a slot's ``unit``.
    UNIT_PRODUCT_CTYPES = ("ams", "dryer", "printer")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Make the slot->unit picker usable.

        ``unit`` is *not* an autocomplete field (the autocomplete view renders
        options from ``InventoryItem.__str__`` -- product UPC + date -- which is
        identical across units sharing a UPC, and cannot be searched by serial
        number). Instead, give it a plain select that is (a) limited to physical
        unit products and (b) labelled by serial number so the specific item is
        selectable.
        """
        formfield = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if db_field.name == "unit":
            formfield.queryset = (
                InventoryItem.objects.filter(
                    product__polymorphic_ctype__model__in=self.UNIT_PRODUCT_CTYPES
                )
                .select_related("product", "product__polymorphic_ctype")
                .order_by("serial_number", "id")
            )
            formfield.label_from_instance = self._unit_label
        return formfield

    @staticmethod
    def _unit_label(obj):
        sn = (obj.serial_number or "").strip() or "(no serial #)"
        kind = obj.product.polymorphic_ctype.model.upper()
        return f"{sn} — {kind}: {obj.product}"

    @admin.action(description="Print location labels (LOC-<id>)")
    def print_location_labels(self, request, queryset):
        from .barcode_utils import generate_and_print_label, label_qr_url

        printed = 0
        for loc in queryset:
            try:
                generate_and_print_label(
                    data=f"LOC-{loc.pk}",
                    text=loc.name,
                    qr_value=label_qr_url(f"LOC-{loc.pk}"),
                )
                printed += 1
            except Exception as exc:  # noqa: BLE001 - surface to admin, keep going
                self.message_user(
                    request, f"Failed to print {loc.name}: {exc}", level="error"
                )
        self.message_user(request, f"Printed {printed} location label(s).")

    @admin.action(description="Print unit labels (SN barcode + QR) — AMS/dryer/printer")
    def print_unit_labels(self, request, queryset):
        """Label for a machine-unit location (AMS/dryer/printer): a Code128 of the
        unit's serial number (USB-wedge friendly) plus a QR linking to the unit's
        location page. The native phone camera opens that page; the in-app move
        scanner strips the URL to ``LOC-<id>`` -> the slot picker. Non-unit or
        serial-less locations are skipped."""
        from .barcode_utils import print_unit_label

        unit_kinds = (Location.Kind.AMS, Location.Kind.DRYER, Location.Kind.PRINTER)
        printed = 0
        skipped = 0
        for loc in queryset:
            sn = (loc.unit.serial_number or "").strip() if loc.unit_id else ""
            if loc.kind not in unit_kinds or not sn:
                skipped += 1
                continue
            try:
                print_unit_label(sn, loc.pk, loc.name)
                printed += 1
            except Exception as exc:  # noqa: BLE001 - surface to admin, keep going
                self.message_user(
                    request, f"Failed to print {loc.name}: {exc}", level="error"
                )
        self.message_user(
            request,
            f"Printed {printed} unit label(s); skipped {skipped} "
            "(not an AMS/dryer/printer location, or no linked unit serial).",
        )


@admin.register(Material)
class MaterialAdmin(UnfoldModelAdmin):
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
        "build_plate_compat",
        "hot_end_compat",
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
                    "build_plate_compat",
                    "hot_end_compat",
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


@admin.register(AuditUnknownScan)
class AuditUnknownScanAdmin(UnfoldModelAdmin):
    list_display = ("upc", "location", "created_at", "resolved", "dismissed")
    list_filter = ("resolved", "dismissed")
    search_fields = ("upc",)
    list_select_related = ("location",)


@admin.register(MaintenanceEvent)
class MaintenanceEventAdmin(UnfoldModelAdmin):
    list_display = (
        "occurred_at",
        "unit",
        "kind",
        "severity",
        "title",
        "cost",
        "downtime_hours",
        "resolved",
    )
    list_filter = ("kind", "severity", "resolved")
    search_fields = ("title", "detail", "hms_code", "unit__product__name")
    autocomplete_fields = ("part",)
    list_select_related = ("unit__product", "part")
    date_hierarchy = "occurred_at"


@admin.register(NozzleConfig)
class NozzleConfigAdmin(UnfoldModelAdmin):
    list_display = (
        "printer",
        "nozzle_diameter_mm",
        "nozzle_type",
        "hotend_changed_at",
    )
    list_select_related = ("printer__product",)


class PrintJobFilamentInline(UnfoldTabularInline):
    model = PrintJobFilament
    extra = 1
    autocomplete_fields = ["item", "ams_slot"]


@admin.register(PrintJob)
class PrintJobAdmin(UnfoldModelAdmin):
    list_display = (
        "__str__",
        "printer",
        "started_at",
        "duration_s",
        "result",
        "source",
        "completed",
    )
    list_filter = ("result", "source", "completed")
    search_fields = ("name", "telemetry_task_id", "printer__serial_number")
    list_select_related = ("printer",)
    autocomplete_fields = ["printer"]
    inlines = [PrintJobFilamentInline]
    readonly_fields = ("created_at",)


# ----- Procurement (Phase 14) -----


@admin.register(Supplier)
class SupplierAdmin(UnfoldModelAdmin):
    list_display = ("name", "website", "account_ref")
    search_fields = ("name", "account_ref")


class PurchaseOrderLineInline(UnfoldTabularInline):
    model = PurchaseOrderLine
    extra = 1
    # ``product`` uses a raw-id widget rather than autocomplete: the polymorphic
    # ProductParentAdmin doesn't declare search_fields (autocomplete requires it),
    # and adding them there would change the existing product admin.
    raw_id_fields = ("product",)
    fields = (
        "product",
        "description",
        "qty_ordered",
        "qty_received",
        "unit_cost",
        "track_individually",
    )


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(UnfoldModelAdmin):
    list_display = (
        "__str__",
        "supplier",
        "status",
        "ordered_at",
        "expected_at",
        "grand_total",
    )
    list_filter = ("status", "supplier")
    search_fields = ("order_ref", "supplier__name")
    list_select_related = ("supplier",)
    date_hierarchy = "created_at"
    inlines = [PurchaseOrderLineInline]
    readonly_fields = ("created_at", "last_modified")


class PurchaseReceiptLineInline(UnfoldTabularInline):
    model = PurchaseReceiptLine
    extra = 0
    raw_id_fields = ("order_line",)


@admin.register(PurchaseReceipt)
class PurchaseReceiptAdmin(UnfoldModelAdmin):
    list_display = ("__str__", "order", "received_at", "received_by")
    list_filter = ("order__supplier",)
    list_select_related = ("order", "order__supplier", "received_by")
    date_hierarchy = "received_at"
    inlines = [PurchaseReceiptLineInline]
    # ``attachment`` is rendered but inert until media storage is configured.
    fields = ("order", "received_at", "received_by", "attachment", "notes")


# ----- Bambu MQTT telemetry mirror (Phase 16.1) -----
# The state tables are read-only mirrors written by the telemetry consumer;
# only PrinterDevice (registry/config) is editable.


@admin.register(PrinterDevice)
class PrinterDeviceAdmin(UnfoldModelAdmin):
    list_display = (
        "name",
        "serial",
        "ip_address",
        "model_name",
        "enabled",
        "last_seen_at",
    )
    list_filter = ("enabled", "model_name")
    search_fields = ("name", "serial")
    fields = (
        "name",
        "serial",
        "ip_address",
        "model_name",
        "access_code",
        "item",
        "enabled",
        "last_seen_at",
    )
    readonly_fields = ("last_seen_at",)


@admin.register(PrinterState)
class PrinterStateAdmin(UnfoldModelAdmin):
    list_display = (
        "device",
        "gcode_state",
        "mc_percent",
        "nozzle_temp",
        "bed_temp",
        "updated_at",
    )
    list_filter = ("gcode_state",)

    def has_add_permission(self, request):
        return False


@admin.register(AMSUnitState)
class AMSUnitStateAdmin(UnfoldModelAdmin):
    list_display = ("device", "ams_index", "humidity", "temp", "dry_time", "updated_at")

    def has_add_permission(self, request):
        return False


@admin.register(AMSChannelState)
class AMSChannelStateAdmin(UnfoldModelAdmin):
    list_display = (
        "device",
        "ams_index",
        "tray_index",
        "tray_type",
        "color_hex",
        "remain_pct",
        "updated_at",
    )
    list_filter = ("tray_type",)

    def has_add_permission(self, request):
        return False


@admin.register(TelemetrySample)
class TelemetrySampleAdmin(UnfoldModelAdmin):
    list_display = (
        "device",
        "ts",
        "gcode_state",
        "mc_percent",
        "nozzle_temp",
        "bed_temp",
    )
    list_filter = ("device", "gcode_state")
    date_hierarchy = "ts"

    def has_add_permission(self, request):
        return False
