from django import forms
from django.core.files.storage import default_storage
from sorl.thumbnail import get_thumbnail


class ProductPictureForm(forms.Form):
    width = forms.IntegerField(min_value=1)
    height = forms.IntegerField(min_value=1)
    image_format = forms.ChoiceField(
        choices=[("JPEG", "JPEG image"), ("PNG", "PNG image")], required=False
    )
    quality = forms.IntegerField(min_value=1, max_value=100, required=False)

    def thumbnail_kwargs(self):
        data = self.cleaned_data

        result = {"geometry_string": "{}x{}".format(data["width"], data["height"])}

        if data["image_format"]:
            result["format"] = data["image_format"]

        if data["quality"]:
            result["quality"] = data["quality"]

        return result

    def product_thumbnail_url(self, product):
        specs = product.specs

        if "picture" not in specs:
            return default_storage.url("products/not_found.png")

        picture = specs["picture"]
        thumbnail_kwargs = self.thumbnail_kwargs()

        try:
            resized_picture = get_thumbnail(picture, **thumbnail_kwargs)
        except OSError:
            # Probably trying to show an RGBA image in JPEG
            del thumbnail_kwargs["format"]
            resized_picture = get_thumbnail(picture, **thumbnail_kwargs)

        return resized_picture
