import requests
import re
import json
import logging
import urllib.parse as urlparse

from bs4 import BeautifulSoup

from base.config_loader import ConfigLoader


class WebAdapter(ConfigLoader):
    '''
    Adapter for fetching pages from various HTML data sources
    such as Wikipedia
    '''
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }

    @classmethod
    def _clean_text(cls, data):
        '''Remove parts of text that might hinder language processing'''
        spchar_list = ['\n', '/', '\\', '[', ']']
        data = data.translate({ord(x): x for x in spchar_list})
        data = data.replace('\xa0', ' ')
        data = re.sub(r'(.)([\.\,\!\?\'\"\[\]\)\;\:])([^ ])', r'\1\2 \3', data)
        data = re.sub(r'(\[\d+\])+', '', data)
        data = re.sub(r' \n', '\n', data)
        data = re.sub(r'\n+', ' ', data)
        data = re.sub(r' +', ' ', data)
        return data

    def parse_page(self, url, page_type='generic'):
        '''Download HTML and extract text from webpage'''
        html_data = requests.get(url).text
        soup = BeautifulSoup(html_data, 'lxml')
        generic_tags = self.custom_parse.get('generic', [])
        if page_type not in self.custom_parse:
            logging.warning(f'{page_type} is not a defined custom parse type. '
                            f'Defined types: {list(self.custom_parse.keys())}')
        tags = set(generic_tags + self.custom_parse.get(page_type, []))

        def find_elements(tag):
            return tag.name in tags
        text_elms = soup.find_all(find_elements)
        text = '\n'.join(str(p.getText()) for p in text_elms)
        cleaned_text = self._clean_text(text)
        title = soup.find('title')
        if title:
            title = title.string
        return title, cleaned_text

    def get_excerpts(self, question, docs, timeout=50):
        '''Query excerpt extraction server to reduce documents into excerpts'''
        r = requests.post(
            self.excerpts_conn_str,
            headers=self.headers,
            json={'question': question, 'docs': docs},
            timeout=timeout
        )
        if r.status_code == 200:
            return json.loads(r.content)
        else:
            logging.error('Excerpts extraction server returned code'
                          f' {r.status_code}!')
            logging.error(r.content)
            return r.content

    def shorten_url(self, url):
        '''Make long URL shorter using cuttly'''
        if not url:
            logging.warning('Tried to shorten empty URL!')
            return url
        api_key = self.cuttly_config["api_key"]
        request_url = ('https://cutt.ly/api/api.php?'
                       f'key={api_key}'
                       f'&short={urlparse.quote(url)}')
        r = requests.get(request_url)
        if r.status_code == 200:
            return json.loads(r.content)['url']['shortLink']
        else:
            logging.error('Cuttly server returned code'
                          f' {r.status_code}!')
            logging.error(r.content)
            return r.content
