import requests
import re
from time import time
from multiprocessing.pool import ThreadPool
import json
import logging
import subprocess
from time import sleep

from bs4 import BeautifulSoup
from adapter.elastic_search import ElasticSearchAdapter as SearchEngine
from adapter.gpt3 import GPT3Adapter


def get_model(model_name, use_gpu=False, pipieline_type='question-answering'):
    from transformers import pipeline
    device = -1  # -1 for CPU
    if use_gpu:
        device = 0  # First GPU device
        logging.info(f'Using GPU device: {device}')
    else:
        logging.info('Using CPU')
    logging.info(f'Initializing model "{model_name}"" ...')
    model = pipeline(pipieline_type, model=model_name,
                     tokenizer=model_name, framework='pt', device=device)
    logging.info(f'Model max tokens: {model.tokenizer.model_max_length}')
    return model


def preprocess_text(data):
    spchar_list = ['\n', '/', '\\', '[', ']']
    data = data.translate({ord(x): x for x in spchar_list})
    data = data.replace('\xa0', ' ')
    data = re.sub(r'(.)([\.\,\!\?\'\"\[\]\)\;\:])([^ ])', r'\1\2 \3', data)
    data = re.sub(r'(\[\d+\])+', '', data)
    data = re.sub(r' \n', '\n', data)
    data = re.sub(r'\n+', ' ', data)
    data = re.sub(r' +', ' ', data)
    return data


def get_web_data(url):
    wiki_data = requests.get(url).text
    soup = BeautifulSoup(wiki_data, 'lxml')
    data = []
    paragraphs = soup.select('p')
    excerpts = soup.select('div.excerpt')
    for k in excerpts + paragraphs:
        data.append(k.getText())
    data = '\n'.join([str(s) for s in data])
    data = preprocess_text(data)
    return data


def split_data(data, part_len):
    base = 0
    i = 0
    parts = []
    while True:
        part = data[base:base+part_len]
        last_period = part.rfind('.')
        if last_period == -1:
            last_period = part_len
        part = part[:last_period+1].strip()
        parts.append(part)
        base = base + last_period+1
        if base >= len(data):
            break
        i += 1
    return parts


def get_find_answer_func(model, question):
    def find_answer(part):
        return model({
            'context': part,
            'question': question,
        })
    return find_answer


def get_excerpts_text(top_answers):
    excerpts = []
    sentences_before = 1
    sentences_after = 1
    for i, (ans, part) in top_answers:
        # Go n sentences ahead
        str_before = part[:ans['start']]
        ends_before = [m.end(0) for m in re.finditer(r'[^\.]\. ', str_before)]
        if ends_before:
            begin = ends_before[-min(len(ends_before), (sentences_before+1))]
        else:
            begin = ans['start']
        str_after = part[ans['end']:]
        if len(str_after) < 2:
            end = ans['end'] + len(str_after)
        else:
            end = ans['end']
            ends_after = [m.end(0) for m in re.finditer(r'[^\.]\.', str_after)]
            if ends_after:
                end += ends_after[min(len(ends_after) - 1, sentences_after)]
        ans_src = part[begin:end]
        excerpts.append((i, ans_src))
    return excerpts


class ExcerptGen:
    def __init__(self,
                 model_name='deepset/bert-large-uncased-whole-word-masking-squad2',
                 accelerator='cpu'):
        self._and_start_elastic_server()
        self.se = SearchEngine()
        self.accelerator = accelerator.lower()
        self.gpt3 = GPT3Adapter()
        self.model = None
        if self.accelerator != 'colab':
            self.model = get_model(model_name=model_name,
                                   use_gpu=self.accelerator == 'gpu')

    def _and_start_elastic_server(self):
        '''Make sure elasticsearch server is up'''
        logging.info('Checking Elasticsearch server status...')
        cmd = 'sudo service elasticsearch status'.split()
        try:
            checkstr = subprocess.check_output(cmd).decode('utf-8')
        except subprocess.CalledProcessError as e:
            if 'elasticsearch is not running' in e.output.decode('utf-8')\
                    .lower():
                logging.info('Elasticsearch server is not running - '
                             'attempting to start it now...')
                cmd = 'sudo service elasticsearch start'.split()
                run_result = subprocess.run(cmd)
                if run_result.returncode != 0:
                    logging.error(
                        'Command failed with return code: '
                        f'{run_result.return_code}')
                    exit()
                # Wait a bit after Elasticsearch server is up because
                # making a connection too soon will cause error
                sleep(5)
                return
            raise(e)
        if 'elasticsearch is running' in checkstr.lower():
            # No need to do anything
            logging.info('Elasticsearch sever already running - good.')

    def get_excerpts_from_docs(self, question, docs, max_page_size=512*32):
        answers = []
        find_answer = get_find_answer_func(self.model, question)
        logging.info(f'Get excerpts with max_page_size={max_page_size}')
        if self.accelerator == 'gpu':
            for doc in docs:
                # If p is too large it will crash the GPU...
                logging.info(
                    f'Splitting doc with len={len(doc)}')
                parts = split_data(doc, max_page_size)
                logging.info(
                    f'Doc len {len(doc)} split into {len(parts)} parts')
                part_answers = [find_answer(p) for p in parts]
                answers.append(max(part_answers, key=lambda a: a['score']))
        elif self.accelerator == 'colab':
            answers = self.ask_colab(question, docs)
        else:
            n_threads = 8
            with ThreadPool(n_threads) as pool:
                answers = pool.starmap(find_answer, enumerate(docs))
        # Extract answer text area
        top_answers = sorted(enumerate(zip(answers, docs)),
                             key=lambda v: v[1][0]['score'],
                             reverse=True)
        return get_excerpts_text(top_answers)

    def get_excerpts(self,
                     question,
                     part_len=1024*2,
                     top_n_answers=4,
                     url='https://en.wikipedia.org/wiki/COVID-19_pandemic'):
        t0 = time()
        # Combine wikipedia data + c3ai
        c3ai_docs = self.se.search(question, 3)
        c3ai_texts = [preprocess_text(d['body'] if d['body'] else d['abstract'])
                      for d in c3ai_docs]
        web_text = get_web_data(url)

        if self.accelerator in ('gpu', 'colab'):
            # GPU/colab is fast enough to not need further text breakdown
            parts = [web_text, *c3ai_texts]
            logging.info(f'Data ({sum(len(p) for p in parts)}) (no split)')
        else:
            c3ai_text = '\n\n\n'.join(c3ai_texts)
            evidence_pool = '\n\n\n'.join((web_text, c3ai_text))
            parts = split_data(evidence_pool, part_len=part_len)
            logging.info(
                f'Data ({len(evidence_pool)}) split into {len(parts)} parts')
        logging.info(f'Data gathering: {time()-t0:.1f}s')

        excerpts = self.get_excerpts_from_docs(question, parts)[:top_n_answers]
        return excerpts

    def ask_colab(self, question, docs,
                  conn_str='http://192.168.1.9:8899/ask'):
        r = requests.post(
            conn_str,
            headers={'Content-Type': 'application/json',
                     'Accept': 'application/json'},
            json={'question': question, 'docs': docs},
            timeout=60
        )
        if r.status_code == 200:
            return json.loads(r.content)
        else:
            logging.error(f'Colab server returned code {r.status_code}!')
            logging.error(r.content)
            return r.content
