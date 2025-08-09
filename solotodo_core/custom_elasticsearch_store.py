from typing import Optional, List, Callable, Dict, Any

from langchain_core.documents import Document
from langchain_elasticsearch import ElasticsearchStore
from langchain_elasticsearch._utilities import _hits_to_docs_scores


class CustomElasticseachStore(ElasticsearchStore):
    def similarity_search(
        self,
        query: str,
        k: int = 4,
        fetch_k: int = 50,
        filter: Optional[List[dict]] = None,
        *,
        custom_query: Optional[
            Callable[[Dict[str, Any], Optional[str]], Dict[str, Any]]
        ] = None,
        doc_builder: Optional[Callable[[Dict], Document]] = None,
        **kwargs: Any,
    ) -> List[Document]:
        # Override the base similarity_search to overwrite the query with our own that may be sent in vector_store_query
        hits = self._store.search(
            query=kwargs.get("vector_store_query", query),
            k=k,
            num_candidates=fetch_k,
            filter=filter,
            custom_query=custom_query,
        )
        docs = _hits_to_docs_scores(
            hits=hits,
            content_field=self.query_field,
            doc_builder=doc_builder,
        )
        return [doc for doc, _score in docs]
