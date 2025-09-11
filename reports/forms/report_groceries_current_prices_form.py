import io

import xlsxwriter
from django import forms
from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone
from guardian.shortcuts import get_objects_for_user

from category_columns.models import CategoryColumn
from solotodo.models import (
    Category,
    Store,
    Entity,
    EsProduct,
)
from solotodo.utils import get_dotted_dict_value
from solotodo_core.s3utils import PrivateS3Boto3Storage


class ReportGroceriesCurrentPricesForm(forms.Form):
    stores = forms.ModelMultipleChoiceField(
        queryset=Store.objects.all(), required=False
    )

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        valid_stores = get_objects_for_user(user, "view_store_reports", Store)
        self.fields["stores"].queryset = valid_stores
        self.user = user

    def clean_stores(self):
        selected_stores = self.cleaned_data["stores"]

        if selected_stores:
            return selected_stores
        else:
            return self.fields["stores"].queryset

    def generate_report(self):
        stores = self.cleaned_data["stores"]
        category = Category.objects.get(pk=settings.GROCERIES_CATEGORY_ID)
        entities = (
            Entity.objects.filter(
                product__isnull=False, store__in=stores, category=category
            )
            .get_available()
            .select_related(
                "product__instance_model",
                "active_registry",
                "currency",
                "store",
            )
            .order_by("product")
        )

        product_ids = [x["product"] for x in entities.values("product")]
        es_search = EsProduct.search().filter("terms", product_id=product_ids)
        es_dict = {e.product_id: e.to_dict() for e in es_search.scan()}
        output = io.BytesIO()

        # Create a workbook and add a worksheet.
        workbook = xlsxwriter.Workbook(output)
        workbook.formats[0].set_font_size(10)
        self.generate_worksheet(workbook, entities, es_dict)
        workbook.close()
        output.seek(0)
        file_value = output.getvalue()
        file_for_upload = ContentFile(file_value)
        storage = PrivateS3Boto3Storage()
        filename_template = "groceries_current_prices_%Y-%m-%d_%H:%M:%S"
        filename = timezone.now().strftime(filename_template)
        path = storage.save("reports/{}.xlsx".format(filename), file_for_upload)
        print(storage.url(path))

        return {"file": file_value, "filename": filename, "path": path}

    @staticmethod
    def generate_worksheet(workbook, es, es_dict):
        worksheet = workbook.add_worksheet()
        date_format = workbook.add_format({"num_format": "yyyy-mm-dd"})
        header_format = workbook.add_format({"bold": True, "font_size": 10})
        category = Category.objects.get(pk=settings.GROCERIES_CATEGORY_ID)
        specs_columns = CategoryColumn.objects.filter(
            field__category=category.pk, purpose=settings.REPORTS_PURPOSE_ID
        )

        headers = [
            "Producto",
            "Tienda",
            "SKU",
            "URL",
            "Fecha muestra",
            "Precio normal",
            "Precio oferta",
            "Nombre en tienda",
        ]

        headers.extend([column.field.label for column in specs_columns])

        for idx, header in enumerate(headers):
            worksheet.write(0, idx, header, header_format)

        row = 1

        for e in es:
            col = 0
            es_entry = es_dict[e.product_id]

            # Product
            worksheet.write(row, col, str(e.product))
            col += 1

            # Store
            worksheet.write(row, col, str(e.store))
            col += 1

            # SKU
            if e.sku:
                sku_text = str(e.sku)
            else:
                sku_text = "N/A"

            worksheet.write(row, col, sku_text)
            col += 1

            # URL
            worksheet.write(row, col, e.url)
            col += 1

            # Date
            worksheet.write(row, col, e.active_registry.timestamp.date(), date_format)
            col += 1

            # Normal price
            worksheet.write(row, col, e.active_registry.normal_price)
            col += 1

            # Offer price
            worksheet.write(row, col, e.active_registry.offer_price)
            col += 1

            # Store name
            worksheet.write(row, col, e.name)
            col += 1

            for column in specs_columns:
                worksheet.write(
                    row,
                    col,
                    get_dotted_dict_value(es_entry["specs"], column.field.es_field)
                    or "N/A",
                )
                col += 1

            row += 1

        worksheet.autofilter(0, 0, row - 1, len(headers) - 1)
