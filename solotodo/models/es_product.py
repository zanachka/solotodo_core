import json
from elasticsearch_dsl import (
    Text,
    Keyword,
    Object,
    Integer,
    Date,
    DenseVector,
    analyzer,
)
from .es_product_entities import EsProductEntities

from django.conf import settings


html_strip = analyzer(
    "html_strip",
    tokenizer="standard",
    filter=["lowercase", "stop", "snowball"],
    char_filter=["html_strip"],
)


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

    ai_description = Text(fields={"keyword": Keyword()})
    ai_meta_tag_description = Text(fields={"keyword": Keyword()})

    metadata = Object(
        dynamic=True, properties={"source": Text(fields={"keyword": Keyword()})}
    )
    description = Text(analyzer=html_strip)

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
    def from_product(cls, product, es_document=None):
        if not es_document:
            es_document = product.instance_model.elasticsearch_document()

        specs, keywords, related_instance_model_ids = es_document

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

        description = "\n".join(
            [f"{key}: {value}" for key, value in document_content.items()]
        )
        for entity in product.entity_set.filter(description__isnull=False):
            description += "\n" + entity.description

        vector = settings.VECTOR_STORE.embedding.embed_documents([specs_content])[0]

        metadata = {
            "id": product.id,
            "category_id": product.category_id,
        }

        return cls(
            product_id=product.id,
            name=str(product),
            name_analyzed=str(product),
            category_id=product.category_id,
            category_name=str(product.category),
            brand_id=product.brand_id,
            brand_name=str(product.brand),
            part_number=product.part_number,
            instance_model_id=product.instance_model_id,
            creation_date=product.creation_date,
            last_updated=product.last_updated,
            keywords=" ".join(keywords),
            specs=specs,
            related_instance_model_ids=related_instance_model_ids,
            product_relationships="product",
            meta={"id": "PRODUCT_{}".format(product.id)},
            text=specs_content,
            vector=vector,
            metadata=metadata,
            description=description,
        )
