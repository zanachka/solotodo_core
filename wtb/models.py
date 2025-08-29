import json
import logging
import traceback

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import models, IntegrityError
from django.utils import timezone
from guardian.shortcuts import get_objects_for_user

from solotodo.models import Store, Product, Category, Website, Brand
from solotodo.utils import sha256
from solotodo_core.s3utils import PrivateS3Boto3Storage
from storescraper.utils import get_store_class_by_name


class WtbBrandQuerySet(models.QuerySet):
    def filter_by_user_perms(self, user, permission):
        return get_objects_for_user(user, permission, self)


class WtbBrand(models.Model):
    name = models.CharField(max_length=100)
    prefered_brand = models.CharField(max_length=100, blank=True, null=True)
    storescraper_class = models.CharField(max_length=100, blank=True, null=True)
    website = models.ForeignKey(Website, on_delete=models.CASCADE)
    stores = models.ManyToManyField(Store)
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT)

    objects = WtbBrandQuerySet.as_manager()

    scraper = property(lambda self: get_store_class_by_name(self.storescraper_class))

    def __str__(self):
        return self.name

    def update_entities(
        self,
        categories=None,
        discover_urls_concurrency=None,
        products_for_url_concurrency=None,
        use_async=None,
        update_log=None,
        extra_args=None,
    ):
        from wtb.tasks import wtb_brand_category_update_pricing

        assert self.storescraper_class

        if not discover_urls_concurrency:
            discover_urls_concurrency = self.scraper.preferred_discover_urls_concurrency

        if not products_for_url_concurrency:
            products_for_url_concurrency = (
                self.scraper.preferred_products_for_url_concurrency
            )

        if use_async is None:
            use_async = self.scraper.prefer_async

        if not update_log:
            update_log = WtbBrandUpdateLog.objects.create(
                brand=self, status=WtbBrandUpdateLog.IN_PROCESS
            )

        extra_args = self.scraper.extra_args_with_preflight(extra_args)

        logger = logging.getLogger("logstash")
        logging_payload = {
            "message": "Started WTB update",
            "wtb_update_log_id": update_log.id,
        }
        logger.info(json.dumps(logging_payload))

        if categories:
            categories = categories.filter(
                storescraper_name__in=self.scraper.categories()
            )
        else:
            categories = Category.objects.filter(
                storescraper_name__in=self.scraper.categories()
            )

        if use_async:
            cache.set(f"wtb_{self.id}_discover_entries", 0, 2 * 60 * 60)
            cache.set(f"wtb_{self.id}_products_for_url", 0, 2 * 60 * 60)

            update_log.initialize_task_counter(0)

            for category in categories:
                update_log.increment_task_counter()

                if use_async:
                    wtb_brand_category_update_pricing.delay(
                        self.id,
                        category.id,
                        discover_urls_concurrency,
                        products_for_url_concurrency,
                        use_async,
                        update_log.id,
                        extra_args,
                    )
        else:
            update_log.initialize_task_counter(1)
            for category in categories:
                update_log.increment_task_counter()
                self.update_entities_category(
                    category,
                    products_for_url_concurrency,
                    use_async,
                    update_log,
                    extra_args,
                )
            update_log.decrement_task_counter()
        return update_log

    def update_entities_category(
        self,
        category,
        products_for_url_concurrency,
        use_async,
        wtb_brand_update_log,
        extra_args,
    ):
        from wtb.tasks import wtb_brand_create_or_update_entity_from_discovery_url

        logger = logging.getLogger("logstash")
        logging_payload = {
            "message": "Started WTB category entities update: " + str(category),
            "wtb_update_log_id": wtb_brand_update_log.id,
        }
        logger.info(json.dumps(logging_payload))
        discovered_urls = []
        logger.info(
            json.dumps(
                {
                    "message": "Discovering URLs for category: " + str(category),
                    "wtb_update_log_id": wtb_brand_update_log.id,
                }
            )
        )
        for (
            discovery_url
        ) in self.scraper.discover_urls_for_category_with_custom_exception(
            category.storescraper_name, extra_args=extra_args
        ):
            cache_key = (
                f"WTB_SCRAPING_{wtb_brand_update_log.id}_{sha256(discovery_url)}"
            )
            already_scraped_product_keys = cache.get(cache_key)
            if already_scraped_product_keys:
                # The discovery url has already been resolved by another process recently. Skip its
                # scraping, we just need to add our category to its scraped_categories
                already_scraped_product_keys = json.loads(already_scraped_product_keys)
                already_updated_entities = self.wtbentity_set.filter(
                    key__in=already_scraped_product_keys
                )
                for entity in already_updated_entities:
                    entity.scraped_categories.add(category)
            else:
                wtb_brand_update_log.increment_task_counter()

                if use_async:
                    wtb_brand_create_or_update_entity_from_discovery_url.delay(
                        self.id,
                        wtb_brand_update_log.id,
                        discovery_url,
                        category.id,
                        extra_args,
                        products_for_url_concurrency,
                    )
                else:
                    self.create_or_update_entity_from_discovery_url(
                        wtb_brand_update_log, discovery_url, category, extra_args
                    )
            discovered_urls.append(discovery_url)

        # Mark the DB entities that were not detected as inactive
        entities_for_update = self.wtbentity_set.filter(
            scraped_categories=category
        ).exclude(url__in=discovered_urls)
        for entity in entities_for_update:
            entity.scraped_categories.remove(category)
            entity.save()

        wtb_brand_update_log.decrement_task_counter()

    def create_or_update_entity_from_discovery_url(
        self, wtb_brand_update_log, discovery_url, category, extra_args=None
    ):
        logger = logging.getLogger("logstash")

        existing_entities = self.wtbentity_set.filter(url=discovery_url)
        existing_entities_dict = {e.key: e for e in existing_entities}
        scraped_keys = []

        for scraped_product in self.scraper.products_for_url_with_custom_exception(
            discovery_url, category.storescraper_name, extra_args=extra_args
        ):
            logger.info(
                json.dumps(
                    {
                        "message": "Scraped product " + str(scraped_product),
                        "wtb_update_log_id": wtb_brand_update_log.id,
                    }
                )
            )

            scraped_keys.append(scraped_product.key)
            existing_entity = existing_entities_dict.pop(scraped_product.key, None)

            if existing_entity:
                existing_entity.update_with_scraped_product(
                    scraped_product, category=category
                )
            else:
                WtbEntity.create_from_scraped_product(scraped_product, self, category)

        for entity in existing_entities_dict.values():
            entity.scraped_categories.remove(category)

        cache_key = f"WTB_SCRAPING_{wtb_brand_update_log.id}_{sha256(discovery_url)}"
        cache.set(cache_key, json.dumps(scraped_keys), 60 * 60)
        wtb_brand_update_log.decrement_task_counter()

    class Meta:
        ordering = ("name",)
        permissions = [
            ("view_wtb_brand", "Can view the WTB brand"),
            ("is_wtb_brand_staff", "Is staff of this WTB brand"),
            ("backend_view_wtb", "Display the WTB menu in the backend"),
        ]


class WtbEntityQuerySet(models.QuerySet):
    def filter_by_user_perms(self, user, permission):
        synth_permissions = {
            "view_wtb_entity": {
                "wtb_brand": "view_wtb_brand",
                "category": "view_category",
            },
            "is_wtb_entity_staff": {
                "wtb_brand": "is_wtb_brand_staff",
                "category": "is_category_staff",
            },
        }

        assert permission in synth_permissions

        permissions = synth_permissions[permission]

        brands_with_permissions = WtbBrand.objects.filter_by_user_perms(
            user, permissions["wtb_brand"]
        )
        categories_with_permissions = Category.objects.filter_by_user_perms(
            user, permissions["category"]
        )

        return self.filter(
            brand__in=brands_with_permissions,
            category__in=categories_with_permissions,
        )

    def get_pending(self):
        return self.filter(product__isnull=True, is_visible=True)


class WtbEntity(models.Model):
    name = models.CharField(max_length=255, db_index=True)
    model_name = models.CharField(max_length=255, db_index=True)
    brand = models.ForeignKey(WtbBrand, on_delete=models.CASCADE)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    scraped_categories = models.ManyToManyField(Category, blank=True, related_name="+")
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, blank=True, null=True
    )
    key = models.CharField(max_length=255, db_index=True)
    section = models.CharField(max_length=255, blank=True, null=True)
    url = models.URLField()
    picture_url = models.URLField(max_length=256)
    price = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    creation_date = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    is_visible = models.BooleanField(default=True)

    objects = WtbEntityQuerySet.as_manager()

    # The last time the entity was associated. Important to leave standalone as
    # it is used for staff payments
    last_association = models.DateTimeField(null=True, blank=True)
    last_association_user = models.ForeignKey(
        get_user_model(), on_delete=models.CASCADE, null=True, blank=True
    )

    def __str__(self):
        return "{} - {}".format(self.brand, self.name)

    def user_has_staff_perms(self, user):
        return user.has_perm("is_wtb_brand_staff", self.brand) and user.has_perm(
            "is_category_staff", self.category
        )

    def save(self, *args, **kwargs):
        is_associated = bool(self.product_id)

        if bool(self.last_association_user_id) != bool(self.last_association):
            raise IntegrityError(
                "WtbEntity must have both last_association " "fields or none of them"
            )

        if not self.is_visible and is_associated:
            raise IntegrityError(
                "WtbEntity cannot be associated and be " "hidden at the same time"
            )

        if is_associated != bool(self.last_association_user_id):
            raise IntegrityError(
                "Associated wtb entities must have association metadata, "
                "non-associated entities must not"
            )

        super(WtbEntity, self).save(*args, **kwargs)

    def update_with_scraped_product(self, scraped_product, category):
        assert scraped_product is None or self.key == scraped_product.key

        if scraped_product:
            if scraped_product.picture_urls:
                picture_url = scraped_product.picture_urls[0]
            else:
                picture_url = "https://via.placeholder.com/200"

            # if scraped_product.positions:
            #     self.section = scraped_product.positions[0][0]

            self.name = scraped_product.name[:254]
            self.model_name = scraped_product.sku
            self.url = scraped_product.url[:190]
            self.picture_url = picture_url[:250]
            self.description = scraped_product.description
            self.category = category

            if scraped_product.normal_price and scraped_product.stock != 0:
                self.price = scraped_product.normal_price
            else:
                self.price = None

            self.save()
        elif self.scraped_categories.all():
            self.scraped_categories.set([])

    def associate(self, user, product):
        if not self.is_visible:
            raise IntegrityError("Non-visible cannot be associated")

        if self.product == product:
            raise IntegrityError("Re-associations must be made to a different product")

        if self.category != product.category:
            raise IntegrityError(
                "Entities must be associated to products of the same category"
            )

        self.last_association = timezone.now()
        self.last_association_user = user
        self.product = product
        self.save()

    def dissociate(self):
        if not self.product:
            raise IntegrityError("Cannot dissociate non-associated entity")

        self.last_association = None
        self.last_association_user = None
        self.product = None
        self.save()

    def external_site_url(self, entity):
        from django.conf import settings

        if self.brand_id in [settings.WTB_LG_CHILE_BRAND, settings.WTB_LG_PANAMA_BRAND]:
            return self._lg_external_site_url(entity)

        return self.url

    @classmethod
    def create_from_scraped_product(cls, scraped_product, brand, category):
        if scraped_product.picture_urls:
            picture_url = scraped_product.picture_urls[0]
        else:
            picture_url = "https://via.placeholder.com/200"

        # if scraped_product.positions:
        #     section = scraped_product.positions[0][0]
        # else:
        #     section = None

        if scraped_product.normal_price and scraped_product.stock != 0:
            price = scraped_product.normal_price
        else:
            price = None

        try:
            cls.objects.create(
                name=scraped_product.name[:254],
                model_name=scraped_product.sku,
                brand=brand,
                category=category,
                key=scraped_product.key,
                url=scraped_product.url[:190],
                picture_url=picture_url[:190],
                # section=section,
                price=price,
                description=scraped_product.description,
            )
        except IntegrityError:
            # There is the possibility of a race condition in our celery workers, where two of them may try to create
            # the same entity at almost the same time
            return

    class Meta:
        ordering = ("brand", "name")
        unique_together = ("brand", "key")
        permissions = [
            (
                "backend_view_pending_wtb_entities",
                "Can view the pending WTB entities interface in the backend",
            ),
        ]


class WtbBrandUpdateLog(models.Model):
    PENDING, IN_PROCESS, SUCCESS, ERROR = [1, 2, 3, 4]

    brand = models.ForeignKey(WtbBrand, on_delete=models.CASCADE)
    status = models.IntegerField(
        choices=[
            (PENDING, "Pending"),
            (IN_PROCESS, "In process"),
            (SUCCESS, "Success"),
            (ERROR, "Error"),
        ],
        default=PENDING,
    )
    creation_date = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    registry_file = models.FileField(
        storage=PrivateS3Boto3Storage(), upload_to="logs/wtb", null=True, blank=True
    )

    entity_count = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return "{} - {}".format(self.brand, self.last_updated)

    def initialize_task_counter(self, value):
        cache.set(self._caching_key(), value, timeout=60 * 60 * 24)
        entities_cache_key = f"{self._caching_key()}_entity_count"
        cache.set(entities_cache_key, 0, timeout=60 * 60 * 24)

    def increment_task_counter(self):
        new_val = cache.incr(self._caching_key())
        return new_val

    def increment_entity_count(self):
        entity_count_cache_key = f"{self._caching_key()}_entity_count"
        cache.incr(entity_count_cache_key)

    def decrement_task_counter(self):
        new_val = cache.decr(self._caching_key())

        if new_val == 0:
            logger = logging.getLogger("logstash")
            logger.info(
                json.dumps(
                    {
                        "message": "Finished WTB pricing update",
                        "wtb_update_log_id": self.id,
                    }
                )
            )
            if self.status == WtbBrandUpdateLog.IN_PROCESS:
                self.status = WtbBrandUpdateLog.SUCCESS
                self.entity_count = cache.get(f"{self._caching_key()}_entity_count")
                self.save()

    def save_with_error(self, logger, discovery_url=None):
        self.status = WtbBrandUpdateLog.ERROR
        self.save()
        payload = {
            "message": f"Error: {traceback.format_exc()}",
            "wtb_update_log_id": self.id,
            "discovery_url": discovery_url,
        }
        logger.error(json.dumps(payload))

    def _caching_key(self):
        return f"WTB_UPDATE_LOG_{self.id}"

    class Meta:
        ordering = ("brand", "-last_updated")
