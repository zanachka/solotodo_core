import json
import io
import base64
import logging

import xlsxwriter
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.db import models
from django.utils import timezone
from guardian.shortcuts import get_objects_for_user, get_objects_for_group
from sorl.thumbnail import ImageField

from .store_type import StoreType
from .country import Country
from .category import Category
from solotodo.utils import validate_sii_rut
from solotodo_core.s3utils import MediaRootS3Boto3Storage
from storescraper.utils import get_store_class_by_name


class StoreQuerySet(models.QuerySet):
    def filter_by_user_perms(self, user, permission, reload_cache=False):
        from solotodo_core import settings

        if user.is_superuser:
            return self

        user_group_names = [x["name"] for x in user.groups.values("name")]

        if permission == "view_store" and (
            user.is_anonymous or user_group_names == [settings.DEFAULT_GROUP_NAME]
        ):
            return self.filter_viewable_by_default_group(reload_cache=reload_cache)

        return get_objects_for_user(user, permission, self)

    def filter_by_banners_support(self):
        stores_with_banner_compatibility = []
        for store in self.filter(last_activation__isnull=False):
            try:
                _ = store.scraper.banners
                stores_with_banner_compatibility.append(store)
            except AttributeError:
                # The scraper of the store does not implement banners method
                pass

        return self.filter(pk__in=[s.id for s in stores_with_banner_compatibility])

    def filter_viewable_by_default_group(self, reload_cache=False):
        from solotodo_core import settings

        store_ids = cache.get("default_group_store_ids")
        if not store_ids or reload_cache:
            group = Group.objects.get(name=settings.DEFAULT_GROUP_NAME)
            stores = get_objects_for_group(group, "view_store", Store)
            store_ids = [x.id for x in stores]
            cache.set("default_group_store_ids", store_ids)

        return self.filter(pk__in=store_ids)

    def filter_by_section_positions_support(self):
        stores_with_section_positions_support = []
        for store in self.filter(last_activation__isnull=False):
            try:
                _ = store.scraper.sections()
                stores_with_section_positions_support.append(store)
            except (NotImplementedError, AttributeError):
                # The scraper of the store does not implement sections method
                pass

        return self.filter(pk__in=[s.id for s in stores_with_section_positions_support])


class Store(models.Model):
    name = models.CharField(max_length=255, db_index=True, unique=True)
    country = models.ForeignKey(Country, on_delete=models.CASCADE)
    last_activation = models.DateTimeField(null=True, blank=True)
    storescraper_class = models.CharField(max_length=255, db_index=True)
    storescraper_extra_args = models.CharField(max_length=255, null=True, blank=True)
    type = models.ForeignKey(StoreType, on_delete=models.CASCADE)
    logo = ImageField(upload_to="store_logos")
    preferred_payment_method = models.CharField(null=True, blank=True, max_length=100)
    active_banner_update = models.OneToOneField(
        "banners.BannerUpdate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    group = models.OneToOneField(
        Group,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="preferred_store",
    )
    last_updated = models.DateTimeField(auto_now=True)
    sii_rut = models.CharField(
        max_length=10, null=True, blank=True, validators=[validate_sii_rut]
    )
    sii_razon_social = models.CharField(max_length=255, null=True, blank=True)

    objects = StoreQuerySet.as_manager()

    scraper = property(lambda self: get_store_class_by_name(self.storescraper_class))

    def __str__(self):
        return self.name

    def scraper_categories(self):
        return Category.objects.filter(storescraper_name__in=self.scraper.categories())

    def sanitize_categories_for_update(self, original_categories=None):
        sanitized_categories = self.scraper_categories()

        if original_categories:
            sanitized_categories &= original_categories

        return sanitized_categories

    def check_and_fill_active_registries(self):
        from solotodo.models import Entity, EntityHistory, StoreUpdateLog

        success = 3
        today = timezone.now().date()

        logs = StoreUpdateLog.objects.filter(
            store=self, creation_date__date=today, status=success
        )

        if logs:
            return

        entities = Entity.objects.filter(store=self, active_registry__isnull=False)

        for entity in entities:
            current_eh = entity.active_registry

            new_eh = EntityHistory.objects.create(
                entity=entity,
                timestamp=timezone.now(),
                stock=current_eh.stock,
                normal_price=current_eh.normal_price,
                offer_price=current_eh.offer_price,
                cell_monthly_payment=current_eh.cell_monthly_payment,
                picture_count=current_eh.picture_count,
                video_count=current_eh.video_count,
                review_count=current_eh.review_count,
                review_avg_score=current_eh.review_avg_score,
            )

            entity.active_registry = new_eh
            entity.save()

    def update_banners(self):
        from banners.models import (
            BannerUpdate,
            Banner,
            BannerAsset,
            BannerSection,
            BannerSubsection,
            BannerSubsectionType,
        )

        scraper = self.scraper

        if self.storescraper_extra_args:
            extra_args = json.loads(self.storescraper_extra_args)
        else:
            extra_args = {}

        update = BannerUpdate.objects.create(store=self)

        try:
            scraped_banners_data = scraper.banners(extra_args=extra_args)
        except Exception as e:
            update.status = BannerUpdate.ERROR
            update.status_message = str(e)
            update.save()
            return

        section_dict = {
            section.name: section for section in BannerSection.objects.all()
        }

        subsection_type_dict = {
            subsection_type.storescraper_name: subsection_type
            for subsection_type in BannerSubsectionType.objects.all()
        }

        for banner_data in scraped_banners_data:
            if banner_data["section"] not in section_dict:
                update.status = BannerUpdate.ERROR
                update.status_message = "Invalid Section {}".format(
                    banner_data["section"]
                )
                update.save()
                return

            if banner_data["type"] not in subsection_type_dict:
                update.status = BannerUpdate.ERROR
                update.status_message = "Invalid Subsection Type {}".format(
                    banner_data["type"]
                )
                update.save()
                return

        for banner_data in scraped_banners_data:
            try:
                asset = BannerAsset.objects.get(key=banner_data["key"])
            except BannerAsset.DoesNotExist:
                if "picture_url" in banner_data:
                    picture_url = banner_data["picture_url"]
                else:
                    storage = MediaRootS3Boto3Storage()
                    image = base64.b64decode(banner_data["picture"])
                    file = io.BytesIO(image)
                    file.seek(0)
                    file_value = file.getvalue()
                    file_for_upload = ContentFile(file_value)

                    filename_template = "banner_%Y-%m-%d_%H:%M:%S"
                    filename = timezone.now().strftime(filename_template)

                    path = storage.save(
                        "banners/{}.png".format(filename), file_for_upload
                    )
                    picture_url = storage.url(path)

                asset = BannerAsset.objects.create(
                    key=banner_data["key"], picture_url=picture_url
                )

            section = section_dict[banner_data["section"]]
            subsection_type = subsection_type_dict[banner_data["type"]]

            subsection = BannerSubsection.objects.get_or_create(
                name=banner_data["subsection"], section=section, type=subsection_type
            )[0]

            destination_urls = ", ".join(banner_data["destination_urls"])

            Banner.objects.create(
                update=update,
                url=banner_data["url"],
                destination_urls=destination_urls,
                asset=asset,
                subsection=subsection,
                position=banner_data["position"],
            )

        update.status = BannerUpdate.SUCCESS
        update.save()
        self.active_banner_update = update
        self.save()

    def matching_report(self, store):
        from .entity import Entity

        entities = (
            Entity.objects.select_related(
                "active_registry", "product__instance_model", "category"
            )
            .filter(store=store)
            .get_available()
        )
        output = io.BytesIO()

        workbook = xlsxwriter.Workbook(output)
        workbook.formats[0].set_font_size(10)

        header_format_left = workbook.add_format(
            {"bold": True, "font_size": 10, "align": "left", "valign": "left"}
        )
        header_format_right = workbook.add_format(
            {"bold": True, "font_size": 10, "align": "right", "valign": "right"}
        )

        worksheet = workbook.add_worksheet()
        headers = [
            "Identificador",
            "SKU",
            "Nombre",
            "Condición",
            "URL",
            "Precio Normal",
            "Precio Oferta",
            "ID SKU SoloTodo",
            "Categoría SoloTodo",
            "Producto SoloTodo",
            "URL SoloTodo",
            "ID Producto SoloTodo",
        ]
        for idx, header in enumerate(headers):
            if "Precio" in header:
                worksheet.write(0, idx, header, header_format_right)
            else:
                worksheet.write(0, idx, header, header_format_left)
        row = 1
        for entity in entities:
            col = 0
            worksheet.write(row, col, entity.key)
            col += 1
            sku = entity.sku or "N/A"
            worksheet.write(row, col, sku)
            col += 1
            worksheet.write(row, col, entity.name)
            col += 1
            worksheet.write(row, col, entity.condition_as_text)
            col += 1
            worksheet.write(row, col, entity.url)
            col += 1
            worksheet.write(row, col, entity.active_registry.normal_price)
            col += 1
            worksheet.write(row, col, entity.active_registry.offer_price)
            col += 1
            worksheet.write(row, col, entity.id)
            col += 1
            worksheet.write(row, col, entity.category.name)
            col += 1
            if entity.product:
                worksheet.write(row, col, entity.product.instance_model.unicode_value)
                col += 1
                worksheet.write(
                    row,
                    col,
                    "https://www.solotodo.cl/products/" + str(entity.product.id),
                )
                col += 1
                worksheet.write(row, col, entity.product_id)
            elif entity.is_visible:
                worksheet.write(row, col, "N/A")
                col += 1
                worksheet.write(row, col, "N/A")
                col += 1
                worksheet.write(row, col, "N/A")
            else:
                worksheet.write(row, col, "No relevante")
                col += 1
                worksheet.write(row, col, "No relevante")
                col += 1
                worksheet.write(row, col, "No relevante")
            row += 1

        workbook.close()
        file_value = output.getvalue()
        file_for_upload = ContentFile(file_value)
        return file_for_upload

    def storescraper_extra_args_as_json(self):
        if self.storescraper_extra_args:
            return json.loads(self.storescraper_extra_args)
        else:
            return {}

    def update_pricing(
        self,
        categories=None,
        discover_urls_concurrency=None,
        products_for_url_concurrency=None,
        use_async=None,
        update_log=None,
        extra_args=None,
    ):
        from solotodo.models import StoreUpdateLog
        from solotodo.tasks import store_category_update_pricing

        assert self.last_activation is not None

        if not discover_urls_concurrency:
            discover_urls_concurrency = self.scraper.preferred_discover_urls_concurrency

        if not products_for_url_concurrency:
            products_for_url_concurrency = (
                self.scraper.preferred_products_for_url_concurrency
            )

        if use_async is None:
            use_async = self.scraper.prefer_async

        if not update_log:
            update_log = StoreUpdateLog.objects.create(
                store=self, status=StoreUpdateLog.IN_PROCESS
            )

        if extra_args:
            extra_args = self.storescraper_extra_args_as_json() | extra_args
        else:
            extra_args = self.storescraper_extra_args_as_json()

        extra_args = self.scraper.extra_args_with_preflight(extra_args)

        categories = self.sanitize_categories_for_update(categories)

        if not categories:
            update_log.status = update_log.ERROR
            update_log.save()
            return update_log

        update_log.discovery_url_concurrency = discover_urls_concurrency
        update_log.products_for_url_concurrency = products_for_url_concurrency
        update_log.use_async = use_async
        update_log.save()

        update_log.categories.set(categories)

        logger = logging.getLogger("logstash")
        logging_payload = {
            "message": "Started pricing update for: "
            + ", ".join(category.name for category in categories),
            "update_log_id": update_log.id,
        }
        logger.info(json.dumps(logging_payload))

        if use_async:
            cache.set(f"{self.id}_discover_entries", 0, 2 * 60 * 60)
            cache.set(f"{self.id}_products_for_url", 0, 2 * 60 * 60)

            update_log.initialize_task_counter(0)
            for category in categories:
                update_log.increment_task_counter()

                if use_async:
                    store_category_update_pricing.delay(
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
                self.update_pricing_category(
                    category,
                    products_for_url_concurrency,
                    use_async,
                    update_log,
                    extra_args,
                )
            update_log.decrement_task_counter()
        return update_log

    def update_pricing_category(
        self,
        category,
        products_for_url_concurrency,
        use_async,
        update_log,
        extra_args,
    ):
        from solotodo.tasks import store_create_or_update_entity_from_discovery_url

        logger = logging.getLogger("logstash")
        logging_payload = {
            "message": "Started category pricing update: " + str(category),
            "update_log_id": update_log.id,
        }
        logger.info(json.dumps(logging_payload))
        discovered_urls = []
        logger.info(
            json.dumps(
                {
                    "message": "Discovering URLs for category: " + str(category),
                    "update_log_id": update_log.id,
                }
            )
        )
        for (
            discovery_url
        ) in self.scraper.discover_urls_for_category_with_custom_exception(
            category.storescraper_name, extra_args=extra_args
        ):
            cache_key = f"SCRAPING_{update_log.id}_{hash(discovery_url)}"
            already_scraped_product_keys = cache.get(cache_key)
            if already_scraped_product_keys:
                # The discovery url has already been resolved by another process recently. Skip its
                # scraping, we just need to add our category to its scraped_categories
                already_scraped_product_keys = json.loads(already_scraped_product_keys)
                already_updated_entities = self.entity_set.filter(
                    key__in=already_scraped_product_keys
                )
                for entity in already_updated_entities:
                    entity.scraped_categories.add(category)
            else:
                update_log.increment_task_counter()
                if use_async:
                    store_create_or_update_entity_from_discovery_url.delay(
                        self.id,
                        update_log.id,
                        discovery_url,
                        category.id,
                        extra_args,
                        products_for_url_concurrency,
                    )
                else:
                    self.create_or_update_entity_from_discovery_url(
                        update_log, discovery_url, category, extra_args
                    )
            discovered_urls.append(discovery_url)

        # Mark the DB entities that were not detected as inactive
        entities_for_update = (
            self.entity_set.get_active()
            .filter(scraped_categories=category)
            .exclude(discovery_url__in=discovered_urls)
        )
        for entity in entities_for_update:
            # Remove the category from the entity scraped_categories to prevent it from being marked as inactive by
            # mistake by a future update of this category. For example if an entity has discovered_categories of
            # Accesories and Headphones, and the store moves it to just Headphones, then the entity will be marked as
            # active by the category update of Headphones, but then will be marked as inactive by the category update
            # of Accesories if the Accesories update runs after the one of Headphones. This case may still happen
            # once with this solution, but by the second time it will be solved and stable.
            entity.scraped_categories.remove(category)
            entity.active_registry = None
            entity.save()

        update_log.decrement_task_counter()

    def create_or_update_entity_from_discovery_url(
        self, update_log, discovery_url, category, extra_args=None
    ):
        from solotodo.models import Entity

        logger = logging.getLogger("logstash")

        existing_entities = self.entity_set.filter(discovery_url=discovery_url)
        existing_entities_dict = {e.key: e for e in existing_entities}
        scraped_keys = []

        products_found = False
        for scraped_product in self.scraper.products_for_url_with_custom_exception(
            discovery_url, category.storescraper_name, extra_args=extra_args
        ):
            logger.info(
                json.dumps(
                    {
                        "message": "Scraped product " + str(scraped_product),
                        "update_log_id": update_log.id,
                    }
                )
            )

            products_found = True
            scraped_keys.append(scraped_product.key)
            if scraped_product.is_available():
                update_log.increment_available_products_count()
            else:
                update_log.increment_unavailable_products_count()

            existing_entity = existing_entities_dict.pop(scraped_product.key, None)

            if not existing_entity:
                # Check the case of a pre existing entity that changed its discovery_url
                try:
                    existing_entity = self.entity_set.get(key=scraped_product.key)
                except Entity.DoesNotExist:
                    pass

            if existing_entity:
                existing_entity.update_with_scraped_product(
                    scraped_product, category=category
                )
            else:
                Entity.create_from_scraped_product(scraped_product, self, category)
        if not products_found:
            update_log.increment_discovery_urls_without_products_count()

        for entity in existing_entities_dict.values():
            if entity.active_registry:
                # Mark as inactive
                entity.active_registry = None
                entity.save()

        cache_key = f"SCRAPING_{update_log.id}_{hash(discovery_url)}"
        cache.set(cache_key, json.dumps(scraped_keys), 60 * 60)
        update_log.decrement_task_counter()

    def update_section_positions(
        self,
        sections=None,
        concurrency=None,
        use_async=None,
        update_log=None,
        extra_args=None,
    ):
        from solotodo.models import StoreSectionPositionsUpdateLog
        from solotodo.tasks import store_update_individual_section_positions

        assert self.last_activation is not None

        # The preferred_discover_urls_concurrency is a reasonable default
        if not concurrency:
            concurrency = self.scraper.preferred_discover_urls_concurrency

        if use_async is None:
            use_async = self.scraper.prefer_async

        if not update_log:
            update_log = StoreSectionPositionsUpdateLog.objects.create(
                store=self,
                status=StoreSectionPositionsUpdateLog.IN_PROCESS,
                concurrency=concurrency,
                use_async=use_async,
            )

        if extra_args:
            extra_args = self.storescraper_extra_args_as_json() | extra_args
        else:
            extra_args = self.storescraper_extra_args_as_json()

        extra_args = self.scraper.extra_args_with_preflight(extra_args)

        if not sections:
            sections = self.scraper.sections()

        logger = logging.getLogger("logstash")
        logging_payload = {
            "message": "Started section positions update for: " + ", ".join(sections),
            "section_positions_update_log_id": update_log.id,
        }
        logger.info(json.dumps(logging_payload))

        if use_async:
            cache.set(f"{self.id}_section_positions", 0, 60 * 60)
            update_log.initialize_task_counter(0)
            for section in sections:
                update_log.increment_task_counter()

                if use_async:
                    store_update_individual_section_positions.delay(
                        self.id,
                        section,
                        concurrency,
                        update_log.id,
                        extra_args,
                    )
        else:
            update_log.initialize_task_counter(1)
            for section in sections:
                update_log.increment_task_counter()
                self.update_individual_section_positions(
                    section,
                    update_log,
                    extra_args,
                )
            update_log.decrement_task_counter()
        return update_log

    def update_individual_section_positions(
        self,
        section,
        update_log,
        extra_args,
    ):
        from solotodo.models import StoreSection, EntitySectionPosition

        logger = logging.getLogger("logstash")
        logging_payload = {
            "message": "Started section position update: " + section,
            "section_positions_update_log_id": update_log.id,
        }
        logger.info(json.dumps(logging_payload))

        sections_dict = {}
        for section_position in self.scraper.section_positions_with_custom_exception(
            section, extra_args=extra_args
        ):
            if section_position["section"] in sections_dict:
                store_section = sections_dict[section_position["section"]]
            else:
                store_section, _created = StoreSection.objects.get_or_create(
                    store=self, name=section_position["section"]
                )
                sections_dict[section_position["section"]] = store_section

            entities_filter = {section_position["field"]: section_position["value"]}
            entities_for_update = self.entity_set.get_active().filter(**entities_filter)
            for entity in entities_for_update:
                logger.info(
                    json.dumps(
                        {
                            "message": f"Setting {entity}: {store_section.name} - {section_position['position']}",
                            "section_positions_update_log_id": update_log.id,
                        }
                    )
                )
                EntitySectionPosition.objects.create(
                    entity_history=entity.active_registry,
                    section=store_section,
                    value=section_position["position"],
                    is_sponsored=section_position["is_sponsored"],
                )
        update_log.decrement_task_counter()

    class Meta:
        app_label = "solotodo"
        ordering = ["name"]
        permissions = (
            ["view_store_update_logs", "Can view the store update logs"],
            ["view_store_stocks", "Can view the store entities stock"],
            ["update_store_pricing", "Can update the store pricing"],
            ["view_store_leads", "View the leads associated to this store"],
            ["view_store_reports", "Download the reports associated to this store"],
            # "Backend" permissions are used exclusively for UI purposes, they
            # are not used at the API level
            ["backend_list_stores", "Can view store list in backend"],
            ["view_store_banners", "Can view store banners"],
            ["view_store_entity_positions", "Can view store entity positions"],
            [
                "create_store_keyword_search",
                "Can create keyword searches in this store",
            ],
            ["view_store_sii_details", "Can view the SII details for the store"],
        )
