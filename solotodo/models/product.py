import json

import re

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.core.validators import validate_comma_separated_integer_list
from django.db import models, IntegrityError
from django.db.models import Q
from django.db.models.deletion import Collector
from django.utils.text import slugify
from langchain_core.prompts import ChatPromptTemplate
from sklearn.neighbors import NearestNeighbors

from metamodel.models import InstanceModel
from .es_product import EsProduct
from solotodo.signals import product_saved
from solotodo.models.utils import solotodo_com_site

from .category import Category
from .brand import Brand


class ProductQuerySet(models.QuerySet):
    def filter_by_category(self, category_or_categories):
        lookup = "instance_model__model__category"
        if hasattr(category_or_categories, "__iter__"):
            lookup += "__in"

        return self.filter(**{lookup: category_or_categories})

    def filter_by_availability_in_countries(self, countries):
        query = (
            Q(entity__active_registry__isnull=False)
            & ~Q(entity__active_registry__stock=0)
            & Q(entity__store__country__in=countries)
        )

        return self.filter(query).distinct()

    def filter_by_availability_in_stores(self, stores):
        query = (
            Q(entity__active_registry__isnull=False)
            & ~Q(entity__active_registry__stock=0)
            & Q(entity__store__in=stores)
        )

        return self.filter(query).distinct()

    def filter_by_search_string(self, search):
        es_search = EsProduct.search()
        # es_search = es_search.filter('terms', product_id=[p.id for p in self])
        q = Product.query_es_by_search_string(search, mode="AND")
        es_search = es_search.filter(q)

        matching_product_ids = [
            r.product_id for r in es_search[: self.count()].execute()
        ]
        return self.filter(pk__in=matching_product_ids)

    def filter_by_name(self, search):
        es_search = EsProduct.search()
        q = Product.query_es_by_name(search, mode="AND")
        es_search = es_search.filter(q)

        matching_product_ids = [
            r.product_id for r in es_search[: self.count()].execute()
        ]
        return self.filter(pk__in=matching_product_ids)

    def filter_by_user_perms(self, user, permission):
        synth_permissions = {"view_product": "view_category"}

        assert permission in synth_permissions

        return self.filter_by_category(
            Category.objects.filter_by_user_perms(user, synth_permissions[permission])
        )

    def update(self, *args, **kwargs):
        raise Exception(
            "Queryset level update is disabled on Product as it "
            "does not call save() or emit pre_save / post_save "
            "signals"
        )

    def delete(self):
        raise Exception(
            "Delete should not be called on product querysets, "
            "delete the associated instance models instead"
        )


class Product(models.Model):
    instance_model = models.ForeignKey(InstanceModel, on_delete=models.CASCADE)
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT)
    part_number = models.CharField(max_length=255, blank=True, null=True)
    sec_qr_codes = models.CharField(
        validators=[validate_comma_separated_integer_list],
        null=True,
        blank=True,
        max_length=255,
    )
    creation_date = models.DateTimeField(db_index=True, auto_now_add=True)
    creator = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
    last_updated = models.DateTimeField(auto_now=True)

    objects = ProductQuerySet.as_manager()

    category = property(lambda self: self.instance_model.model.category)
    category_id = property(lambda self: self.instance_model.model.category.id)
    name = property(lambda self: str(self.instance_model))

    @property
    def ai_description(self):
        raw_ai_description = EsProduct.get_by_product_id(self.pk).summary_text

        if raw_ai_description:
            return json.loads(raw_ai_description)["description"]
        else:
            return None

    def __init__(self, *args, **kwargs):
        self._es_entry = None
        super(Product, self).__init__(*args, **kwargs)

    @property
    def category(self):
        return self.instance_model.model.category

    @property
    def es_entry(self):
        if not self._es_entry:
            self._es_entry = EsProduct.get("PRODUCT_" + str(self.id)).to_dict()
        return self._es_entry

    @property
    def specs(self):
        if not self._es_entry:
            self._es_entry = EsProduct.get("PRODUCT_" + str(self.id)).to_dict()
        return self._es_entry["specs"]

    @property
    def ai_specs(self):
        specs = {"product_id": self.pk, "category": self.category.name}

        for field in self.instance_model.fields.all():
            field_type = field.field.model.name
            field_name = field.field.name
            field_value = field.value

            if field_type == "FileField":
                continue

            if field_type == "DecimalField":
                specs[field_name] = float(field_value.decimal_value)
            elif field_type == "BooleanField":
                specs[field_name] = "Yes" if field_value.decimal_value else "No"
            else:
                specs[field_name] = (
                    field_value.unicode_representation
                    or field_value.unicode_value
                    or int(field_value.decimal_value)
                )

        return specs

    @property
    def keywords(self):
        if not self._es_entry:
            self._es_entry = (
                EsProduct.search()
                .filter("term", product_id=self.id)
                .execute()[0]
                .to_dict()
            )
        return self._es_entry["keywords"]

    @property
    def picture_url(self):
        if "picture" in self.specs:
            return default_storage.url(self.specs["picture"])
        return None

    @property
    def slug(self):
        return slugify(str(self))

    def __str__(self):
        return str(self.instance_model)

    @classmethod
    def prefetch_specs(cls, products):
        product_ids = [p.id for p in products]

        search = EsProduct.search().filter("terms", product_id=product_ids)[
            : len(product_ids)
        ]
        response = search.execute().to_dict()
        es_dict = {
            e["_source"]["product_id"]: e["_source"] for e in response["hits"]["hits"]
        }

        for product in products:
            product._es_entry = es_dict[product.id]

    def user_has_staff_perms(self, user):
        return user.has_perm("is_category_staff", self.category)

    def solotodo_com_url(self):
        site = solotodo_com_site()
        return "https://{}/products/{}-{}".format(
            site.domain, self.id, slugify(str(self))
        )

    def save(self, *args, **kwargs):
        creator_id = kwargs.pop("creator_id", None)

        if bool(creator_id) == bool(self.id):
            raise IntegrityError(
                "Exiting products cannot have a creator " "(and vice versa)"
            )

        es_document = self.instance_model.elasticsearch_document()

        self.brand = Brand.objects.get_or_create(name=es_document[0]["brand_unicode"])[
            0
        ]

        part_number = es_document[0].get("part_number", "") or ""

        if part_number:
            self.part_number = part_number.strip()
        else:
            self.part_number = None

        sec_qr_codes = es_document[0].get("sec_qr_codes", "")
        if sec_qr_codes:
            self.sec_qr_codes = sec_qr_codes.strip()
        else:
            self.sec_qr_codes = None

        if creator_id:
            self.creator_id = creator_id

        super(Product, self).save(*args, **kwargs)

        product_saved.send(sender=self.__class__, product=self, es_document=es_document)

    def delete(self, *args, **kwargs):
        raise Exception(
            "Delete should not be called on product instances, "
            "delete the associated instance model instead"
        )

    def search_bucket_key(self, es_document):
        bucket_fields = self.category.search_bucket_key_fields
        if bucket_fields:
            return ",".join(
                [str(es_document[field.strip()]) for field in bucket_fields.split(",")]
            )
        else:
            return ""

    def bucket(self, fields):
        product_specs = self.specs
        search = EsProduct.category_search(self.category)

        for field in fields:
            field_value = product_specs.get(field)
            if isinstance(field_value, str):
                query_type = "match_phrase"
            else:
                query_type = "term"

            search = search.filter(query_type, **{"specs." + field: field_value})

        es_products_dict = {
            es_product.product_id: es_product.to_dict()
            for es_product in search[:100].execute()
        }

        bucket_products = Product.objects.filter(
            pk__in=es_products_dict.keys()
        ).select_related("instance_model__model__category")

        for product in bucket_products:
            product._es_entry = es_products_dict[product.id]

        return bucket_products

    @staticmethod
    def query_es_by_search_string(search, mode="OR"):
        from elasticsearch_dsl import Q

        search = search.strip()

        if not search:
            return Q()

        search_terms = [term.lower() for term in re.split(r"\W+", search)]
        search_query = None
        for search_term in search_terms:
            keywords_term_query = Q("wildcard", keywords="*{}*".format(search_term))
            name_term_query = Q(
                "wildcard",
                name_analyzed={"value": "*{}*".format(search_term), "boost": 3.0},
            )

            if search_query:
                if mode == "OR":
                    search_query |= keywords_term_query
                    search_query |= name_term_query
                else:
                    search_query &= keywords_term_query
            else:
                search_query = keywords_term_query
                if mode == "OR":
                    search_query |= name_term_query

        return search_query

    @staticmethod
    def query_es_by_name(search, mode="OR"):
        from elasticsearch_dsl import Q

        search = search.strip()

        if not search:
            return Q()

        search_terms = [term.lower() for term in re.split(r"\W+", search)]
        search_query = None
        for search_term in search_terms:
            name_term_query = Q("wildcard", name_analyzed="*{}*".format(search_term))

            if search_query:
                if mode == "OR":
                    search_query |= name_term_query
                else:
                    search_query &= name_term_query
            else:
                search_query = name_term_query

        return search_query

    def videos(self):
        from solotodo.models import ProductVideo

        specs = self.specs
        videos = ProductVideo.objects.all()
        selected_videos = []

        for video in videos:
            conditions = json.loads(video.conditions)
            include_video = True

            for key, value in conditions.items():
                if specs.get(key) not in value:
                    include_video = False
                    break

            if include_video:
                selected_videos.append(video)

        return selected_videos

    @classmethod
    def find_similar_products(
        cls,
        query_products,
        stores=None,
        brands=None,
        initial_candidate_entities=None,
        results_per_product=5,
    ):
        from solotodo.models import Entity

        if not query_products:
            return []

        category = query_products[0].category

        # Get the candidates

        if not initial_candidate_entities:
            initial_candidate_entities = Entity.objects.all()

        candidates_query = (
            initial_candidate_entities.filter(
                product__isnull=False, product__instance_model__model__category=category
            )
            .order_by()
            .get_available()
            .distinct("product")
            .select_related("product")
        )

        if stores is not None:
            candidates_query = candidates_query.filter(store__in=stores)

        candidates = []

        product_ids = [e.product_id for e in candidates_query]
        es_brand_products = EsProduct.category_search(category).filter(
            "terms", product_id=product_ids
        )

        if brands is not None:
            es_brand_products = es_brand_products.filter(
                "terms", specs__brand_unicode=brands
            )

        es_results_dict = {e.product_id: e.to_dict() for e in es_brand_products.scan()}

        for entity in candidates_query:
            product = entity.product
            candidate_specs = es_results_dict.get(entity.product_id)
            if not candidate_specs:
                continue
            product._es_entry = candidate_specs
            candidates.append(product)

        # Obtain the (field_name, weight) pairs
        fields_metadata = []
        for field_with_weight in category.similar_products_fields.split(","):
            field_with_weight = field_with_weight.strip()

            if "**" in field_with_weight:
                field, weight_factor = field_with_weight.split("**")
                weight = 1.0 + float(weight_factor) / 10
            else:
                field = field_with_weight
                weight = 1.0

            fields_metadata.append(
                {
                    "field": field,
                    "weight": weight,
                    "min": Decimal("Inf"),
                    "max": Decimal("-Inf"),
                }
            )

        def attr_getter(x, field_name):
            field_value = x.get(field_name, 0)

            if field_value is None:
                return 0
            return float(field_value)

        def field_normalizer(data_entry):
            result = []
            for idx, field_value in enumerate(data_entry):
                if fields_metadata[idx]["min"] == fields_metadata[idx]["max"]:
                    entry_value = 0
                else:
                    entry_value = float(field_value - fields_metadata[idx]["min"]) / (
                        fields_metadata[idx]["max"] - fields_metadata[idx]["min"]
                    )
                    entry_value /= fields_metadata[idx]["weight"]
                result.append(entry_value)
            return result

        candidate_entries = []
        for candidate in candidates:
            candidate_entry = []

            for entry in fields_metadata:
                field_value = attr_getter(candidate.specs, entry["field"])

                if field_value < entry["min"]:
                    entry["min"] = field_value

                if field_value > entry["max"]:
                    entry["max"] = field_value

                candidate_entry.append(field_value)

            candidate_entries.append(candidate_entry)

        candidate_entries = [field_normalizer(entry) for entry in candidate_entries]

        if candidate_entries:
            n_neighbors = results_per_product + 1
            if n_neighbors > len(candidate_entries):
                n_neighbors = len(candidate_entries)

            neighbors = NearestNeighbors(n_neighbors=n_neighbors).fit(candidate_entries)

            query_entries = []
            for query_product in query_products:
                query_product_specs = query_product.specs
                query_product_entry = [
                    attr_getter(query_product_specs, entry["field"])
                    for entry in fields_metadata
                ]
                query_entries.append(field_normalizer(query_product_entry))

            distances, indices = neighbors.kneighbors(query_entries)
        else:
            distances = [[]] * len(query_products)
            indices = [[]] * len(query_products)

        result = []
        for idx, query_product in enumerate(query_products):
            similar_products = []

            for i in range(len(indices[idx])):
                candidate = candidates[indices[idx][i]]

                if candidate != query_product:
                    similar_products.append(
                        {
                            "product": candidates[indices[idx][i]],
                            "distance": distances[idx][i],
                        }
                    )

            result.append({"product": query_product, "similar": similar_products})

        return result

    def find_similar(
        self,
        stores=None,
        brands=None,
        initial_candidate_entities=None,
        results_per_product=5,
    ):
        return self.find_similar_products(
            [self],
            stores=stores,
            brands=brands,
            initial_candidate_entities=initial_candidate_entities,
            results_per_product=results_per_product,
        )[0]

    def fuse(self, target_product):
        from .entity import Entity

        # Transfers all related objects that point to this product to the
        # target, then deletes self

        self.productpricealert_set.update(product=target_product)
        self.product_1.update(product_1=target_product)
        self.product_2.update(product_2=target_product)
        self.budgetentry_set.update(selected_product=target_product)

        for budget in self.budget_set.all():
            budget.products_pool.add(target_product)

        self.micrositeentry_set.update(product=target_product)

        for e in self.entity_set.all():
            e.category = target_product.category
            e.product = target_product
            e.save()

        for e in Entity.objects.filter(cell_plan=self):
            e.cell_plan = target_product
            e.save()

        self.pictures.update(product=target_product)
        self.entitylog_set.update(product=target_product)
        self.rating_set.update(product=target_product)
        self.visit_set.update(product=target_product)
        self.wtbentity_set.update(product=target_product)
        collector = Collector(using="default")
        im = self.instance_model
        collector.collect([im])
        # Make sure we only are going to delete the instance model and
        # related product
        assert len(collector.data) == 2
        im.delete()

    @classmethod
    def pending_field_values(cls):
        from elasticsearch_dsl import Q as ES_Q
        from .product_field_watcher import ProductFieldWatcher

        base_search = EsProduct.search().filter(
            "has_child", type="entity", query=ES_Q("match_all")
        )
        watchers = ProductFieldWatcher.objects.all()
        result = []
        for watcher in watchers:
            search = base_search.filter("term", category_id=watcher.category_id)
            search = search.filter(
                "term", **{"specs." + watcher.es_value_path: watcher.es_target_value}
            )
            subresult = {}
            for search_result in search.scan():
                result_dict = search_result.to_dict()
                subresult[result_dict["specs"][watcher.es_instance_model_id_path]] = (
                    result_dict["specs"][watcher.es_label_path]
                )

            pending_fields = [
                {"id": key, "label": value}
                for key, value in sorted(
                    subresult.items(), key=lambda x: x[0], reverse=True
                )
            ]

            result.append({"label": watcher.name, "pending_fields": pending_fields})
        return result

    def ai_generate_description(self):
        from django.conf import settings

        tagging_prompt = ChatPromptTemplate.from_template(
            """
            Eres un generador de descripciones de productos para un sitio de comparación de precios. 
            A partir del siguiente input, escribe una descripción clara, imparcial, informativa, neutral y bien estructurada 
            del producto descrito en formato Markdown.

## Instrucciones:
- Destaca las características del producto.
- Incluye una lista con al menos 3 características principales.
- Usa encabezados y formato Markdown para estructurar el contenido.
- No incluyas imagenes o tablas
- La ficha va ser usada para el mercado de Chile, asume que el producto va a ser utilizado en ese país
- No es necesario incluir información de compatibilidad eléctrica

## Input del usuario:

{input}

## Output esperado (en formato Markdown):

[Descripción general del producto, en formato markdown, destacando en negrita sus cualidades principales]

## Características destacadas

- [Característica 1]
- [Característica 2]
...
- [Característica n]

## Pros

- [Pro 1]
- [Pro 2]
...
- [Pro n]

## Contras

- [Contra 1]
- [Contra 2]
...
- [Contra n]
            """
        )

        descriptions = [
            e.description for e in self.entity_set.filter(description__isnull=False)
        ]
        prompt_input = json.dumps(self.ai_specs) + "\n\n" + "\n\n".join(descriptions)

        prompt = tagging_prompt.invoke({"input": prompt_input})
        seo_description = settings.LLMS["gpt-4.1-mini"].invoke(prompt)

        return seo_description.content

    def ai_generate_meta_tag_description(self):
        from django.conf import settings

        tagging_prompt = ChatPromptTemplate.from_template(
            """
            Toma la siguiente descripción larga de un producto y genera una meta descripción en español de máximo 
            160 caracteres. La descripción debe ser clara, concisa, y destacar el tipo de producto y sus características 
            clave. No incluyas comillas. Esta descripción será usada como meta tag "description" en una página de comparación de precios.

Descripción del producto:
{input}
            """
        )

        descriptions = [
            e.description for e in self.entity_set.filter(description__isnull=False)
        ]
        joined_descriptions = (
            json.dumps(self.ai_specs) + "\n\n" + "\n\n".join(descriptions)
        )

        prompt = tagging_prompt.invoke({"input": joined_descriptions})
        seo_description = settings.LLMS["gpt-4.1-mini"].invoke(prompt)

        return seo_description.content

    def ai_generate_keywords(self):
        from django.conf import settings

        tagging_prompt = ChatPromptTemplate.from_template(
            """
            A partir de la siguiente descripción de producto, genera una lista de palabras clave relevantes que 
            serán usadas para búsqueda por keywords dentro de un sitio web. Incluye tanto los términos explícitamente 
            mencionados como sinónimos (por ejemplo si aparece "juegos" incluye 
            tambien "gamer" y "gaming"). Separa cada keyword con coma. Sólo retorna el texto final, sin comentarios.

Descripción del producto:
{input}

Ejemplo de salida:
palabra1, palabra2, sinónimo1, sinónimo2, palabra relacionada1, etc.
            """
        )

        # self.es_entry may be cached, so get a fresh instance of the related EsProduct
        es_product = EsProduct.get_by_product_id(self.pk)
        joined_descriptions = (
            f"{json.dumps(self.ai_specs)}\n{es_product.ai_description}"
        )

        prompt = tagging_prompt.invoke({"input": joined_descriptions})
        keywords = settings.LLMS["gpt-4.1-mini"].invoke(prompt).content
        keywords += f", {str(self)}, {self.id}, {self.instance_model_id}"

        for instance_field in self.instance_model.fields.all():
            if not instance_field.field.model.is_primitive():
                keywords += f", {instance_field.value}"

        return keywords

    def update_ai_fields(self, fields=None):
        # If the product is a Grocery dont generate AI fields for it
        # TODO: improve this so that it is not hardcoded
        if self.category_id == 549:
            return

        ai_description = None
        ai_meta_tag_description = None
        keywords = None

        if fields is None or "ai_description" in fields:
            ai_description = self.ai_generate_description()
        if fields is None or "ai_meta_tag_description" in fields:
            ai_meta_tag_description = self.ai_generate_meta_tag_description()
        if fields is None or "keywords" in fields:
            keywords = self.ai_generate_keywords()

        # Fetch and update the ElasticSearch document as late as possible to prevent conflicts between the moment
        # the document is fetched and when it is saved, for example when creating and editing a cloned product

        es_product = EsProduct.get_by_product_id(self.pk)
        if ai_description:
            es_product.ai_description = ai_description
        if ai_meta_tag_description:
            es_product.ai_meta_tag_description = ai_meta_tag_description
        if keywords:
            es_product.keywords = keywords

        es_product.save()

    class Meta:
        app_label = "solotodo"
        ordering = ("instance_model",)
        permissions = [
            ("backend_list_products", "Can view product list in backend"),
        ]
