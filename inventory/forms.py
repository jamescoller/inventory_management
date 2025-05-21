from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from .models import *

class UserRegisterForm(UserCreationForm):
	email = forms.EmailField()

	class Meta:
		model = User
		fields = ['username', 'email', 'password1', 'password2']

class InventoryItemForm(forms.ModelForm):

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

		has_inventory = InventoryItem.objects.exists()

		if has_inventory:

			# Get the most recent object
			most_recent_shipment = InventoryItem.objects.order_by('-id').first().shipment
			most_recent_location = InventoryItem.objects.order_by('-id').first().location
			# Set it as the initial value
			self.fields['location'].initial = most_recent_location
			self.fields['shipment'].initial = most_recent_shipment

		# if not has_inventory:
		# 	self.fields['location'].initial = 'NULL'
		# 	self.fields['shipment'].initial = 'NULL'

	class Meta:
		model = InventoryItem
		fields = ['shipment', 'upc', 'location']

	# TODO: Allow for items to be added by SKU, not just by UPC

class MoveItemForm(forms.ModelForm):
	class Meta:
		model = InventoryItem
		fields = ['upc', 'location', 'status']

class FilamentForm(forms.ModelForm):
	class Meta:
		model = Filament
		fields = ['name', 'upc', 'sku', 'price', 'notes', 'category',
				  'material','material_type','color','hex_code']

class AMSForm(forms.ModelForm):
	class Meta:
		model = AMS
		fields = ['name', 'upc', 'sku', 'price', 'notes', 'category',
				  'mfr','model','num_slots']

class DryerForm(forms.ModelForm):
	class Meta:
		model = Dryer
		fields = ['name', 'upc', 'sku', 'price', 'notes', 'category',
				  'mfr','model','num_slots','max_temp_degC']

class PrinterForm(forms.ModelForm):
	class Meta:
		model = Printer
		fields = ['name', 'upc', 'sku', 'price', 'notes', 'category',
				  'mfr','model','num_extruders']

class HardwareForm(forms.ModelForm):
	class Meta:
		model = Hardware
		fields = ['name', 'upc', 'sku', 'price', 'notes', 'category',
				  'usage']

class InventoryEditForm(forms.ModelForm):
	class Meta:
		model = InventoryItem
		fields = ['location', 'status', 'date_depleted']