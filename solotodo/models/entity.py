import io
import json
import re

import rapidfuzz
import time
import urllib
from decimal import Decimal
from enum import Enum
from typing import Union

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.validators import validate_comma_separated_integer_list
from django.db import models, IntegrityError
from django.db.models import Q, Count
from django.utils import timezone
from PIL import Image, UnidentifiedImageError
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.chains.retrieval import create_retrieval_chain
from langchain_core.prompts import ChatPromptTemplate
from pyzbar.pyzbar import decode
from pydantic import Field, create_model

from .solotodo_user import SoloTodoUser
from .product import Product
from .currency import Currency
from .category import Category
from .store import Store
from .bundle import Bundle
from .coupon import Coupon
from .es_product import EsProduct
from solotodo.utils import iterable_to_dict, fetch_sec_fields
from solotodo_core.s3utils import MediaRootS3Boto3Storage
from metamodel.models import InstanceModel


class EntityQueryset(models.QuerySet):
    def get_available(self):
        return self.filter(active_registry__stock__ne=0)

    def get_unavailable(self):
        return self.filter(
            Q(active_registry__isnull=True) | Q(active_registry__stock=0)
        )

    def get_active(self):
        return self.filter(active_registry__isnull=False)

    def get_inactive(self):
        return self.filter(active_registry__isnull=True)

    def filter_by_user_perms(self, user, permission):
        synth_permissions = {
            "view_entity": {
                "store": "view_store",
                "category": "view_category",
            },
            "view_entity_stocks": {
                "store": "view_store_stocks",
                "category": "view_category",
            },
            "is_entity_staff": {
                "store": "view_store",
                "category": "is_category_staff",
            },
        }

        assert permission in synth_permissions

        permissions = synth_permissions[permission]

        stores_with_permissions = Store.objects.filter_by_user_perms(
            user, permissions["store"]
        )
        categories_with_permissions = Category.objects.filter_by_user_perms(
            user, permissions["category"]
        )

        return self.filter(
            store__in=stores_with_permissions,
            category__in=categories_with_permissions,
        )

    def get_pending(self):
        return self.get_available().filter(product__isnull=True, is_visible=True)

    def update(self, *args, **kwargs):
        raise Exception(
            "Queryset level update is disabled on Entity as it "
            "does not emit pre_save / post_save signals"
        )

    def estimated_sales(
        self, start_date=None, end_date=None, sorting="normal_price_sum"
    ):
        from solotodo.models import EntityHistory

        ehs = EntityHistory.objects.filter(entity__in=self, stock__gt=0)
        if start_date:
            ehs = ehs.filter(timestamp__gte=start_date)
        if end_date:
            ehs = ehs.filter(timestamp__lte=end_date)

        ehs = ehs.order_by("entity", "timestamp").select_related("entity")

        movements_by_entity = {}
        for e in self:
            movements_by_entity[e] = {
                "count": 0,
                "normal_price_sum": Decimal(0),
                "offer_price_sum": Decimal(0),
            }

        last_eh_seen = None

        for eh in ehs:
            if not last_eh_seen or last_eh_seen.entity != eh.entity:
                pass
            else:
                units_sold = last_eh_seen.stock - eh.stock
                if units_sold > 0 and units_sold / last_eh_seen.stock < 0.1:
                    movements_by_entity[eh.entity]["count"] += units_sold
                    movements_by_entity[eh.entity]["normal_price_sum"] += (
                        units_sold * last_eh_seen.normal_price
                    )
                    movements_by_entity[eh.entity]["offer_price_sum"] += (
                        units_sold * last_eh_seen.offer_price
                    )
            last_eh_seen = eh

        result_list = [
            {
                "entity": entity,
                "count": value["count"],
                "normal_price_sum": value["normal_price_sum"],
                "offer_price_sum": value["offer_price_sum"],
            }
            for entity, value in movements_by_entity.items()
        ]

        sorted_results = sorted(result_list, key=lambda x: x[sorting], reverse=True)

        return sorted_results

    def conflicts(self):
        raw_conflicts = (
            self.filter(product__isnull=False)
            .get_available()
            .values("store", "product", "cell_plan", "bundle")
            .annotate(conflict_count=Count("pk"))
            .order_by("store", "product", "cell_plan", "bundle")
            .filter(conflict_count__gt=1)
        )

        store_ids = set()
        product_ids = set()
        bundle_ids = set()

        entities_query = Q()
        for entry in raw_conflicts:
            store_ids.add(entry["store"])
            product_ids.add(entry["product"])
            if entry["cell_plan"]:
                product_ids.add(entry["cell_plan"])
            if entry["bundle"]:
                bundle_ids.add(entry["bundle"])

            entities_query |= (
                Q(store=entry["store"])
                & Q(product=entry["product"])
                & Q(cell_plan=entry["cell_plan"])
                & Q(bundle=entry["bundle"])
            )

        entities = (
            Entity.objects.get_available().filter(entities_query).select_related()
        )

        entities_dict = {}
        for entity in entities:
            key = (
                entity.store_id,
                entity.product_id,
                entity.cell_plan_id,
                entity.bundle_id,
            )
            if key not in entities_dict:
                entities_dict[key] = []
            entities_dict[key].append(entity)

        stores_dict = iterable_to_dict(Store.objects.filter(pk__in=store_ids))
        products_dict = iterable_to_dict(
            Product.objects.filter(pk__in=product_ids).select_related(
                "instance_model__model__category"
            )
        )
        products_dict[None] = None

        bundles_dict = iterable_to_dict(Bundle.objects.filter(pk__in=bundle_ids))
        bundles_dict[None] = None

        result = []
        for entry in raw_conflicts:
            result.append(
                {
                    "store": stores_dict[entry["store"]],
                    "product": products_dict[entry["product"]],
                    "cell_plan": products_dict[entry["cell_plan"]],
                    "bundle": bundles_dict[entry["bundle"]],
                    "entities": entities_dict[
                        (
                            entry["store"],
                            entry["product"],
                            entry["cell_plan"],
                            entry["bundle"],
                        )
                    ],
                }
            )

        return result


class Entity(models.Model):
    CONDITION_CHOICES = [
        ("https://schema.org/DamagedCondition", "Damaged"),
        ("https://schema.org/NewCondition", "New"),
        ("https://schema.org/RefurbishedCondition", "Refurbished"),
        ("https://schema.org/UsedCondition", "Used"),
        # This is not part of the schema standard
        ("https://schema.org/OpenBoxCondition", "Open Box"),
    ]
    CONDITION_CHOICES_DICT = dict(CONDITION_CHOICES)
    DEFAULT_IMAGE = "products/not_found.png"
    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    scraped_category = models.ForeignKey(
        Category, on_delete=models.CASCADE, related_name="+"
    )
    scraped_categories = models.ManyToManyField(Category, blank=True, related_name="+")
    currency = models.ForeignKey(Currency, on_delete=models.CASCADE)
    condition = models.URLField(choices=CONDITION_CHOICES, db_index=True)
    scraped_condition = models.URLField(choices=CONDITION_CHOICES, db_index=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, null=True)
    bundle = models.ForeignKey(Bundle, on_delete=models.CASCADE, null=True)
    cell_plan = models.ForeignKey(
        Product, on_delete=models.CASCADE, null=True, related_name="+"
    )
    best_coupon = models.ForeignKey(
        Coupon,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entities_with_coupon",
    )
    active_registry = models.OneToOneField(
        "EntityHistory", on_delete=models.CASCADE, related_name="+", null=True
    )
    name = models.CharField(max_length=256, db_index=True)
    cell_plan_name = models.CharField(
        max_length=60, null=True, blank=True, db_index=True
    )
    part_number = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    sku = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    ean = models.CharField(max_length=50, null=True, blank=True)
    key = models.CharField(max_length=256, db_index=True)
    url = models.URLField(max_length=512, db_index=True)
    discovery_url = models.URLField(max_length=512, db_index=True)
    picture_urls = models.TextField(blank=True, null=True)
    description = models.TextField(null=True)
    video_urls = models.TextField(blank=True, null=True)
    flixmedia_id = models.CharField(max_length=256, blank=True, null=True)
    review_count = models.IntegerField(blank=True, null=True)
    review_avg_score = models.FloatField(blank=True, null=True)
    has_virtual_assistant = models.BooleanField(null=True, blank=True)
    sec_qr_codes = models.CharField(
        validators=[validate_comma_separated_integer_list],
        null=True,
        blank=True,
        max_length=255,
        db_index=True,
    )
    seller = models.CharField(max_length=256, blank=True, null=True, db_index=True)
    is_visible = models.BooleanField(default=True)

    # Metadata

    creation_date = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)

    # The last time the entity was associated. Important to leave standalone as
    # it is used for staff payments
    last_association = models.DateTimeField(null=True, blank=True)
    last_association_user = models.ForeignKey(
        get_user_model(), on_delete=models.CASCADE, null=True
    )

    # Last time a staff accessed the entity in the backend. Used to display a
    # warning to other staff if they try to access it at the same time.
    last_staff_access = models.DateTimeField(null=True, blank=True)
    last_staff_access_user = models.ForeignKey(
        get_user_model(), on_delete=models.CASCADE, null=True, related_name="+"
    )

    # The last time the pricing of this entity was updated. Needed because
    # active_registry may be null. It does not match the active_registry date
    # either way because the registry uses the timestamp of the scraping, and
    # this field uses the timestamp of the moment it is updated in the database
    last_pricing_update = models.DateTimeField()

    ai_association_result = models.JSONField(null=True, blank=True)

    objects = EntityQueryset.as_manager()

    def __str__(self):
        result = "{} - {}".format(self.store, self.name)
        if self.cell_plan_name:
            result += " / {}".format(self.cell_plan_name)
        result += " ({})".format(self.category)

        return result

    @property
    def condition_as_text(self):
        return self.CONDITION_CHOICES_DICT[self.condition]

    def is_available(self):
        if self.active_registry:
            return self.active_registry.stock != 0

        return False

    def update_with_scraped_product(
        self, scraped_product, sections_dict={}, category=None, currency=None
    ):
        from solotodo.models import EntityHistory, StoreSection, EntitySectionPosition

        assert scraped_product is None or self.key == scraped_product.key

        # If the entity is currently inactive and no scraping information
        # was obtained for it then just return
        if not self.active_registry_id and not scraped_product:
            return

        updated_data = {
            "last_pricing_update": timezone.now(),
        }

        if scraped_product:
            if category is None:
                category = Category.objects.get(
                    storescraper_name=scraped_product.category
                )

            if currency is None:
                currency = Currency.objects.get(iso_code=scraped_product.currency)

            new_active_registry = EntityHistory.objects.create(
                entity=self,
                stock=scraped_product.stock,
                normal_price=scraped_product.normal_price,
                offer_price=scraped_product.offer_price,
                cell_monthly_payment=scraped_product.cell_monthly_payment,
                timestamp=scraped_product.timestamp,
                picture_count=scraped_product.picture_urls_count(),
                video_count=scraped_product.video_urls_count(),
                review_count=scraped_product.review_count,
                review_avg_score=scraped_product.review_avg_score,
            )

            updated_data.update(
                {
                    "name": scraped_product.name,
                    "scraped_category": category,
                    "currency": currency,
                    "cell_plan_name": scraped_product.cell_plan_name,
                    "part_number": scraped_product.part_number,
                    "sku": scraped_product.sku,
                    "ean": scraped_product.ean,
                    "url": scraped_product.url,
                    "discovery_url": scraped_product.discovery_url,
                    "picture_urls": scraped_product.picture_urls_as_json(),
                    "video_urls": scraped_product.video_urls_as_json(),
                    "description": scraped_product.description,
                    "scraped_condition": scraped_product.condition,
                    "flixmedia_id": scraped_product.flixmedia_id,
                    "seller": scraped_product.seller,
                    "review_count": scraped_product.review_count,
                    "review_avg_score": scraped_product.review_avg_score,
                    "has_virtual_assistant": scraped_product.has_virtual_assistant,
                    "active_registry": new_active_registry,
                }
            )

            # If the entity condition hasn't been changed manually by the
            # staff, update it with the scraped condition
            if self.condition == self.scraped_condition:
                updated_data["condition"] = scraped_product.condition
        else:
            updated_data.update({"active_registry": None})

        self.update_keeping_log(updated_data)

    @classmethod
    def create_from_scraped_product(
        cls, scraped_product, store, category, currency=None, sections_dict=dict
    ):
        from solotodo.models import EntityHistory

        if not currency:
            currency = Currency.objects.get(iso_code=scraped_product.currency)

        new_entity = cls.objects.create(
            store=store,
            category=category,
            scraped_category=category,
            currency=currency,
            condition=scraped_product.condition,
            scraped_condition=scraped_product.condition,
            name=scraped_product.name,
            cell_plan_name=scraped_product.cell_plan_name,
            part_number=scraped_product.part_number,
            sku=scraped_product.sku,
            ean=scraped_product.ean,
            key=scraped_product.key,
            url=scraped_product.url,
            discovery_url=scraped_product.discovery_url,
            picture_urls=scraped_product.picture_urls_as_json(),
            video_urls=scraped_product.video_urls_as_json(),
            description=scraped_product.description,
            flixmedia_id=scraped_product.flixmedia_id,
            seller=scraped_product.seller,
            review_count=scraped_product.review_count,
            review_avg_score=scraped_product.review_avg_score,
            has_virtual_assistant=scraped_product.has_virtual_assistant,
            is_visible=True,
            last_pricing_update=timezone.now(),
        )

        new_entity_history = EntityHistory.objects.create(
            entity=new_entity,
            stock=scraped_product.stock,
            normal_price=scraped_product.normal_price,
            offer_price=scraped_product.offer_price,
            cell_monthly_payment=scraped_product.cell_monthly_payment,
            timestamp=scraped_product.timestamp,
            picture_count=scraped_product.picture_urls_count(),
            video_count=scraped_product.video_urls_count(),
            review_count=scraped_product.review_count,
            review_avg_score=scraped_product.review_avg_score,
        )

        new_entity.active_registry = new_entity_history
        new_entity.save()

    def update_keeping_log(self, updated_data, user=None):
        from solotodo.models import EntityLog

        if not user:
            user = get_user_model().get_bot()

        entity_log = EntityLog(
            entity=self,
            user=user,
        )

        save_log = False

        for field, new_value in updated_data.items():
            old_value = getattr(self, field)
            if field in EntityLog.DATA_FIELDS:
                setattr(entity_log, field, old_value)
                if old_value != new_value:
                    save_log = True

            setattr(self, field, new_value)

        self.save()

        if save_log:
            # Fill the remaining fields
            for field in EntityLog.DATA_FIELDS:
                if field not in updated_data:
                    entity_value = getattr(self, field)
                    setattr(entity_log, field, entity_value)
            entity_log.save()

    def save(self, *args, **kwargs):
        is_associated = bool(self.product_id or self.cell_plan_id or self.bundle)

        if bool(self.last_association_user_id) != bool(self.last_association):
            raise IntegrityError(
                "Entity must have both last_association " "fields or none of them"
            )

        if not self.is_visible and is_associated:
            raise IntegrityError(
                "Entity cannot be associated and be hidden " "at the same time"
            )

        if not self.product_id and self.cell_plan_id:
            raise IntegrityError(
                "Entity cannot have a cell plan but " "not a primary product"
            )

        if not self.product_id and self.bundle_id:
            raise IntegrityError(
                "Entity cannot have a bundle plan but " "not a primary product"
            )

        if is_associated != bool(self.last_association_user_id):
            raise IntegrityError(
                "Associated entities must have association metadata, "
                "non-associated entities must not"
            )

        super(Entity, self).save(*args, **kwargs)

    def update_pricing(self):
        scraper = self.store.scraper

        if self.store.storescraper_extra_args:
            extra_args = json.loads(self.store.storescraper_extra_args)
        else:
            extra_args = None

        scraped_products = scraper.products_for_url(
            self.discovery_url,
            category=self.scraped_category.storescraper_name,
            extra_args=extra_args,
        )

        entity_scraped_product = None
        for scraped_product in scraped_products:
            if scraped_product.key == self.key:
                entity_scraped_product = scraped_product
                break

        self.update_with_scraped_product(entity_scraped_product)

    def events(self):
        entity = self
        events = []

        def apply_log_to_entity(log):
            from solotodo.models import EntityLog

            local_changes = []

            for field in EntityLog.DATA_FIELDS:
                entity_value = getattr(entity, field)
                log_value = getattr(log, field)
                if entity_value != log_value:
                    setattr(entity, field, log_value)
                    local_changes.append(
                        {
                            "field": field,
                            "old_value": log_value,
                            "new_value": entity_value,
                        }
                    )

            return local_changes

        for log in self.entitylog_set.select_related():
            changes = apply_log_to_entity(log)
            events.append(
                {"user": log.user, "timestamp": log.creation_date, "changes": changes}
            )

        return events

    def user_has_staff_perms(self, user):
        return user.has_perm("is_category_staff", self.category)

    def user_can_view_stocks(self, user):
        return user.has_perm("view_category", self.category) and user.has_perm(
            "view_store_stocks", self.store
        )

    def associate(self, user, product, cell_plan=None, bundle=None):
        if not self.is_visible:
            raise IntegrityError("Non-visible cannot be associated")

        if (
            self.product == product
            and self.cell_plan == cell_plan
            and self.bundle == bundle
        ):
            raise IntegrityError(
                "Re-associations must be made to a different product / "
                "cell plan / bundle combination"
            )

        if self.category != product.category:
            raise IntegrityError(
                "Entities must be associated to products of the same category"
            )

        if self.cell_plan_name and not cell_plan:
            raise IntegrityError("Entities with cell plan name must specify a plan.")

        now = timezone.now()

        update_dict = {
            "last_association": now,
            "last_association_user": user,
            "product": product,
            "cell_plan": cell_plan,
            "bundle": bundle,
        }

        self.update_keeping_log(update_dict, user)

    def dissociate(self, user, reason=None):
        if not self.product:
            raise IntegrityError("Cannot dissociate non-associated entity")
        if reason and self.last_association_user == user:
            raise IntegrityError(
                "Reason must not be present if the last association user is "
                "the same as the one dissociating the entity"
            )

        update_dict = {
            "last_association": None,
            "last_association_user": None,
            "product": None,
            "cell_plan": None,
            "bundle": None,
        }

        if reason:
            self.last_association_user.send_entity_dissociation_mail(self, user, reason)

        self.update_keeping_log(update_dict, user)

    def associate_related_cell_entities(self, user):
        from django.conf import settings

        assert self.cell_plan_name
        assert self.product

        print("Associating related entities for: {}".format(self))

        other_entities = Entity.objects.filter(
            store=self.store, name=self.name
        ).exclude(pk=self.pk)

        other_cell_plan_names = [e.cell_plan_name for e in other_entities]

        cell_plan_category = Category.objects.get(pk=settings.CELL_PLAN_CATEGORY)

        matching_cell_plans = (
            EsProduct.category_search(cell_plan_category)
            .filter("terms", specs__association_name=other_cell_plan_names)[:100]
            .execute()
        )

        cell_plan_ids = [cell_plan.product_id for cell_plan in matching_cell_plans]
        cell_plans = Product.objects.filter(pk__in=cell_plan_ids)
        cell_plans_dict = iterable_to_dict(cell_plans)

        cell_plans_dict = {
            cell_plan.specs["association_name"]: cell_plans_dict[cell_plan.product_id]
            for cell_plan in matching_cell_plans
        }

        print("Related entities found:")
        for entity in other_entities:
            print("* {}".format(entity))

            if entity.cell_plan_name in cell_plans_dict:
                cell_plan = cell_plans_dict[entity.cell_plan_name]
                print("Matching plan found: {}".format(cell_plan))
                if (
                    entity.product != self.product
                    or entity.cell_plan != cell_plan
                    or entity.bundle != self.bundle
                ):
                    entity.associate(user, self.product, cell_plan, self.bundle)
            else:
                print("No matching cell plan found")

    def picture_urls_as_list(self):
        if not self.picture_urls:
            return None
        return json.loads(self.picture_urls)

    def video_urls_as_list(self):
        if not self.video_urls:
            return None
        return json.loads(self.video_urls)

    def affiliate_url(self, soicos_prefix=""):
        from django.conf import settings

        linio_settings = settings.LINIO_AFFILIATE_SETTINGS
        affiliate_ids = settings.AFFILIATE_IDS

        if self.store_id == linio_settings["STORE_ID"]:
            if "?" in self.url:
                separator = "&"
            else:
                separator = "?"

            target_url = (
                "{}{}utm_source=affiliates&utm_medium=hasoffers&"
                "utm_campaign={}&aff_sub="
                "".format(self.url, separator, linio_settings["AFFILIATE_ID"])
            )

            url = (
                "https://linio.go2cloud.org/aff_c?offer_id=18&aff_id={}"
                "&url={}".format(
                    linio_settings["AFFILIATE_ID"], urllib.parse.quote(target_url)
                )
            )
            return url
        elif self.store_id in affiliate_ids:
            target_url = self.url
            affiliate_id = affiliate_ids[self.store_id]
            url = "https://ad.soicos.com/{}?dl={}&trackerID={}{}".format(
                affiliate_id,
                urllib.parse.quote(target_url),
                soicos_prefix,
                self.active_registry_id,
            )

            return url

        return None

    def update_sec_qr_codes(self):
        extra_args = self.store.storescraper_extra_args_as_json()
        session = self.store.scraper.get_session(extra_args)
        picture_urls = self.picture_urls_as_list() or []

        qr_codes = set()
        for picture_url in picture_urls:
            response = session.get(picture_url, timeout=10)
            if response.status_code != 200:
                continue
            image = Image.open(io.BytesIO(response.content))
            decoded_qr_codes = decode(image)
            for decoded_qr_code in decoded_qr_codes:
                if decoded_qr_code.type != "QRCODE":
                    continue
                qr_url = decoded_qr_code.data.decode("UTF-8")
                qr_code_match = re.match(
                    r"https://ww6.sec.cl/qr/qr.do\?a=prod&i=(\d+)$", qr_url
                )
                if not qr_code_match:
                    continue
                qr_code = str(int(qr_code_match.groups()[0]))
                qr_codes.add(qr_code)

        if qr_codes:
            sec_qr_codes = ",".join(qr_codes)
        else:
            sec_qr_codes = "0"

        self.sec_qr_codes = sec_qr_codes
        self.save()

    def sec_info(self):
        if not self.sec_qr_codes or self.sec_qr_codes == "0":
            return []
        sec_qr_codes = self.sec_qr_codes.split(",")
        sec_entries = []
        for sec_qr_code in sec_qr_codes:
            zeros = 13 - len(sec_qr_code)
            sec_url = "https://ww6.sec.cl/qr/qr.do?a=prod&i={}{}".format(
                zeros * "0", sec_qr_code
            )
            raw_sec_data = fetch_sec_fields(sec_qr_code)
            sec_entry = {
                "code": sec_qr_code,
                "sec_url": sec_url,
                "brands": raw_sec_data["Marcas"],
                "models": raw_sec_data["Modelos"],
            }
            sec_entries.append(sec_entry)
        return sec_entries

    def ai_get_input(self):
        data = {
            "name": self.name,
            "description": self.description,
            "url": self.url,
        }

        if self.part_number:
            data["manufacturer_part_number"] = self.part_number

        if self.sec_qr_codes and self.sec_qr_codes != "0":
            data["sec_qr_codes"] = self.sec_qr_codes

        return json.dumps(data)

    def ai_infer_category(self):
        tagging_prompt = ChatPromptTemplate.from_template(
            """
            Determine what category the product corresponds to based on its characteristics:
            {input}
            """
        )
        field_data = Field(
            description="The product category. Choose from predefined options or suggest a new one if none fit."
        )
        categories = list(Category.objects.all().values_list("name", flat=True))
        enum = Enum("categoryEnum", {choice: choice for choice in categories}, type=str)
        Classification = create_model(
            "Classification", category=(Union[enum, str], field_data)
        )
        llm = settings.LLM.with_structured_output(Classification)
        prompt = tagging_prompt.invoke({"input": self.ai_get_input()})
        infered_category = llm.invoke(prompt).category

        if infered_category not in categories:
            raise (
                Exception(f"The infered Category does not exist: {infered_category}")
            )

        return Category.objects.get(name=infered_category)

    def ai_infer_product_data(self):
        errors = {}
        if not self.description:
            errors["general"] = "The entity does not have a description"
            return {}, errors

        tagging_prompt = ChatPromptTemplate.from_template(
            """
            Determine the specifications of the product described in the following JSON document. The field 'description' is in Markdown format
            
            {input}
            """
        )
        fields_annotation, fields_enum_choices = self.category.get_fields_annotation()
        Classification = create_model("Classification", **fields_annotation)
        llm = settings.LLM.with_structured_output(Classification)
        prompt = tagging_prompt.invoke({"input": self.ai_get_input()})
        try:
            response = dict(llm.invoke(prompt))
        except Exception as e:
            return {}, {"general": str(e)}

        for field, value in response.items():
            field_data = fields_annotation[field][1]
            is_optional = field_data.default is None
            field_enum_choices = fields_enum_choices.get(field, None)

            def clean_value(singular_value):
                if singular_value == "null" and is_optional:
                    return None, 100

                if isinstance(singular_value, str) and "\\" in singular_value:
                    decoded_singular_value = singular_value.encode().decode(
                        "unicode_escape"
                    )
                else:
                    decoded_singular_value = singular_value

                if (
                    decoded_singular_value
                    and field_enum_choices
                    and decoded_singular_value not in field_enum_choices
                ):
                    uppercase_field_enum_choices_dict = {
                        x: x.upper() for x in field_enum_choices
                    }
                    uppercase_best_match, score, best_match = (
                        rapidfuzz.process.extractOne(
                            decoded_singular_value.upper(),
                            uppercase_field_enum_choices_dict,
                        )
                    )
                    return best_match, score
                else:
                    return decoded_singular_value, 100

            if isinstance(value, list):
                cleaned_fields = []
                for value_entry in value:
                    cleaned_value, score = clean_value(value_entry)
                    if score >= 90:
                        cleaned_fields.append(cleaned_value)
                response[field] = cleaned_fields
            else:
                cleaned_value, score = clean_value(value)
                if score >= 90:
                    response[field] = cleaned_value
                else:
                    errors[field] = f"Choice not found: {value}"

        for key in errors.keys():
            if key != "general":
                del response[key]

        return response, errors

    def ai_create_product(self, inferred_product_data=None, ignore_errors=False):
        if not inferred_product_data:
            inferred_product_data, errors = self.ai_infer_product_data()
            if errors and not ignore_errors:
                raise Exception("The AI inferred product data has errors")

        meta_model = self.category.meta_model
        fields = meta_model.fields.all()
        instance = InstanceModel()
        instance.model = meta_model
        instance.save(initial=True)

        for field in fields:
            if field.name == "picture":
                continue

            field_name = field.name
            instance_value = inferred_product_data.get(field_name, None)

            if instance_value is None:
                continue

            if field.model.is_primitive():
                setattr(instance, field_name, instance_value)
            elif field.multiple:
                field_instances = field.model.instancemodel_set.filter(
                    unicode_representation__in=instance_value
                )
                setattr(instance, field_name, field_instances)
            elif instance_value:
                field_instance = field.model.instancemodel_set.get(
                    unicode_representation=instance_value
                )
                setattr(instance, field_name, field_instance)

        instance.picture = self.get_instance_model_picture()
        try:
            instance.save(creator_id=SoloTodoUser.get_bot().pk)
        except Exception as e:
            # Instance saving may fail if the ignore_errors flags is True but one of the fields with errors is used
            # to calculate important params of the associated product (its brand, for example)
            instance.delete()
            raise Exception(
                "Product could not be created due to errors in the inferred data"
            )

        product = Product.objects.get(instance_model=instance)
        return product

    def get_instance_model_picture(self):
        picture_urls = self.picture_urls_as_list()

        if not picture_urls:
            return self.DEFAULT_IMAGE

        extra_args = self.store.storescraper_extra_args_as_json()
        session = self.store.scraper.get_session(extra_args)
        try:
            response = session.get(picture_urls[0])
        except Exception:
            return self.DEFAULT_IMAGE

        if response.status_code != 200:
            return self.DEFAULT_IMAGE

        try:
            Image.open(io.BytesIO(response.content))
        except UnidentifiedImageError:
            return self.DEFAULT_IMAGE

        filename = f"products/{self.pk}"
        storage = MediaRootS3Boto3Storage()
        storage.save(filename, ContentFile(response.content))
        file_url = storage.url(filename)

        return file_url.split(f"{MediaRootS3Boto3Storage.location}/")[-1]

    def ai_find_similar_products(self, inferred_product_data=None):
        if not inferred_product_data:
            inferred_product_data, errors = self.ai_infer_product_data()
            if errors:
                errors_text = ", ".join(
                    [f"{key}: {value}" for key, value in errors.items()]
                )
                raise Exception(
                    "The AI inferred product data has errors: " + errors_text
                )

        retrieval_qa_chat_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "Answer any use questions based solely on the context below:\n\n<context>\n{context}\n</context>",
                ),
                ("human", "{input}"),
            ]
        )
        combine_docs_chain = create_stuff_documents_chain(
            settings.LLM, retrieval_qa_chat_prompt
        )
        retrieval_chain = create_retrieval_chain(
            settings.VECTOR_STORE.as_retriever(
                search_type="similarity",
                search_kwargs={
                    "k": 50,
                    "score_threshold": 0.5,
                    "filter": [
                        {"term": {"product_relationships": "product"}},
                        {"term": {"metadata.category_id": self.category_id}},
                    ],
                },
            ),
            combine_docs_chain,
        )

        prompt = f"""
        Return the information of up to five indexed products that match the product described the JSON at the end of this prompt based on its brand, commercial model and technical specifications.
        
        The results brand should be similar to {inferred_product_data['brand']}
        The results commercial model should be similar to {inferred_product_data['commercial_model']}
        
        {self.category.ai_additional_prompt_instructions_for_similarity_search or ''}
        
        The response must always be a valid json, with no additional commentaries or text
        The response must be in JSON format without backticks or other formatting, as an array of objects, each with the following keys:
        
        product_id: ID of the product.
        confidence: A number between 0 and 100 representing how confident you are that the product is of the same model as the queried one
        reasoning: The reason of your response        
        """

        query_product_dict = json.loads(self.ai_get_input())
        query_product_dict.update(inferred_product_data)

        response = retrieval_chain.invoke(
            {"input": f"{prompt} \n {json.dumps(query_product_dict)}"}
        )
        json_response = json.loads(response["answer"])

        result = []
        for entry in json_response:
            try:
                matching_product = Product.objects.get(pk=entry["product_id"])
            except Product.DoesNotExist:
                # AI hallucinates product IDs sometimes
                continue
            except ValueError:
                # AI hallucinates product IDs sometimes
                continue

            result.append(
                {
                    "product": matching_product,
                    "confidence": entry["confidence"],
                    "reasoning": entry["reasoning"],
                }
            )

        return result

    def ai_associate(self):
        result = self._ai_associate()
        self.ai_association_result = result
        self.save()
        return result

    def _ai_associate(self):
        if not self.is_visible:
            raise Exception("Entity has been marked as non-relevant")

        if not self.category.ai_confidence_threshold_for_association:
            raise Exception("Category not managed by AI")

        result = {
            "inferred_product_data": None,
            "similar_product_entries": None,
            "associated_product_id": None,
            "product_created": None,
            "errors": None,
        }

        inferred_product_data, errors = self.ai_infer_product_data()
        result["inferred_product_data"] = inferred_product_data
        if errors:
            result["errors"] = errors
            return result

        try:
            ai_similar_products_data = self.ai_find_similar_products(
                inferred_product_data
            )
        except Exception as e:
            result["errors"] = {"general": str(e)}
            return result

        serialized_ai_matching_product_data = [
            {
                "product_id": x["product"].id,
                "confidence": x["confidence"],
                "reasoning": x["reasoning"],
            }
            for x in ai_similar_products_data
        ]
        result["similar_product_entries"] = serialized_ai_matching_product_data

        if (
            ai_similar_products_data
            and ai_similar_products_data[0]["confidence"]
            >= self.category.ai_confidence_threshold_for_association
        ):
            self.associate(
                SoloTodoUser.get_bot(), ai_similar_products_data[0]["product"]
            )
            result["associated_product_id"] = ai_similar_products_data[0]["product"].id
            result["product_created"] = False
        else:
            product = self.ai_create_product(inferred_product_data)
            self.associate(SoloTodoUser.get_bot(), product)
            result["associated_product_id"] = product.id
            result["product_created"] = True
        return result

    def ai_update_category(self):
        if self.product_id:
            raise Exception(
                "Associated entities cannot change their category, please dissociate it first"
            )

        ai_category = self.ai_infer_category()

        if ai_category != self.category:
            self.category = ai_category
            self.save(update_fields=["category"])

    class Meta:
        app_label = "solotodo"
        ordering = ("creation_date",)
        unique_together = ("store", "key")
        permissions = [
            ("backend_list_entities", "Can view entity list in backend"),
            ("backend_view_entity_conflicts", "Can view entity conflicts in backend"),
            (
                "backend_view_entity_estimated_sales",
                "Can view the entity estimated sales interface in backend",
            ),
            (
                "backend_view_pending_entities",
                "Can view the pending entities interface in the backend",
            ),
        ]
