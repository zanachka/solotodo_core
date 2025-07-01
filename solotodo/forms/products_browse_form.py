from django import forms
from elasticsearch_dsl import Q

from solotodo.forms.base_products_browse_form import BaseProductsBrowseForm
from solotodo.forms.product_specs_form import ProductSpecsForm
from solotodo.models import Product, EsEntity


class ProductsBrowseForm(BaseProductsBrowseForm):
    ordering = forms.CharField(required=False)
    search = forms.CharField(required=False)

    ORDERING_CHOICES = {
        "offer_price_usd": {
            "script": "doc['offer_price_usd_with_coupon'].value",
            "direction": "asc",
            "score_mode": "min",
        },
        "normal_price_usd": {
            "script": "doc['normal_price_usd_with_coupon'].value",
            "direction": "asc",
            "score_mode": "min",
        },
        "price_per_unit": {
            "script": "doc['offer_price_usd_per_unit'].value",
            "direction": "asc",
            "score_mode": "min",
        },
        "leads": {
            "script": "doc['leads'].value",
            "direction": "desc",
            "score_mode": "sum",
        },
        # Discount and relevance are special cases that have their
        # parameters hardcoded
        "discount": {},
        "relevance": {},
    }

    COLLAPSE_SIZE = 5

    def clean_ordering(self):
        return self.cleaned_data["ordering"] or "offer_price_usd"

    def _get_specs_form(self, request, category=None):
        ordering = self.cleaned_data["ordering"]

        if category:
            # Create the sub form for the category-dependant specs
            specs_form_query = request.query_params.copy()
            # Determine whether we or the specs form will handle the sorting
            if ordering in self.ORDERING_CHOICES:
                # We will handle the sorting, remove the field from the specs
                # params, otherwise it will be detected as invalid
                specs_form_query.pop("ordering", None)
            else:
                # The specs form will handle the sorting, so set ours to None
                ordering = None

            specs_form_class = category.specs_form()
            specs_form = specs_form_class(specs_form_query)
        else:
            specs_form = ProductSpecsForm(request.query_params, user=self.user)
            assert ordering in self.ORDERING_CHOICES

        assert specs_form.is_valid()
        return specs_form

    def _customize_search(self, search, specs_form, entities_filter):
        all_specs_filter = specs_form.get_filter()
        ordering = self.cleaned_data["ordering"]

        if ordering == "discount":
            # Create a second search to determine the discount of each product.
            # As far as I know we can't do this calculation inside the main
            # query because it uses aggregations that can't be associated
            # with a particular product directly.

            discounts_search = (
                EsEntity.search()
                .filter(entities_filter)
                .filter("has_parent", parent_type="product", query=all_specs_filter)
            )

            discounts_search.aggs.bucket(
                "products", "terms", field="product_id", size=10000
            ).metric("min_price", "min", field="offer_price_usd").metric(
                "min_reference_price", "min", field="reference_offer_price_usd"
            ).pipeline(
                "discount",
                "bucket_script",
                buckets_path={
                    "min_price": "min_price",
                    "min_reference_price": "min_reference_price",
                },
                script="params.min_reference_price - params.min_price;",
            )

            discount_per_product_dict = {
                x["key"]: max(x["discount"]["value"], 0)
                for x in discounts_search[:0].execute().aggs.products.buckets
            }

            search = search.query(
                Q(
                    "script_score",
                    query=Q(),
                    script={
                        "params": discount_per_product_dict,
                        "source": """
                          if (params.containsKey(doc['product_id'].value.toString())) 
                              params.get(doc['product_id'].value.toString()); 
                          else 
                              0;
                          """,
                    },
                )
            )
            search = search.filter("has_child", type="entity", query=entities_filter)
            sort_params = {"_score": "desc"}
            keyword_search_type = "filter"
        elif ordering == "relevance":
            search = search.filter("has_child", type="entity", query=entities_filter)
            keyword_search_type = "query"
            sort_params = {"_score": "desc"}
        elif ordering:
            ordering_metadata = self.ORDERING_CHOICES[ordering]
            script_score = ordering_metadata["script"]

            # Create a query that gives the filtered entities a score
            # depending on our ordering choice. The filter query itself must be
            # a bool with an empty "must" field because otherwise ElasticSearch
            # won't even try and give it a score. Also the filters cannot be
            # in the "must" field because in that case they alter the
            # numeric value of the score, I don't know why.
            query = Q(
                "function_score",
                script_score={"script": script_score},
                query=Q("bool", filter=entities_filter, must=Q()),
            )
            search = search.query(
                "has_child",
                type="entity",
                query=query,
                score_mode=ordering_metadata["score_mode"],
            )

            sort_params = {"_score": ordering_metadata["direction"]}
            keyword_search_type = "filter"
        else:
            sort_params = specs_form.get_ordering()
            assert sort_params
            search = search.filter("has_child", type="entity", query=entities_filter)
            keyword_search_type = "filter"

        keywords = self.cleaned_data["search"]
        if keywords:
            if keyword_search_type == "filter":
                keywords_query = Product.query_es_by_search_string(keywords, mode="AND")
                search = search.filter(keywords_query)
            elif keyword_search_type == "query":
                keywords_query = Product.query_es_by_search_string(keywords, mode="OR")
                search = search.query(keywords_query)
            else:
                raise Exception("Invalid keyword_search_type")

        search = search.sort(sort_params)
        return search, sort_params
