import logging
import re
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlencode

import django_filters
import openpyxl
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils.html import escape
from django.utils.timezone import localtime, now as timezone_now
from django.views.generic import CreateView, TemplateView, UpdateView, View

from .barcode_utils import generate_and_print_barcode
from .forms import (
    AMSForm,
    DryerForm,
    FilamentForm,
    HardwareForm,
    InventoryEditForm,
    InventoryItemForm,
    PrinterForm,
    UserRegisterForm,
)
from .models import (
    AMS,
    Dryer,
    Filament,
    Hardware,
    InventoryItem,
    Location,
    Printer,
    Product,
)

logger = logging.getLogger("inventory")

# InventoryItem statuses that count as "active" (not consumed or sold)
_ACTIVE_STATUSES = [
    InventoryItem.Status.NEW,
    InventoryItem.Status.IN_USE,
    InventoryItem.Status.DRYING,
    InventoryItem.Status.STORED,
]

# Representative hex color for each filament color family
COLOR_FAMILY_HEX = {
    "RED": "#e74c3c",
    "ORANGE": "#e67e22",
    "YELLOW": "#f1c40f",
    "GREEN": "#27ae60",
    "BLUE": "#2980b9",
    "PURPLE": "#8e44ad",
    "PINK": "#fd79a8",
    "BROWN": "#8B4513",
    "BLACK": "#2c3e50",
    "GRAY": "#95a5a6",
    "WHITE": "#ecf0f1",
    "TRANSLUCENT": "#dfe6e9",
}

FAMILY_ORDER = [
    "RED", "ORANGE", "YELLOW", "GREEN", "BLUE", "PURPLE",
    "PINK", "BROWN", "BLACK", "GRAY", "WHITE", "TRANSLUCENT",
]

# ---- Barcode Writer Helpers --------


class PrintBarcodeView(LoginRequiredMixin, View):

    def get(self, request, item_id, mode):
        # 1. Get the item
        item = get_object_or_404(
            InventoryItem.objects.select_related("product"), id=item_id
        )

        try:
            # 2. Generate and print the barcode (returns PIL image)
            response = generate_and_print_barcode(item, mode)

            # 3. Return as HTTP response
            return response

        except Exception as e:
            return HttpResponse(f"Barcode generation failed: {str(e)}", status=500)

    def post(self, request, item_id, mode):
        item = get_object_or_404(InventoryItem, id=item_id)
        try:
            generate_and_print_barcode(item, mode)
        except Exception as e:
            logger.error(f"Barcode generation failed: {str(e)}")
            return HttpResponse(str(e), status=500)

        if request.headers.get("HX-Request"):
            html_body = render_to_string(
                "inventory/partials/print_confirmations.html",
                {
                    "item": item,
                    "mode": mode,
                },
            )
            html_wrapped = f'<div id="print-result" class="alert alert-success mt-2">{html_body}</div>'
            return HttpResponse(html_wrapped)

        return redirect("inventory_edit", item_id=item_id)


class BarcodeRedirectView(LoginRequiredMixin, View):
    def get(self, request, value):
        if value.startswith("INV-"):
            item_id = value.replace("INV-", "")
            return redirect("inventory_edit", item_id=item_id)
        return HttpResponse("Invalid barcode", status=400)


class AboutView(TemplateView):
    template_name = "inventory/about.html"


class AddProductChoiceView(LoginRequiredMixin, CreateView):
    def get(self, request):
        upc = request.session.get("pending_inventory", {}).get("upc", "")
        return render(request, "inventory/add_product_choice.html", {"upc": upc})


class InventoryFilter(django_filters.FilterSet):
    sku = django_filters.CharFilter(
        field_name="product__sku", lookup_expr="exact", label="SKU"
    )
    upc = django_filters.CharFilter(
        field_name="product__upc", lookup_expr="exact", label="UPC"
    )
    name = django_filters.CharFilter(
        field_name="product__name", lookup_expr="icontains", label="Name"
    )

    class Meta:
        model = InventoryItem
        fields = ["sku", "upc", "name"]


class InventorySearchView(LoginRequiredMixin, View):
    def get(self, request):
        # Get search parameters from the query string
        sku = request.GET.get("sku", "")
        upc = request.GET.get("upc", "")
        name = request.GET.get("name", "")
        location = request.GET.get("location", "")
        serial_number = request.GET.get("serial_number", "")
        item_id = request.GET.get("item_id", "")

        # Check for INV_xxx pattern
        inv_pattern = re.match(r"^INV-(\d+)$", name.strip())
        if inv_pattern:
            item_id = inv_pattern.group(1)
            return redirect("inventory_edit", item_id=item_id)

        # Base queryset, excluding depleted items
        items = InventoryItem.objects.exclude(status=5).select_related(
            "product", "location"
        )

        # If there's a simple search from the navbar, search across multiple fields
        if name and not any([sku, upc, location, serial_number, item_id]):
            items = items.filter(
                Q(product__name__icontains=name)
                | Q(product__sku__icontains=name)
                | Q(product__upc__icontains=name)
                | Q(location__name__icontains=name)
                | Q(serial_number__icontains=name)
                | Q(id__icontains=name)
            )
        else:
            # Apply specific filters
            if sku:
                items = items.filter(product__sku=sku)
            if upc:
                items = items.filter(product__upc=upc)
            if name:
                items = items.filter(product__name__icontains=name)
            if location:
                items = items.filter(location__name__icontains=location)
            if serial_number:
                items = items.filter(serial_number=serial_number)
            if item_id:
                items = items.filter(id=item_id)

        # Pass filtered items to the template
        context = {
            "items": items or InventoryItem.objects.none(),
            "search_values": {
                "sku": sku,
                "upc": upc,
                "name": name,
                "location": location,
                "serial_number": serial_number,
                "item_id": item_id,
            },
            "status_choices": InventoryItem.Status.choices,
            "locations": Location.objects.all().order_by("name"),
        }

        return render(request, "inventory/inventory_search.html", context)


class InventoryEditView(LoginRequiredMixin, UpdateView):
    def get(self, request, item_id):
        item = get_object_or_404(
            InventoryItem.objects.select_related("product"), id=item_id
        )
        form = InventoryEditForm(instance=item)
        return render(
            request,
            "inventory/inventory_edit.html",
            {"form": form, "item": item, "product": item.product},
        )

    def post(self, request, item_id):
        item = get_object_or_404(InventoryItem, id=item_id)
        action = request.POST.get("action")

        # Handle depleted/sold actions
        if action in ["deplete", "sell"]:
            if action == "deplete":
                if hasattr(item, "mark_depleted"):
                    item.mark_depleted()
                    item.save()
                    messages.success(
                        request, f"Item '{item}' has been marked as depleted."
                    )
                else:
                    messages.error(request, "This item cannot be marked as depleted.")
            elif action == "sell":
                if hasattr(item, "mark_sold"):
                    item.mark_sold()
                    item.save()
                    messages.success(request, f"Item '{item}' has been marked as sold.")
                else:
                    messages.error(request, "This item cannot be marked as sold.")
            return redirect("inventory_edit", item_id=item_id)

        # Handle the regular form submission
        old_location = item.location
        form = InventoryEditForm(request.POST, instance=item)  # Bind form with instance

        if form.is_valid():
            new_location = form.cleaned_data["location"]
            warning = item.filament_drying_warning(new_location)

            if warning:
                level, message, needs_ack = warning

                if level == "error":
                    form.add_error("location", message)
                    return render(
                        request,
                        "inventory/inventory_edit.html",
                        {"form": form, "item": item, "product": item.product},
                    )

                if needs_ack and not request.POST.get("acknowledged"):
                    return render(
                        request,
                        "inventory/inventory_edit.html",
                        {
                            "form": form,
                            "item": item,
                            "product": item.product,
                            "warning_level": level,
                            "warning_message": message,
                            "requires_ack": True,
                            "pending_location": new_location.id,
                        },
                    )

                if level == "info":
                    messages.info(request, message)
                elif level == "warning":
                    messages.warning(request, message)

            form.save()
            return redirect("inventory_search")
        else:
            # Form is not valid, render the page with errors
            return render(
                request,
                "inventory/inventory_edit.html",
                {"form": form, "item": item, "product": item.product},
            )


class AddInventoryView(LoginRequiredMixin, CreateView):
    model = InventoryItem
    form_class = InventoryItemForm
    template_name = "inventory/item_form.html"
    success_url = reverse_lazy("add_inventory")

    def get_initial(self):
        initial = super().get_initial()
        if InventoryItem.objects.exists():
            latest = InventoryItem.objects.order_by("-id").first()
            initial["shipment"] = latest.shipment
            initial["location"] = latest.location
        return initial

    def post(self, request, **kwargs):

        form = self.form_class(request.POST)

        if not form.is_valid():
            return self.form_invalid(form)

        upc = form.cleaned_data.get("upc")
        sku = form.cleaned_data.get("sku")
        shipment = form.cleaned_data.get("shipment")
        location = form.cleaned_data.get("location")

        if not upc and not sku:
            messages.error(request, "You must provide either a UPC or SKU.")
            return redirect("add_inventory")

        product = None

        if upc:
            product = Product.objects.filter(upc=upc).first()

        if product is None and sku:
            product = Product.objects.filter(sku=sku).first()

        # If still no product found, redirect to 'add_product_choice'
        if product is None:
            # Store scanned data temporarily in session
            request.session["pending_inventory"] = {
                "upc": upc,
                "sku": sku,
                "shipment": shipment,
                "location_id": location.id if location else None,
            }
            messages.warning(
                request,
                f"No product found with that UPC or SKU. Please add the product before continuing.",
            )
            return redirect("add_product_choice")  # This is a new view we’ll create
            # messages.error(request, f"No product found with UPC: {upc}")
            # return redirect('add_inventory')

        # Create InventoryItem only if a product was found
        messages.info(
            request,
            f"Matched product: {product.name} (SKU: {product.sku}, UPC: {product.upc})",
        )

        new_item = InventoryItem.objects.create(
            product=product,
            shipment=shipment,
            location=location,
        )

        messages.success(request, f"Added {product.name} to inventory")
        logger.info(f"Added {product.name} to inventory")

        try:
            generate_and_print_barcode(new_item, mode="unique")
            # generate_and_print_barcode(new_item, mode="upc")
        except Exception as e:
            messages.warning(request, f"Label printing failed: {e}")
            logger.error(f"Label printing failed: {e}")

        # After successful item creation and label printing
        html = render_to_string(
            "inventory/partials/print_confirmations.html",
            {
                "item": new_item,
                "mode": "unique",
            },
        )
        messages.success(request, html)

        return redirect("add_inventory")

    def form_valid(self, form):
        response = super().form_valid(form)

        try:
            generate_and_print_barcode(self.object, mode="unique")
        except Exception as e:
            messages.error(self.request, f"Label print failed: {e}")
            logger.error(f"label printing failed: {e}")

        return response


class Index(TemplateView):
    template_name = "inventory/index.html"


class BulkUpdateView(LoginRequiredMixin, View):
    def get(self, request):
        return redirect("inventory_search")

    def post(self, request):
        raw_ids = request.POST.getlist("item_ids")
        try:
            item_ids = [int(i) for i in raw_ids if str(i).strip()]
        except (ValueError, TypeError):
            messages.warning(request, "Invalid item selection.")
            return self._redirect_back(request)

        if not item_ids:
            messages.warning(request, "No items selected.")
            return self._redirect_back(request)

        MAX_BULK = 200
        if len(item_ids) > MAX_BULK:
            messages.error(request, f"Cannot update more than {MAX_BULK} items at once.")
            return self._redirect_back(request)

        new_status_raw = request.POST.get("bulk_status", "").strip()
        new_location_id = request.POST.get("bulk_location", "").strip()
        new_shipment = request.POST.get("bulk_shipment", "").strip() or None

        if new_shipment and len(new_shipment) > 100:
            messages.error(request, "Shipment value is too long (max 100 characters).")
            return self._redirect_back(request)

        new_status = None
        if new_status_raw:
            try:
                val = int(new_status_raw)
                InventoryItem.Status(val)   # raises ValueError if not a valid choice
                new_status = val
            except ValueError:
                messages.error(request, "Invalid status value.")
                return self._redirect_back(request)

        new_location = None
        if new_location_id:
            try:
                new_location = Location.objects.get(pk=new_location_id)
            except Location.DoesNotExist:
                messages.error(request, "Invalid location.")
                return self._redirect_back(request)

        if new_status is None and new_location is None and new_shipment is None:
            messages.warning(request, "No fields selected — nothing was changed.")
            return self._redirect_back(request)

        count = 0
        with transaction.atomic():
            for item in InventoryItem.objects.filter(id__in=item_ids):
                status_clears_location = False
                if new_status is not None:
                    item.status = new_status
                    item._skip_status_from_location = True
                    if new_status in (InventoryItem.Status.DEPLETED, InventoryItem.Status.SOLD):
                        status_clears_location = True
                if new_location is not None and not status_clears_location:
                    item.location = new_location
                if new_shipment is not None:
                    item.shipment = new_shipment
                item.save()
                count += 1

        messages.success(request, f"Updated {count} item{'s' if count != 1 else ''}.")
        return self._redirect_back(request)

    def _redirect_back(self, request):
        filter_keys = ("sku", "upc", "name", "status", "location", "serial_number", "item_id")
        params = {k: request.POST.get(k, "") for k in filter_keys if request.POST.get(k, "")}
        url = reverse("inventory_search")
        if params:
            url += "?" + urlencode(params)
        return redirect(url)


class SignUpView(View):
    def get(self, request):
        form = UserRegisterForm()
        return render(request, "inventory/signup.html", {"form": form})

    def post(self, request):
        form = UserRegisterForm(request.POST)

        if form.is_valid():
            form.save()
            user = authenticate(
                username=form.cleaned_data["username"],
                password=form.cleaned_data["password1"],
            )
            logger.info(f"User created: {user.username}")

            login(request, user)
            return redirect("index")

        return render(request, "inventory/signup.html", {"form": form})


def _build_low_stock_alerts():
    """Return low-stock alert rows, sorted by urgency.

    Two DB queries:
    1. Active (non-depleted, non-sold) items grouped by product SKU — filtered to < LOW_QUANTITY.
    2. Items depleted in the last 30 days grouped by product SKU — used as "recently consumed" signal.

    Products with zero active items that were recently depleted are included as "Out of Stock".
    """
    low_qty = getattr(settings, "LOW_QUANTITY", 3)
    thirty_days_ago = timezone_now() - timedelta(days=30)

    # Products with some active inventory that is running low
    active_map = {
        row["product__sku"]: {
            "product__name": row["product__name"],
            "product_type": row["product__polymorphic_ctype__model"].title(),
            "active_count": row["active_count"],
            "in_use_count": row["in_use_count"],
        }
        for row in InventoryItem.objects.exclude(
            status__in=[InventoryItem.Status.DEPLETED, InventoryItem.Status.SOLD]
        )
        .values("product__sku", "product__name", "product__polymorphic_ctype__model")
        .annotate(
            active_count=Count("id"),
            in_use_count=Count("id", filter=Q(status=InventoryItem.Status.IN_USE)),
        )
        .filter(active_count__lt=low_qty)
    }

    # Products depleted in the last 30 days (captures active consumption)
    depleted_map = {
        row["product__sku"]: row
        for row in InventoryItem.objects.filter(
            status=InventoryItem.Status.DEPLETED,
            date_depleted__gte=thirty_days_ago,
        )
        .values("product__sku", "product__name", "product__polymorphic_ctype__model")
        .annotate(recently_depleted=Count("id"))
    }

    # Alert candidates: low active stock + products that ran out recently
    out_of_stock_skus = set(depleted_map) - set(active_map)
    alert_skus = set(active_map) | out_of_stock_skus

    urgency_rank = {"danger": 0, "warning": 1, "secondary": 2}
    alerts = []
    for sku in alert_skus:
        if sku in active_map:
            row = {"product__sku": sku, **active_map[sku]}
        else:
            d = depleted_map[sku]
            row = {
                "product__sku": sku,
                "product__name": d["product__name"],
                "product_type": d["product__polymorphic_ctype__model"].title(),
                "active_count": 0,
                "in_use_count": 0,
            }
        row["recently_depleted"] = depleted_map.get(sku, {}).get("recently_depleted", 0)

        if row["active_count"] == 0 and row["recently_depleted"] > 0:
            row["urgency"] = "danger"
            row["urgency_label"] = "Out of Stock"
        elif row["recently_depleted"] > 0:
            row["urgency"] = "warning"
            row["urgency_label"] = "Running Low"
        else:
            row["urgency"] = "secondary"
            row["urgency_label"] = "Low Stock"

        alerts.append(row)

    alerts.sort(key=lambda r: (urgency_rank[r["urgency"]], r["active_count"], r["product__name"]))
    return alerts


class FilamentColorGuideView(LoginRequiredMixin, TemplateView):
    template_name = "inventory/filament_color_guide.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        filaments = list(
            Filament.objects.annotate(
                active_count=Count(
                    "inventory_items",
                    filter=Q(inventory_items__status__in=_ACTIVE_STATUSES),
                )
            )
            .filter(active_count__gt=0)
            .select_related("material")
            .order_by("color_family", "color")
        )

        grouped = {}
        for f in filaments:
            grouped.setdefault(f.color_family or "OTHER", []).append(f)

        # Preserve defined family order; append any unlisted families at the end
        ordered = {k: grouped[k] for k in FAMILY_ORDER if k in grouped}
        for k, v in grouped.items():
            if k not in ordered:
                ordered[k] = v

        context["grouped_filaments"] = ordered
        context["total_filaments"] = len(filaments)
        return context


class Dashboard(LoginRequiredMixin, View):
    def get(self, request):
        item_counts_by_type = [
            {
                "class_name": row["product__polymorphic_ctype__model"].title(),
                "count": row["count"],
            }
            for row in InventoryItem.objects.values("product__polymorphic_ctype__model")
            .annotate(count=Count("id"))
            .order_by("-count")
        ]

        total_value = (
            InventoryItem.objects.aggregate(total=Sum("product__price"))["total"]
            or Decimal("0.00")
        )

        materials = (
            Filament.objects.values("material__name")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        filament_chart_data = {
            "labels": [row["material__name"] for row in materials],
            "data": [row["count"] for row in materials],
        }

        colors = list(
            Filament.objects.values("color_family")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        color_chart_data = {
            "labels": [row["color_family"] or "Unknown" for row in colors],
            "data": [row["count"] for row in colors],
            "colors": [COLOR_FAMILY_HEX.get(row["color_family"] or "", "#cccccc") for row in colors],
        }

        inventory_by_sku = [
            {
                "product__name": row["product__name"],
                "product__sku": row["product__sku"],
                "product__class_name": row["product__polymorphic_ctype__model"].title(),
                "total_quantity": row["total_quantity"],
            }
            for row in InventoryItem.objects.values(
                "product__sku",
                "product__name",
                "product__polymorphic_ctype__model",
            )
            .annotate(total_quantity=Count("id"))
            .order_by("-total_quantity")
        ]

        low_stock_alerts = _build_low_stock_alerts()

        grand_total = InventoryItem.objects.count()
        distinct_products = InventoryItem.objects.values("product").distinct().count()
        latest_item = InventoryItem.objects.order_by("-last_modified").first()
        latest_timestamp = latest_item.last_modified if latest_item else None

        return render(
            request,
            "inventory/dashboard.html",
            {
                "distinct_products": distinct_products,
                "latest_timestamp": latest_timestamp,
                "item_counts_by_type": item_counts_by_type,
                "locations": Location.objects.all(),
                "grand_total": grand_total,
                "value": total_value,
                "filament_chart_data": filament_chart_data,
                "color_chart_data": color_chart_data,
                "inventory_by_sku": inventory_by_sku,
                "low_stock_alerts": low_stock_alerts,
                "low_qty_threshold": getattr(settings, "LOW_QUANTITY", 3),
            },
        )


class BaseAddProductView(LoginRequiredMixin, CreateView):
    template_name = "inventory/add_product.html"
    success_url = reverse_lazy("add_inventory")
    form_title = ""
    submit_label = "Save"

    def get_initial(self):
        initial = super().get_initial()
        pending = self.request.session.get("pending_inventory")
        if pending:
            initial["upc"] = pending.get("upc")
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form_title"] = self.form_title
        context["submit_label"] = self.submit_label
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.request.GET.get("from_inventory"):
            pending = self.request.session.pop("pending_inventory", None)
            if pending:
                InventoryItem.objects.create(
                    product=self.object,
                    shipment=pending.get("shipment"),
                    location_id=pending.get("location_id"),
                )
                messages.success(
                    self.request, f"{self.object.name} and inventory item created."
                )
                return redirect("add_inventory")
        return response


class AddFilamentView(BaseAddProductView):
    model = Filament
    form_class = FilamentForm
    form_title = "Add New Filament"
    submit_label = "Save Filament"


class AddPrinterView(BaseAddProductView):
    model = Printer
    form_class = PrinterForm
    form_title = "Add New Printer"
    submit_label = "Save Printer"


class AddDryerView(BaseAddProductView):
    model = Dryer
    form_class = DryerForm
    form_title = "Add New Dryer"
    submit_label = "Save Dryer"


class AddHardwareView(BaseAddProductView):
    model = Hardware
    form_class = HardwareForm
    form_title = "Add New Hardware"
    submit_label = "Save Hardware"


class AddAMSView(BaseAddProductView):
    model = AMS
    form_class = AMSForm
    form_title = "Add New AMS"
    submit_label = "Save AMS"


class InventoryExportView(LoginRequiredMixin, View):
    def get(self, request):
        # Get filters from query parameters
        sku = request.GET.get("sku", "")
        upc = request.GET.get("upc", "")
        name = request.GET.get("name", "")
        location = request.GET.get("location", "")

        # Rebuild the filtered queryset
        items = InventoryItem.objects.exclude(status=5).select_related(
            "product", "location"
        )
        if sku:
            items = items.filter(product__sku=sku)
        if upc:
            items = items.filter(product__upc=upc)
        if name:
            items = items.filter(product__name__icontains=name)
        if location:
            items = items.filter(location__name__icontains=location)

        # Create Excel workbook
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Inventory Export"

        # Write headers
        headers = ["Product", "SKU", "UPC", "Date Added", "Location"]
        ws.append(headers)

        # Write data rows
        for item in items:
            ws.append(
                [
                    item.product.name,
                    item.product.sku,
                    item.product.upc,
                    localtime(item.date_added).strftime("%Y-%m-%d %H:%M:%S"),
                    item.location.name if item.location else "",
                ]
            )

        # Return as downloadable file
        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        filename = "inventory_export.xlsx"
        response["Content-Disposition"] = f"attachment; filename={filename}"
        wb.save(response)
        return response


class InUseOverviewView(LoginRequiredMixin, TemplateView):
    template_name = "inventory/in_use_overview.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        in_use_items = InventoryItem.objects.filter(
            status=InventoryItem.Status.IN_USE
        ).select_related("location", "product")
        drying_items = InventoryItem.objects.filter(
            status=InventoryItem.Status.DRYING
        ).select_related("location", "product")
        stored_items = InventoryItem.objects.filter(
            status=InventoryItem.Status.STORED
        ).select_related("location", "product")

        grouped_by_location = {}
        for item in in_use_items:
            # TODO Add in additional views for | drying_items | stored_items
            loc = item.location.name if item.location else "Unassigned"
            item.product_type = str(
                item.product.polymorphic_ctype.model
            )  # Add model type

            tooltip_lines = []
            if item.serial_number:
                tooltip_lines.append(f"<strong>Serial:</strong> {escape(item.serial_number)}")

            if (
                item.product_type == "filament"
                and hasattr(item.product.filament, "color")
                and item.product.filament.color
            ):
                tooltip_lines.append(
                    f"<strong>Color:</strong> {escape(item.product.filament.color)}"
                )
            item.tooltip_html = "'{}'".format(
                "<br>".join(tooltip_lines).replace('"', "&quot;")
            )

            grouped_by_location.setdefault(loc, []).append(item)

        context["grouped_items"] = grouped_by_location
        return context


class DryStorageOverviewView(LoginRequiredMixin, TemplateView):
    template_name = "inventory/dry_storage_overview.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        stored_items = InventoryItem.objects.filter(
            status=InventoryItem.Status.STORED
        ).select_related("location", "product")

        grouped_by_location = {}
        for item in stored_items:
            loc = item.location.name if item.location else "Unassigned"
            item.product_type = str(
                item.product.polymorphic_ctype.model
            )  # Add model type

            tooltip_lines = []
            if item.serial_number:
                tooltip_lines.append(f"<strong>Serial:</strong> {escape(item.serial_number)}")

            if (
                item.product_type == "filament"
                and hasattr(item.product.filament, "color")
                and item.product.filament.color
            ):
                tooltip_lines.append(
                    f"<strong>Color:</strong> {escape(item.product.filament.color)}"
                )
            item.tooltip_html = "'{}'".format(
                "<br>".join(tooltip_lines).replace('"', "&quot;")
            )

            grouped_by_location.setdefault(loc, []).append(item)

        context["grouped_items"] = grouped_by_location
        return context
