# Base class for search engine adapter

class SearchEngineBase:
    def __init__(self, *args, **kwargs):
        pass

    def _add(self, documents, *args, **kwargs):
        pass

    def _search(self, query, n, *args, **kwargs):
        pass

    def add(self, documents, *args, **kwargs):
        return self._add(documents, *args, **kwargs)

    def search(self, query, n, *args, **kwargs):
        return self._search(query, n, *args, **kwargs)
