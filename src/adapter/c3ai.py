# Data adapter for C3.ai Data Lake
# API Doc:
# https://c3.ai/covid-19-api-documentation/
import requests
from time import sleep
import json
import logging
from multiprocessing.pool import ThreadPool


class RequestException(Exception):
    pass


class C3aiAdapter:
    limits = {
        'biblioentry': 2000,
        'populationdata': 2000,
        'labordetail': 2000,
        'linelistrecord': 5000,
        'sequence': 8000,
        'subsequence': 8000,
        'biologicalasset': 8000,
    }

    @classmethod
    def request(cls, typename, api, body, max_retries=10, retry_wait=1):
        '''
        Sends HTTP Post request to C3ai's data lake API.
        Retry on server error.
        '''
        for nth_retry in range(1, max_retries+1):
            try:
                response = requests.post(
                    'https://api.c3.ai/covid/api/1/' + typename + '/' + api,
                    json=body,
                    headers={
                        'Accept': 'application/json',
                        'Content-Type': 'application/json'
                    })
            except Exception as e:
                if 'Temporary failure in name resolution' in str(e):
                    logging.error(f'Request to {typename}/{api} resulted in error  '
                                f'{e}; '
                                f'retrying in {retry_wait}s '
                                f'({nth_retry}/{max_retries})')
                    sleep(retry_wait)
                    continue
            if response.status_code == 200:
                # Successful request
                return response.json()
            elif (500 <= response.status_code < 600) or \
                    'too many requests' in repr(response).lower():
                # Retry on server error or congestion
                if nth_retry >= max_retries:
                    # raise RequestException(repr(response))
                    response
                    return {
                        'error': f'Max request {max_retries} retries reached.',
                        'content': json.loads(response.content)
                    }
                logging.error(f'Request to {typename}/{api} resulted in code '
                              f'{response.status_code}; '
                              f'retrying in {retry_wait}s '
                              f'({nth_retry}/{max_retries})')
                sleep(retry_wait)
            else:
                try:
                    message = response.json()['message']
                except Exception:
                    message = 'Could not parse response JSON message: ' + \
                        repr(response)
                raise RequestException(message)

    @classmethod
    def fetch(cls, typename, body):
        return cls.request(typename, 'fetch', body)

    @classmethod
    def fetch_all(cls, typename, body, n_threads):
        stop_at_offset = -1

        def thread_work(offset):
            nonlocal stop_at_offset
            if stop_at_offset != -1 and stop_at_offset <= offset:
                return []
            thread_spec = body['spec'].copy()
            thread_spec['offset'] = offset
            p = cls.fetch(typename, {'spec': thread_spec})
            if not p['hasMore']:
                stop_at_offset = offset
            return p
        spec = body['spec']
        pagesize = spec.get('limit', cls.limits[typename.lower()])
        groupsize = n_threads * pagesize
        base_offset = spec.get('offset', 0)
        while stop_at_offset == -1:
            with ThreadPool(n_threads) as pool:
                pages = pool.map(thread_work,
                                 range(base_offset, base_offset + groupsize, pagesize))
                yield pages
            base_offset += groupsize

    @classmethod
    def get_all_biblioentry_ids(cls, n_threads=50):
        pages = cls.fetch_all(
            typename='biblioentry',
            body={
                'spec': {'include': 'id'}
            },
            n_threads=n_threads
        )
        for page in pages:
            for subpage in page:
                if subpage['count'] > 0:
                    yield subpage['objs']

    @classmethod
    def get_all_papers(cls, **kwargs):
        pages = cls.fetch_all(
            typename='biblioentry',
            body={
                'spec': {
                    'include': 'id,title,abstractText,hasFullText,authors,publishTime,url',
                    **kwargs
                }
            },
            n_threads=1,
        )
        for page in pages:
            for subpage in page:
                if subpage['count'] > 0:
                    yield subpage['objs']

    @classmethod
    def get_text(cls, biblioentry_ids, n_threads=50):
        # Although GetArticleMetadata supports up to 10 ids,
        # it does not return the ids themselves, and if we
        # query using an id that actually doesn't have full
        # text, then we cannot know which paper is missing in
        # the result. Therefore just query one by one in parallel.
        def thread_work(biblioentry_id):
            text = cls.request(
                typename='biblioentry',
                api='getarticlemetadata',
                body={'ids': [biblioentry_id]}
            )
            if 'value' in text:
                text = text['value']['value']
            else:
                # There was an error and retries couldn't resolve
                # it. Just return that error message + content.
                text = [text]
            if len(text) > 0 and 'body_text' in text[0]:
                body_text = text[0]['body_text']
            else:
                body_text = ''
            return body_text
        with ThreadPool(n_threads) as pool:
            return pool.map(thread_work, biblioentry_ids)
