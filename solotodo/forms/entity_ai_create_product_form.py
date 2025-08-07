from django import forms
from .llm_model_form import get_choices


class EntityAiCreateProductForm(forms.Form):
    ignore_errors = forms.BooleanField(required=False)
    llm_model = forms.ChoiceField(choices=get_choices, required=False)
