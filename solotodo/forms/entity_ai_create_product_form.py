from django import forms


class EntityAiCreateProductForm(forms.Form):
    ignore_errors = forms.BooleanField(required=False)
