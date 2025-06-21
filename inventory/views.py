import logging
import re
from decimal import Decimal

import django_filters
import openpyxl
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.utils.timezone import localtime
from django.views.generic import CreateView, TemplateView, UpdateView, View

from .barcode_utils import generate_and_print_barcode
from .forms import *
from .models import *
from .tables import *

logger = logging.getLogger("inventory")

# ---- Barcode Writer Helpers --------


class PrintBarcodeView(View):

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

        return redirect("inventory_edit", pk=item_id)


class BarcodeRedirectView(View):
    def get(self, request, value):
        if value.startswith("INV-"):
            item_id = value.replace("INV-", "")
            return redirect("inventory_edit", pk=item_id)
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
        if name and not any([sku, upc, location, serial_number]):
            items = items.filter(
                Q(product__name__icontains=name)
                | Q(product__sku__icontains=name)
                | Q(product__upc__icontains=name)
                | Q(location__name__icontains=name)
                | Q(serial_number__icontains=name)
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

        # Pass filtered items to the template
        context = {
            "items": items or InventoryItem.objects.none(),
            "search_values": {
                "sku": sku,
                "upc": upc,
                "name": name,
                "location": location,
                "serial_number": serial_number,
            },
        }

        return render(request, "inventory/inventory_search.html", context)


class inventoryEditView(LoginRequiredMixin, UpdateView):
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
        form = InventoryEditForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            return redirect("inventory_search")
        else:
            form = InventoryEditForm(instance=item)

        return render(
            request,
            "inventory/inventory_edit.html",
            {"form": form, "item": item, "product": item.product},
        )


class addInventoryView(LoginRequiredMixin, CreateView):
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

        # Try to find product by UPC
        if upc:
            for model in [Filament, Printer, Hardware, AMS, Dryer]:
                try:
                    product = model.objects.get(upc=upc)
                    break
                except model.DoesNotExist:
                    continue

        # Try to find product by SKU
        if product is None and sku:
            for model in [Filament, Printer, Hardware, AMS, Dryer]:
                try:
                    product = model.objects.filter(sku=sku).first()
                    break
                except model.DoesNotExist:
                    continue

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
            generate_and_print_barcode(new_item, mode="upc")
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


class Dashboard(LoginRequiredMixin, View):
    def get(self, request):

        # This will list how many of each subclass, i.e. AMS, Hardware, Filament, etc.
        item_counts_by_type = []

        # This ensures we get the actual subclass instance of the product
        for item in InventoryItem.objects.select_related("product").all():
            real_product = item.product
            if isinstance(real_product, PolymorphicModel):
                real_product = real_product.get_real_instance_class()
                class_name = real_product.__name__
            else:
                class_name = real_product.__class__.__name__

            match = next(
                (
                    entry
                    for entry in item_counts_by_type
                    if entry["class_name"] == class_name
                ),
                None,
            )
            if match:
                match["count"] += 1
            else:
                item_counts_by_type.append({"class_name": class_name, "count": 1})

        item_counts = InventoryItem.objects.values("product", "product__sku").annotate(
            count=Count("id")
        )

        # Get actual product instances
        items = []
        for entry in item_counts:
            inv = InventoryItem.objects.filter(product_id=entry["product"]).first()
            if inv:
                inv.product.inventory_count = entry["count"]  # inject count
                inv.product.class_name = inv.product.get_real_instance_class().__name__
                items.append(inv)

        total_value = Decimal("0.00")
        # Calculate total value
        for item in items:
            if item.product.price:
                total_value += item.product.price * Decimal(
                    str(item.product.inventory_count)
                )

        # Aggregate Filament items by material
        materials = (
            Filament.objects.values("material")
            .annotate(count=Count("id"))
            .order_by("-count")  # <-- This sorts it
        )

        # Prepare data for the pie chart
        filament_chart_data = {
            "labels": [item["material"] for item in materials],
            "data": [item["count"] for item in materials],
        }

        # Aggregate Filament items by color
        colors = (
            Filament.objects.values("color")
            .annotate(count=Count("id"))
            .order_by("-count")  # <-- this sorts it
        )

        # Prepare data for the pie chart
        color_chart_data = {
            "labels": [item["color"] for item in colors],
            "data": [item["count"] for item in colors],
        }

        raw_inventory_by_sku = (
            InventoryItem.objects.select_related("product")
            .values("product__sku", "product__name")
            .annotate(total_quantity=Count("id"))
            .order_by("-total_quantity")
        )

        # Inject class name via a mapping step
        sku_class_lookup = {}
        for item in InventoryItem.objects.select_related("product"):
            sku = item.product.sku
            if sku not in sku_class_lookup:
                sku_class_lookup[sku] = item.product.get_real_instance_class().__name__

        inventory_by_sku = []
        for row in raw_inventory_by_sku:
            row["product__class_name"] = sku_class_lookup.get(
                row["product__sku"], "Unknown"
            )
            inventory_by_sku.append(row)

        # Get latest timestamp for summary
        latest_item = InventoryItem.objects.order_by("-timestamp").first()
        latest_timestamp = latest_item.timestamp if latest_item else None

        grand_total = sum(item.product.inventory_count for item in items)

        # print(json.dumps(color_chart_data))

        return render(
            request,
            "inventory/dashboard.html",
            {
                "items": items,
                "latest_timestamp": latest_timestamp,
                "item_counts": item_counts,
                "item_counts_by_type": item_counts_by_type,
                "locations": Location.objects.all(),
                "grand_total": grand_total,
                "value": total_value,
                "filament_chart_data": filament_chart_data,
                "color_chart_data": color_chart_data,
                "inventory_by_sku": inventory_by_sku,
            },
        )


class AddFilamentView(LoginRequiredMixin, CreateView):
    model = Filament
    form_class = FilamentForm
    template_name = "inventory/add_filament.html"
    success_url = reverse_lazy("add_inventory")

    def get_initial(self):
        initial = super().get_initial()
        pending = self.request.session.get("pending_inventory")
        if pending:
            initial["upc"] = pending.get("upc")
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.request.GET.get("from_inventory"):
            # Use pending inventory data to create InventoryItem
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


class AddPrinterView(LoginRequiredMixin, CreateView):
    model = Printer
    form_class = PrinterForm
    template_name = "inventory/add_printer.html"
    success_url = reverse_lazy("add_inventory")

    def get_initial(self):
        initial = super().get_initial()
        pending = self.request.session.get("pending_inventory")
        if pending:
            initial["upc"] = pending.get("upc")
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.request.GET.get("from_inventory"):
            # Use pending inventory data to create InventoryItem
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


class AddDryerView(LoginRequiredMixin, CreateView):
    model = Dryer
    form_class = DryerForm
    template_name = "inventory/add_dryer.html"
    success_url = reverse_lazy("add_inventory")

    def get_initial(self):
        initial = super().get_initial()
        pending = self.request.session.get("pending_inventory")
        if pending:
            initial["upc"] = pending.get("upc")
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.request.GET.get("from_inventory"):
            # Use pending inventory data to create InventoryItem
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


class AddHardwareView(LoginRequiredMixin, CreateView):
    model = Hardware
    form_class = HardwareForm
    template_name = "inventory/add_hardware.html"
    success_url = reverse_lazy("add_inventory")

    def get_initial(self):
        initial = super().get_initial()
        pending = self.request.session.get("pending_inventory")
        if pending:
            initial["upc"] = pending.get("upc")
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.request.GET.get("from_inventory"):
            # Use pending inventory data to create InventoryItem
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


class AddAMSView(LoginRequiredMixin, CreateView):
    model = AMS
    form_class = AMSForm
    template_name = "inventory/add_ams.html"
    success_url = reverse_lazy("add_inventory")

    def get_initial(self):
        initial = super().get_initial()
        pending = self.request.session.get("pending_inventory")
        if pending:
            initial["upc"] = pending.get("upc")
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.request.GET.get("from_inventory"):
            # Use pending inventory data to create InventoryItem
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


class FilamentView(LoginRequiredMixin, View):
    def get(self, request):

        item_counts = Filament.objects.values("product", "product__name").annotate(
            count=Count("id")
        )

        # Get actual product instances
        items = []
        for entry in item_counts:
            inv = InventoryItem.objects.filter(product_id=entry["filament"]).first()
            if inv:
                inv.product.inventory_count = entry["count"]  # inject count
                inv.product.class_name = inv.product.get_real_instance_class().__name__
                items.append(inv)

        total_value = Decimal("0.00")

        # Calculate total value
        for item in items:
            if item.product.price:
                total_value += item.product.price * Decimal(
                    str(item.product.inventory_count)
                )

        # Aggregate Filament items by material
        materials = (
            Filament.objects.values("material")
            .annotate(count=Count("id"))
            .order_by("-count")  # <-- This sorts it
        )

        # Prepare data for the pie chart
        filament_chart_data = {
            "labels": [item["material"] for item in materials],
            "data": [item["count"] for item in materials],
        }

        # Aggregate Filament items by color
        colors = (
            Filament.objects.values("color")
            .annotate(count=Count("id"))
            .order_by("-count")  # <-- this sorts it
        )

        # Prepare data for the pie chart
        color_chart_data = {
            "labels": [item["color"] for item in colors],
            "data": [item["count"] for item in colors],
        }

        num_filament_rolls = sum(item.product.inventory_count for item in items)

        return render(
            request,
            "inventory/dashboard.html",
            {
                "item_counts": item_counts,
                "items": items,
                "locations": Location.objects.all(),
                "filament_chart_data": filament_chart_data,
                "color_chart_data": color_chart_data,
            },
        )


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
                    item.location.name,
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


class InUseOverviewView(TemplateView):
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
                tooltip_lines.append(f"<strong>Serial:</strong> {item.serial_number}")

            if (
                item.product_type == "filament"
                and hasattr(item.product.filament, "color")
                and item.product.filament.color
            ):
                tooltip_lines.append(
                    f"<strong>Color:</strong> {item.product.filament.color}"
                )
            item.tooltip_html = "'{}'".format(
                "<br>".join(tooltip_lines).replace('"', "&quot;")
            )

            grouped_by_location.setdefault(loc, []).append(item)

        context["grouped_items"] = grouped_by_location
        return context


class DryStorageOverviewView(TemplateView):
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
                tooltip_lines.append(f"<strong>Serial:</strong> {item.serial_number}")

            if (
                item.product_type == "filament"
                and hasattr(item.product.filament, "color")
                and item.product.filament.color
            ):
                tooltip_lines.append(
                    f"<strong>Color:</strong> {item.product.filament.color}"
                )
            item.tooltip_html = "'{}'".format(
                "<br>".join(tooltip_lines).replace('"', "&quot;")
            )

            grouped_by_location.setdefault(loc, []).append(item)

        context["grouped_items"] = grouped_by_location
        return context
