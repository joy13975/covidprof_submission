# Search indexing adaptor using tantivy
# Source: https://github.com/tantivy-search/tantivy-py
import os

import tantivy

from base.search_engine import SearchEngineBase


class TantivyAdapter(SearchEngineBase):
    def __init__(self,
                 index_path='tantivy_index',
                 fields=[
                     ('id', True),
                     ('title', True),
                     ('authors', True),
                     ('publishTime', True),
                     ('abstract', True),
                     ('body', True)]
                 ):
        schema_builder = tantivy.SchemaBuilder()
        for field, stored in fields:
            schema_builder.add_text_field(field, stored=stored)
        self.schema = schema_builder.build()
        if not os.path.exists(index_path):
            os.mkdir(index_path)
        self.index = tantivy.Index(self.schema, index_path)

    def _add(self, documents):
        writer = self.index.writer()
        if isinstance(documents, dict):
            documents = [documents]
        for doc in documents:
            writer.add_document(tantivy.Document(**doc))
        writer.commit()

    def _search(self, query, n=3, target_fields=['title', 'abstract', 'body']):
        # Reload the index to ensure it points to the last commit.
        self.index.reload()
        searcher = self.index.searcher()
        query = self.index.parse_query(query, target_fields)
        search_result = searcher.search(query, limit=n)
        return [searcher.doc(doc_addr) for _, doc_addr in search_result.hits]
