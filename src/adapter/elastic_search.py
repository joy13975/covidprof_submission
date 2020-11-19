from datetime import datetime
from elasticsearch_dsl import Document, Keyword, Text, Date, connections
from elasticsearch_dsl.query import MultiMatch

from .base.search_engine import SearchEngineBase

# define a default article mapping


class DefaultArticleMapping(Document):
    title = Text(analyzer='snowball')
    authors = Text()
    publishTime = Date()
    abstract = Text(analyzer='snowball')
    body = Text(analyzer='snowball')

    class Index:
        name = "covidprof"
        # set settings and possibly other attributes of the index like
        # analyzers
        settings = {"number_of_shards": 1, "number_of_replicas": 0}


class ElasticSearchAdapter(SearchEngineBase):
    def __init__(self, mapping=DefaultArticleMapping):
        # establish a persistent elasticsearch connection
        connections.create_connection()
        # set the mapping as an instance attribute, for use in the _add method
        self.mapping = mapping
        # push the mapping template to elasticsearch and initialize the index
        self.mapping.init()

    def _add(self, documents):
        if isinstance(documents, dict):
            documents = [documents]
        for doc in documents:
            doc_without_id = {k: v for (k, v) in doc.items() if k != "id"}
            # convert publishTime from string to datetime if it exists
            if doc_without_id['publishTime'] != '':
                doc_without_id['publishTime'] = datetime.strptime(doc_without_id['publishTime'], '%Y-%m-%dT%H:%M:%S')
            else:
                doc_without_id['publishTime'] = None
            
            # save the doc
            self.mapping(meta={'id': doc['id']}, **doc_without_id).save()

        # refresh index to make changes live
        self.mapping._index.refresh()

    def _search(self, query, n, target_fields=['body', 'abstract'],
                frag_size=500, n_frags=3):
        # target_fields is in order of importance!!
        s = self.mapping.search()
        s.query = MultiMatch(
            query=query,
            fields=target_fields,
        )
        for f in target_fields:
            s = s.highlight(f, pre_tags='', post_tags='',
                            fragment_size=frag_size,
                            number_of_fragments=n_frags)
        s = s.sort(
            {'_score': {'order': 'desc'}},
            {'publishTime': {'order': 'desc'}},
        )
        return s[:n].execute()

    @classmethod
    def get_highlight_frags(cls, doc, fields=['body', 'abstract']):
        '''Extract highlighted fragments'''
        for field in fields:
            if field in doc.meta.highlight:
                return '\n\n'.join(doc.meta.highlight[field])
