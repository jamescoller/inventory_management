from django.shortcuts import render, redirect
from django.urls import reverse_lazy
from django.views.generic import TemplateView, View, CreateView, UpdateView, DeleteView, ListView
from django.contrib.auth import authenticate, login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.db.models import Count
from django.db.models import Sum
from django.contrib.contenttypes.models import ContentType
from .forms import *
from .models import *
from django.shortcuts import render, get_object_or_404
from decimal import Decimal
import json

class AboutView(TemplateView):
    template_name = 'inventory/about.html'

class AddProductChoiceView(LoginRequiredMixin, CreateView):
    def get(self, request):
        upc = request.session.get('pending_inventory', {}).get('upc', '')
        return render(request, 'inventory/add_product_choice.html', {'upc': upc})


class addInventoryView(LoginRequiredMixin, CreateView):
    model = InventoryItem
    form_class = InventoryItemForm
    template_name = 'inventory/item_form.html'
    success_url = reverse_lazy('add_inventory')

    def post(self, request, **kwargs):


        upc = request.POST.get('upc')
        shipment = request.POST.get('shipment')
        location_id = request.POST.get('location')
        location = get_object_or_404(Location, id=location_id)

        product = None

        # Loop through models and get the correct one
        for model in [Filament, Printer, Hardware, AMS, Dryer]:
            try:
                product = model.objects.get(upc=upc)
                break
            except model.DoesNotExist:
                continue

        if product is None:
            # Store scanned data temporarily in session
            request.session['pending_inventory'] = {
                'upc': upc,
                'shipment': shipment,
                'location_id': location_id,
            }
            messages.warning(
                request,
                f"No product found with UPC: {upc}. Please add the product before continuing."
            )
            return redirect('add_product_choice')  # This is a new view we’ll create
            # messages.error(request, f"No product found with UPC: {upc}")
            # return redirect('add_inventory')

        # Create InventoryItem only if a product was found
        InventoryItem.objects.create(
            product=product,
            shipment=shipment,
            location=location,
            upc=upc,
        )

        messages.success(request, f"Added {product.name} to inventory.")
        return redirect('add_inventory')

    def form_valid(self, form):
        form.instance.user = self.request.user
        return super().form_valid(form)

class Index(TemplateView):
    template_name = 'inventory/index.html'

class SignUpView(View):
    def get(self, request):
        form = UserRegisterForm()
        return render(request, 'inventory/signup.html', {'form': form})

    def post(self, request):
        form = UserRegisterForm(request.POST)

        if form.is_valid():
            form.save()
            user = authenticate(
                username=form.cleaned_data['username'],
                password=form.cleaned_data['password1']
            )

            login(request, user)
            return redirect('index')

        return render(request, 'inventory/signup.html', {'form': form})


class Dashboard(LoginRequiredMixin, View):
    def get(self, request):

        item_counts_by_type = []

        # This ensures we get the actual subclass instance of the product
        for item in InventoryItem.objects.select_related('product').all():
            real_product = item.product
            if isinstance(real_product, PolymorphicModel):
                real_product = real_product.get_real_instance_class()
                class_name = real_product.__name__
            else:
                class_name = real_product.__class__.__name__

            match = next((entry for entry in item_counts_by_type if entry['class_name'] == class_name), None)
            if match:
                match['count'] += 1
            else:
                item_counts_by_type.append({'class_name': class_name, 'count': 1})

        item_counts = (
            InventoryItem.objects
            .values('product', 'product__category')
            .annotate(count=Count('id'))
        )

        # Get actual product instances
        items = []
        for entry in item_counts:
            inv = InventoryItem.objects.filter(product_id=entry['product']).first()
            if inv:
                inv.product.inventory_count = entry['count']  # inject count
                inv.product.class_name = inv.product.get_real_instance_class().__name__
                items.append(inv)

        total_value = Decimal('0.00')
        # Calculate total value
        for item in items:
            if item.product.price:
                total_value += item.product.price * Decimal(str(item.product.inventory_count))

        # Aggregate Filament items by material
        materials = (
                Filament.objects.values('material')
                .annotate(count=Count('id'))
                .order_by('-count')  # <-- This sorts it
        )

        # Prepare data for the pie chart
        filament_chart_data = {
            'labels': [item['material'] for item in materials],
            'data': [item['count'] for item in materials],
        }

        # Aggregate Filament items by color
        colors = (
            Filament.objects.values('color')
            .annotate(count=Count('id'))
            .order_by('-count')  # <-- this sorts it
        )

        # Prepare data for the pie chart
        color_chart_data = {
            'labels': [item['color'] for item in colors],
            'data': [item['count'] for item in colors],
        }


        # Get latest timestamp for summary
        latest_item = InventoryItem.objects.order_by('-timestamp').first()
        latest_timestamp = latest_item.timestamp if latest_item else None

        grand_total = sum(item.product.inventory_count for item in items)

        # print(json.dumps(color_chart_data))


        return render(request, 'inventory/dashboard.html', {
            'items': items,
            'latest_timestamp': latest_timestamp,
            'item_counts': item_counts,
            'item_counts_by_type': item_counts_by_type,
            'locations': Location.objects.all(),
            'grand_total': grand_total,
            'value': total_value,
            'filament_chart_data': filament_chart_data,
            'color_chart_data': color_chart_data,
        })

class AddFilamentView(LoginRequiredMixin, CreateView):
    model = Filament
    form_class = FilamentForm
    template_name = 'inventory/add_filament.html'
    success_url = reverse_lazy('add_inventory')

    def get_initial(self):
        initial = super().get_initial()
        pending = self.request.session.get('pending_inventory')
        if pending:
            initial['upc'] = pending.get('upc')
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.request.GET.get('from_inventory'):
            # Use pending inventory data to create InventoryItem
            pending = self.request.session.pop('pending_inventory', None)
            if pending:
                InventoryItem.objects.create(
                    product=self.object,
                    shipment=pending.get('shipment'),
                    location_id=pending.get('location_id'),
                    upc=pending.get('upc'),
                    user=self.request.user
                )
                messages.success(self.request, f"{self.object.name} and inventory item created.")
                return redirect('add_inventory')
        return response

class AddPrinterView(LoginRequiredMixin, CreateView):
    model = Printer
    form_class = PrinterForm
    template_name = 'inventory/add_printer.html'
    success_url = reverse_lazy('add_inventory')

    def get_initial(self):
        initial = super().get_initial()
        pending = self.request.session.get('pending_inventory')
        if pending:
            initial['upc'] = pending.get('upc')
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.request.GET.get('from_inventory'):
            # Use pending inventory data to create InventoryItem
            pending = self.request.session.pop('pending_inventory', None)
            if pending:
                InventoryItem.objects.create(
                    product=self.object,
                    shipment=pending.get('shipment'),
                    location_id=pending.get('location_id'),
                    upc=pending.get('upc'),
                    user=self.request.user
                )
                messages.success(self.request, f"{self.object.name} and inventory item created.")
                return redirect('add_inventory')
        return response

class AddDryerView(LoginRequiredMixin, CreateView):
    model = Dryer
    form_class = DryerForm
    template_name = 'inventory/add_dryer.html'
    success_url = reverse_lazy('add_inventory')

    def get_initial(self):
        initial = super().get_initial()
        pending = self.request.session.get('pending_inventory')
        if pending:
            initial['upc'] = pending.get('upc')
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.request.GET.get('from_inventory'):
            # Use pending inventory data to create InventoryItem
            pending = self.request.session.pop('pending_inventory', None)
            if pending:
                InventoryItem.objects.create(
                    product=self.object,
                    shipment=pending.get('shipment'),
                    location_id=pending.get('location_id'),
                    upc=pending.get('upc'),
                    user=self.request.user
                )
                messages.success(self.request, f"{self.object.name} and inventory item created.")
                return redirect('add_inventory')
        return response

class AddHardwareView(LoginRequiredMixin, CreateView):
    model = Hardware
    form_class = HardwareForm
    template_name = 'inventory/add_hardware.html'
    success_url = reverse_lazy('add_inventory')

    def get_initial(self):
        initial = super().get_initial()
        pending = self.request.session.get('pending_inventory')
        if pending:
            initial['upc'] = pending.get('upc')
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.request.GET.get('from_inventory'):
            # Use pending inventory data to create InventoryItem
            pending = self.request.session.pop('pending_inventory', None)
            if pending:
                InventoryItem.objects.create(
                    product=self.object,
                    shipment=pending.get('shipment'),
                    location_id=pending.get('location_id'),
                    upc=pending.get('upc'),
                    user=self.request.user
                )
                messages.success(self.request, f"{self.object.name} and inventory item created.")
                return redirect('add_inventory')
        return response

class AddAMSView(LoginRequiredMixin, CreateView):
    model = AMS
    form_class = AMSForm
    template_name = 'inventory/add_ams.html'
    success_url = reverse_lazy('add_inventory')

    def get_initial(self):
        initial = super().get_initial()
        pending = self.request.session.get('pending_inventory')
        if pending:
            initial['upc'] = pending.get('upc')
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.request.GET.get('from_inventory'):
            # Use pending inventory data to create InventoryItem
            pending = self.request.session.pop('pending_inventory', None)
            if pending:
                InventoryItem.objects.create(
                    product=self.object,
                    shipment=pending.get('shipment'),
                    location_id=pending.get('location_id'),
                    upc=pending.get('upc'),
                    user=self.request.user
                )
                messages.success(self.request, f"{self.object.name} and inventory item created.")
                return redirect('add_inventory')
        return response

class FilamentView(LoginRequiredMixin, View):
    def get(self, request):

        item_counts = (
            Filament.objects
            .values('product', 'product__name')
            .annotate(count=Count('id'))
        )

        # Get actual product instances
        items = []
        for entry in item_counts:
            inv = InventoryItem.objects.filter(product_id=entry['filament']).first()
            if inv:
                inv.product.inventory_count = entry['count']  # inject count
                inv.product.class_name = inv.product.get_real_instance_class().__name__
                items.append(inv)

        total_value = Decimal('0.00')

        # Calculate total value
        for item in items:
            if item.product.price:
                total_value += item.product.price * Decimal(str(item.product.inventory_count))

        inventory_by_sku = (
            InventoryItem.objects
            .values('product__sku', 'product__name')
            .annotate(count=Count('id'))
            .order_by('-count')
        )

        # Aggregate Filament items by material
        materials = (
            Filament.objects.values('material')
            .annotate(count=Count('id'))
            .order_by('-count')  # <-- This sorts it
        )

        # Prepare data for the pie chart
        filament_chart_data = {
            'labels': [item['material'] for item in materials],
            'data': [item['count'] for item in materials],
        }

        # Aggregate Filament items by color
        colors = (
            Filament.objects.values('color')
            .annotate(count=Count('id'))
            .order_by('-count')  # <-- this sorts it
        )

        # Prepare data for the pie chart
        color_chart_data = {
            'labels': [item['color'] for item in colors],
            'data': [item['count'] for item in colors],
        }

        num_filament_rolls = sum(item.product.inventory_count for item in items)

        return render(request, 'inventory/dashboard.html', {
            'item_counts': item_counts,
            'item_counts_by_type': item_counts_by_type,
            'items': items,
            'locations': Location.objects.all(),
            'filament_chart_data': filament_chart_data,
            'color_chart_data': color_chart_data,
            'inventory_by_sku': inventory_by_sku,
        })