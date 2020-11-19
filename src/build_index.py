# Builds or updates research paper index
import sys
import os
import json
from time import time
from glob import glob
from itertools import chain
import logging
from datetime import datetime

from adapter.c3ai import C3aiAdapter
from adapter.elastic_search import ElasticSearchAdapter as SearchEngine
from adapter.web import WebAdapter


def download(skip_to=-1, stop_at=-1, get_paper_args={}, output='file'):
    a = C3aiAdapter()
    for page_i, papers_page in enumerate(a.get_all_papers(**get_paper_args)):
        t0 = time()
        if skip_to != -1 and page_i < int(skip_to):
            logging.info(f'Skipping page {page_i}')
            continue
        if stop_at != -1 and page_i >= int(stop_at):
            break
        logging.info(f'Downloading page {page_i}...')
        # Strip unnecessary info
        text_papers = []
        for p in papers_page:
            del p['meta']
            del p['version']
            if p.get('hasFullText'):
                text_papers.append(p)
            else:
                p['text'] = ''
        text_paper_ids = [p['id'] for p in text_papers]
        # Fetch paper text
        texts = a.get_text(text_paper_ids)
        # Assign text to paper
        for p, t in zip(text_papers, texts):
            p['text'] = t
        # Output
        if output == 'file':
            with open(f'data/page_{page_i}.json', 'w') as f:
                json.dump(papers_page, f)
        elif output == 'yield':
            yield papers_page
        else:
            raise ValueError(f'Unknown output type {output}')
        logging.info(f'Page {page_i} downloaded in {time()-t0:.1f}s')
        page_i += 1
    logging.info('Done')


def _paper_to_doc(papers):
    for paper in papers:
        if type(paper['text']) is list:
            paper['text'] = '\n'.join(section['text']
                                      for section in paper['text'])
        yield {
            'id': paper['id'],
            'title': paper.get('title', ''),
            'authors': paper.get('authors', ''),
            'publishTime': paper.get('publishTime', ''),
            'abstract': paper.get('abstractText', ''),
            'body': paper.get('text', ''),
            'url': paper.get('url', ''),
        }


def _get_doc_iters():
    for path in sorted(glob('data/page_*.json')):
        with open(path, 'r') as f:
            papers = json.load(f)
        logging.info(f'Indexing {path}')
        yield _paper_to_doc(papers)


def init_index():
    t = SearchEngine()
    doc_iter = chain.from_iterable(_get_doc_iters())
    t.add(doc_iter)


def update_index():
    a = C3aiAdapter()
    t = SearchEngine()
    # Get (latest ids) - (indexed ids)
    for i, ids_page in enumerate(a.get_all_biblioentry_ids()):
        new_ids = []
        for id_obj in ids_page:
            paper_id = id_obj['id']
            docs = t.search(paper_id, target_fields=['id'], n=1)
            if docs and docs[0]['id'][0] == paper_id:
                continue
            new_ids.append(paper_id)
        if not new_ids:
            logging.info(f'IDs page {i} has no new paper IDs.')
            continue
        logging.info(f'IDs page {i} new paper IDs: {new_ids}')
        # Get header and full text for these new papers
        pages = download(get_paper_args={'filter': ' || '.join(f'id=="{i}"' for i in new_ids)},
                         output='yield')
        for papers in pages:
            t.add(_paper_to_doc(papers))


def add(json_file):
    assert os.path.exists(json_file)
    with open(json_file, 'r') as f:
        page = json.load(f)
    t = SearchEngine()
    t.add(page)


def add_web(url, page_type='generic'):
    # Download single page
    t = SearchEngine()
    w = WebAdapter()
    title, text = w.parse_page(url, page_type=page_type)
    print(text)
    print('-------------------------------')
    yn = input('Above text OK? (y/n)')
    if yn.lower().lower() != 'y':
        print('Abort')
        exit(0)
    date_str = input('Enter page last update date (YYYYmmdd): ')
    page_id = input('Enter page id: ')
    dt = datetime.strptime(date_str, '%Y%m%d')
    dt_str = dt.isoformat()
    page = {
        'id':  page_id,
        'title': title,
        'body': text,
        'url': url,
        'publishTime': dt_str,
    }

    t.add(page)


def debug():
    logging.warning(f'Debugging with args: {sys.argv}')
    a = C3aiAdapter()
    t = SearchEngine()
    import code
    code.interact(local={**locals(), **globals()})


if __name__ == '__main__':
    logging.basicConfig(
        format='%(asctime)s %(levelname)-8s %(message)s',
        level=logging.INFO,
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    if len(sys.argv) < 2:
        logging.error('Specify mode: init or update')
        exit(1)
    mode = sys.argv[1]
    if mode == 'download':
        list(download(**dict(v.split('=') for v in sys.argv[2:])))
    elif mode == 'init':
        init_index()
    elif mode == 'update':
        update_index()
    elif mode == 'add':
        assert len(sys.argv) >= 3, 'Provide filename'
        add(sys.argv[2])
    elif mode == 'addweb':
        assert len(sys.argv) >= 2, 'Provide URL'
        add_web(sys.argv[2], **dict(v.split('=') for v in sys.argv[3:]))
    else:
        debug()
