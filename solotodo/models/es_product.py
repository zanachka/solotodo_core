import json
from elasticsearch_dsl import Text, Keyword, Object, Integer, Date, DenseVector
from .es_product_entities import EsProductEntities

from django.conf import settings


class EsProduct(EsProductEntities):
    product_id = Integer()
    name = Keyword()
    name_analyzed = Text()
    category_id = Integer()
    category_name = Keyword()
    brand_id = Integer()
    brand_name = Keyword()
    part_number = Keyword()
    instance_model_id = Integer()
    creation_date = Date()
    last_updated = Date()
    keywords = Text()
    specs = Object(dynamic=True)
    related_instance_model_ids = Integer(multi=True)

    # Fields used by the vector store that finds similar products
    # The "text" fields doesn't seem to be used anywhere
    text = Text(fields={"keyword": Keyword()})
    vector = DenseVector(
        dims=3072,
        index=True,
        similarity="cosine",
        index_options={"type": "int8_hnsw", "m": 16, "ef_construction": 100},
    )

    ai_description = Text()
    ai_meta_tag_description = Text()

    metadata = Object(
        dynamic=True, properties={"source": Text(fields={"keyword": Keyword()})}
    )

    @classmethod
    def search(cls, **kwargs):
        return cls._index.search(**kwargs).filter(
            "term", product_relationships="product"
        )

    @classmethod
    def category_search(cls, category, **kwargs):
        return cls.search(**kwargs).filter("term", category_id=category.id)

    @classmethod
    def get_by_product_id(cls, product_id):
        return cls.get("PRODUCT_{}".format(product_id))

    @classmethod
    def from_product(cls, product, es_document=None, elasticsearch_document=None):
        if not es_document:
            es_document = product.instance_model.elasticsearch_document()

        specs, related_instance_model_ids = es_document

        if "default_bucket" not in specs:
            specs["default_bucket"] = specs["id"]

        # Vector fields
        document_content = {"id": product.id, "product_name": str(product)}
        for instance_field in product.instance_model.fields.select_related("field"):
            if instance_field.field.model.name == "FileField":
                continue
            base_field_name = instance_field.field.name
            field_value_candidate_1 = specs.get(base_field_name, None)
            field_value_candidate_2 = specs.get(f"{base_field_name}_unicode", None)
            document_content[base_field_name] = (
                field_value_candidate_1 or field_value_candidate_2
            )
        specs_content = json.dumps(document_content, sort_keys=True)

        vector = settings.VECTOR_STORE.embedding.embed_documents([specs_content])[0]

        metadata = {
            "id": product.id,
            "category_id": product.category_id,
        }

        if not elasticsearch_document:
            elasticsearch_document = cls(meta={"id": "PRODUCT_{}".format(product.id)})

        elasticsearch_document.product_id = product.id
        elasticsearch_document.name = str(product)
        elasticsearch_document.name_analyzed = str(product)
        elasticsearch_document.category_id = product.category_id
        elasticsearch_document.category_name = str(product.category)
        elasticsearch_document.brand_id = product.brand_id
        elasticsearch_document.brand_name = str(product.brand)
        elasticsearch_document.part_number = str(product.part_number)
        elasticsearch_document.instance_model_id = product.instance_model_id
        elasticsearch_document.creation_date = product.creation_date
        elasticsearch_document.last_updated = product.last_updated
        elasticsearch_document.specs = specs
        elasticsearch_document.keywords = specs_content
        elasticsearch_document.related_instance_model_ids = related_instance_model_ids
        elasticsearch_document.product_relationships = "product"
        elasticsearch_document.vector = vector
        elasticsearch_document.metadata = metadata

        return elasticsearch_document
