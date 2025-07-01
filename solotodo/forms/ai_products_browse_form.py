import json

from enum import Enum
from typing import Optional, List

from django import forms
from django.conf import settings
from elasticsearch_dsl import Q
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from pydantic import BaseModel

from solotodo.forms.base_products_browse_form import BaseProductsBrowseForm


class QueryAnalysis(BaseModel):
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    query_without_price: str


class AIProductsBrowseForm(BaseProductsBrowseForm):
    search = forms.CharField(required=False)

    def _preprocess_query(self):
        assert self.is_valid()
        tagging_prompt = ChatPromptTemplate.from_template(
            """
Analyze this product search query and extract the product category, price bounds, and clean query.

Query: "{input}"

Instructions:
1. Extract price bounds if mentioned:
   - Maximum price: "under $500", "below 1000", "less than €800", "max $600"
   - Minimum price: "over $200", "above 300", "more than €150", "at least $400"
   - Price range: "between $200 and $500", "$300-$800", "from 400 to 1000"
2. Convert prices to numeric values without currency symbols
3. Remove all price-related phrases from the original query to create query_without_price
4. If no price bounds are mentioned, leave min_price and max_price as null

Examples:
- "washing machine under $800" → category: "washing machine", max_price: 800, min_price: null, query_without_price: "washing machine"
- "energy efficient refrigerator over $500" → category: "refrigerator", min_price: 500, max_price: null, query_without_price: "energy efficient refrigerator"
- "laptop between $600 and $1200 for students" → category: "laptop", min_price: 600, max_price: 1200, query_without_price: "laptop for students"
- "dishwasher for small apartment" → category: "dishwasher", min_price: null, max_price: null, query_without_price: "dishwasher for small apartment"
"""
        )

        llm = settings.LLM.with_structured_output(QueryAnalysis)
        prompt = tagging_prompt.invoke({"input": self.cleaned_data["search"]})
        response = dict(llm.invoke(prompt))

        return response

    def _customize_search(self, search, specs_form, entities_filter):
        assert self.is_valid()
        preprocessed_query = self._preprocess_query()
        processed_search = preprocessed_query["query_without_price"]

        query_vector = settings.VECTOR_STORE.embedding.embed_documents(
            [processed_search]
        )[0]

        # Create vector similarity query
        vector_query = Q(
            "script_score",
            query=Q("match_all"),
            script={
                "source": "cosineSimilarity(params.query_vector, 'search_vector') + 1.0",
                "params": {"query_vector": query_vector},
            },
        )

        # Create keyword search query
        keyword_query = Q(
            "multi_match",
            query=preprocessed_query,
            fields=["name^2", "ai_description", "category_name^1.5"],
            type="best_fields",
        )

        # Combine queries using bool should
        # shoulds = [vector_query, keyword_query]
        shoulds = [vector_query]
        combined_query = Q("bool", should=shoulds, minimum_should_match=1)

        # Apply filters
        filters = [Q("exists", field="search_vector")]

        # Category filter
        # if category:
        #     filters.append(Q("term", category_id=category.id))

        # Price range filters
        # if min_price is not None or max_price is not None:
        #     price_range = {}
        #     if min_price is not None:
        #         price_range["gte"] = min_price
        #     if max_price is not None:
        #         price_range["lte"] = max_price
        #     filters.append(Q("range", price=price_range))

        # Apply filters to the query
        if filters:
            combined_query = Q("bool", must=combined_query, filter=filters)

        # Execute search
        search = search.query(combined_query).extra(
            size=2 * self.cleaned_data["page_size"]
        )

        documents = [Document(x.text) for x in search.iterate()]

        # Prepare context for LLM
        context = "\n\n".join([doc.page_content for doc in documents])

        search_prompt = ChatPromptTemplate.from_template(
            """
        You are a product search assistant for a price comparison website. Based on the user's query and the retrieved product information, provide helpful product recommendations.

        User Query: {query}

        Retrieved Products:
        {context}

        Instructions:
        1. Analyze the user's requirements from their natural language query
        2. Match products based on specifications, features, and suitability
        3. Rank products by relevance to the user's needs
        4. Provide clear explanations for why each product matches
        5. Consider factors like capacity, size, efficiency, price range, and brand reputation
        6. Focus on the most relevant specifications for the product category

        Provide your response in the following format:
        **Recommended Products:**

        For each recommended product, include:
        - Product name and key specifications
        - Why it matches the user's requirements
        - Price information
        - Any important considerations

        Keep responses concise but informative.
        """
        )

        # Generate response using RAG
        chain = (
            {"query": RunnablePassthrough(), "context": RunnablePassthrough()}
            | search_prompt
            | settings.LLM
            | StrOutputParser()
        )

        response = chain.invoke(
            {"query": preprocessed_query["query_without_price"], "context": context}
        )

        import ipdb

        ipdb.set_trace()

        return search, {"_score": "desc"}
