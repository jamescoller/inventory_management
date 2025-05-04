from django.shortcuts import render, redirect
from django.urls import reverse_lazy
from django.views.generic import TemplateView, View, CreateView, UpdateView, DeleteView, ListView
from django.contrib.auth import authenticate, login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.contenttypes.models import ContentType
from .forms import *
from .models import *
from django.shortcuts import render, get_object_or_404

class AboutView(TemplateView):
	template_name = 'inventory/about.html'

# class addInventoryView(View):
# 	def get(self, request):
# 		if request.method == 'POST':
# 			upc = request.POST.get('upc')
# 			tracking_number = request.POST.get('tracking_number')
# 			product = get_object_or_404(Product.objects.all(), upc=upc)
# 			InventoryItem.objects.create(product=product, shipment=tracking_number, upc=upc)
#
# 		return render(request, 'inventory/item_form.html', {'form': InventoryItemForm()})


class addInventoryView(LoginRequiredMixin, CreateView):
	model = InventoryItem
	form_class = InventoryItemForm
	template_name = 'inventory/item_form.html'
	success_url = reverse_lazy('add_inventory')

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context['location'] = Location.objects.all()
		return context

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
		items = InventoryItem.objects.all()
		return render(request, 'inventory/dashboard.html', {'items': items})