from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from .models import InventoryItem, Location

class UserRegisterForm(UserCreationForm):
	email = forms.EmailField()

	class Meta:
		model = User
		fields = ['username', 'email', 'password1', 'password2']

class InventoryItemForm(forms.ModelForm):
	location = forms.ModelChoiceField(queryset=Location.objects.all())

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

class MoveItemForm(forms.ModelForm):
	class Meta:
		model = InventoryItem
		fields = ['upc', 'location', 'status']