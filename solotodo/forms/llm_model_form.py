from django import forms


def get_choices():
    from django.conf import settings

    return [(llm_model_name, llm_model_name) for llm_model_name in settings.LLMS.keys()]


class LlmModelForm(forms.Form):
    llm_model = forms.ChoiceField(choices=get_choices, required=False)
