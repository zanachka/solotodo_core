import csv
import io

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.files.base import ContentFile
from django.db import models, connections
from django.db.models import Max, Min
from django.db.models.functions import TruncDate
from django_redshift_backend.distkey import DistKey
from guardian.shortcuts import get_objects_for_group

from solotodo_core.s3utils import PrivateSaS3Boto3Storage


class LgRsEntitySectionPosition(models.Model):
    average_value = models.FloatField()
    latest_value = models.IntegerField()
    section_id = models.IntegerField()
    section_name = models.CharField(max_length=256)
    store_id = models.IntegerField()
    store_name = models.CharField(max_length=256)
    date = models.DateField()
    entity_id = models.IntegerField()
    entity_name = models.CharField(max_length=256)
    category_id = models.IntegerField()
    category_name = models.CharField(max_length=256)
    product_id = models.IntegerField()
    product_name = models.CharField(max_length=256)
    brand_id = models.IntegerField()
    brand_name = models.CharField(max_length=256)
    sku = models.CharField(max_length=256, blank=True, null=True)
    url = models.URLField(max_length=512)
    is_sponsored = models.BooleanField(default=False)

    def str(self):
        return self.id

    @classmethod
    def synchronize_with_db_positions(cls):
        from solotodo.models import Store, Category, EntitySectionPosition

        lg_group = Group.objects.get(pk=settings.LG_CHILE_GROUP_ID)

        stores = get_objects_for_group(lg_group, "view_store", Store)
        categories = get_objects_for_group(lg_group, "view_category", Category)

        positions_to_synchronize = (
            EntitySectionPosition.objects.filter(
                entity_history__entity__store__in=stores,
                entity_history__entity__category__in=categories,
                entity_history__entity__product__isnull=False,
            )
            .select_related(
                "entity_history__entity__store",
                "entity_history__entity__category",
                "entity_history__entity__product__instance_model",
                "entity_history__entity__product__brand",
                "section",
            )
            .annotate(date=TruncDate("entity_history__timestamp"))
        )

        last_synchronization = cls.objects.aggregate(Max("date"))["date__max"]

        if last_synchronization:
            print("Synchronizing since {}".format(last_synchronization))
            positions_to_synchronize = positions_to_synchronize.filter(
                entity_history__timestamp__gte=last_synchronization
            )
        else:
            print("Synchronizing from scratch")

        print("Creating in memory CSV File")
        output = io.StringIO()
        writer = csv.writer(output)
        data_count = len(positions_to_synchronize)

        for idx, entity_section_position in enumerate(positions_to_synchronize):
            print("Processing: {} / {}".format(idx + 1, data_count))
            entity = entity_section_position.entity_history.entity
            section = entity_section_position.section

            writer.writerow(
                [
                    entity_section_position.value,
                    section.id,
                    str(section),
                    entity.store.id,
                    str(entity.store),
                    entity_section_position.date,
                    entity.id,
                    entity.name,
                    entity.category.id,
                    str(entity.category),
                    entity.product.id,
                    str(entity.product),
                    entity.product.brand.id,
                    str(entity.product.brand),
                    entity.sku,
                    entity.url,
                    entity_section_position.value,
                    entity_section_position.is_sponsored,
                ]
            )

        output.seek(0)
        file_for_upload = ContentFile(output.getvalue().encode("utf-8"))

        print("Uploading CSV file")

        storage = PrivateSaS3Boto3Storage()
        storage.file_overwrite = True
        path = "lg_pricing/entity_positions.csv"
        storage.save(path, file_for_upload)

        if last_synchronization:
            print("Deleting existing entity positions in Redshift")
            cls.objects.filter(date__gte=last_synchronization).delete()

        print("Loading new data into Redshift")

        cursor = connections["lg_pricing"].cursor()
        command = """
                    copy {} from 's3://{}/{}'
                    credentials 'aws_access_key_id={};aws_secret_access_key={}'
                    csv;
                    """.format(
            cls._meta.db_table,
            settings.AWS_SA_STORAGE_BUCKET_NAME,
            path,
            settings.AWS_ACCESS_KEY_ID,
            settings.AWS_SECRET_ACCESS_KEY,
        )

        cursor.execute(command)
        cursor.close()

    class Meta:
        app_label = "lg_pricing"
        indexes = [DistKey(fields=["brand_id"])]
        ordering = ["date"]
