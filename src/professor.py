# Entry point for the COVID Professor main app
import logging
import re
import sys
from time import time
import RAKE
from multiprocessing.pool import ThreadPool

from adapter.elastic_search import ElasticSearchAdapter as SearchEngine
from adapter.twitter import TwitterAdapter
from adapter.c3ai import C3aiAdapter
from adapter.gpt3 import GPT3Adapter
from adapter.web import WebAdapter
from question_type import QuestionType
from numerical import Numerical
from base.config_loader import ConfigLoader
from intent_type import IntentType

rake = RAKE.Rake(RAKE.SmartStopList())


class Professor(ConfigLoader):
    safe_words_regex = [
        re.compile(fmt) for fmt in [
            r'^stop[\.\,\!]*$',
            r'^shut up[\.\,\!\?]*$',
            r'^.*fuck.*$',
            r'^.*idiot.*$',
            r'^you (are )?stupid[\.\,\!\?]*$',
            r'^wtf[\.\,\!\?]*$',
            r'^ok[\.\,\!\?]*$',
        ]
    ]

    def __init__(self):
        '''Constructor'''
        super().__init__()
        # Initialize components
        self.messaging = TwitterAdapter(message_handler=self.message_handler)
        self.search_engine = SearchEngine()
        self.datalake = C3aiAdapter()
        self.language = GPT3Adapter()
        self.web = WebAdapter()
        self.numerical = Numerical()

    def _get_auxiliary_url(self, msg, corrected_msg):
        '''Select a COVID-19 related webpage URL based on input message'''
        # TODO: Smarter URL selection or update to an actual search
        msg_words = f'{msg} {corrected_msg}'.lower().split()
        macro = len(set(msg_words) & set(self.macro_words)) > 0
        if macro:
            url = self.macro_url
        else:
            url = self.micro_url
        return url

    @classmethod
    def _calc_relevance(cls, words, docs):
        '''Calculate simple relevance measure by counting keywords' presence
        in docs'''
        return sum(
            [w.lower() in doc.lower() for w in words for doc in docs]
        ) / len(words)/len(docs)

    def _get_document_urls(self, docs):
        '''Extract urls from search result documents'''
        urls = []
        for d in docs:
            try:
                # Need to remove api links because they fail to
                # actually lead to the paper
                url = next(
                    u for u in d['url'].split(';')
                    if all(w not in u.lower()
                           for w in self.banned_url_words)
                )
            except StopIteration:
                url = d['url']
            urls.append(url)
        return urls

    def _shorten_url(self, url):
        '''Shortens a URL or return original URL on failure'''
        if not self.shorten_urls:
            return url
        try:
            return self.web.shorten_url(url)
        except Exception as e:
            logging.error(f'Could not shorten URL "{url}" due to {e}')
            return url

    def _shorten_urls(self, urls, max_threads=2):
        '''Shortens URLs (multithreaded)'''
        with ThreadPool(min(len(urls), max_threads)) as pool:
            return pool.map(self._shorten_url, urls)

    def _answer_textual(self, msg, corrected_msg):
        '''Search for a textual answer to a human question'''
        covid_crct_msg = self.input_msg_header + corrected_msg
        # Extract keywords for search because they perform
        # better than simply feeding the whole message.
        # The result contains phrase parts and score in tuples.
        rake_results = rake.run(covid_crct_msg)
        logging.info(f'RAKE results: {rake_results}')
        # Search backend for relevant text
        keyword_str = ' '.join(w for w, _ in rake_results)
        # Still make it configurable whether to use keyword or
        # message in search
        search_query = keyword_str if self.use_keyword_to_search \
            else corrected_msg
        t0 = time()
        search_results = self.search_engine.search(
            search_query,
            n=self.search_n_docs,
            n_frags=self.search_n_frags,
            frag_size=self.search_frag_size)
        logging.info(f'Search engine took {time()-t0:.1f}s')
        # Extract fragments wthin the results
        relevant_text = [
            self.search_engine.get_highlight_frags(r)
            for r in search_results
        ]
        # Log relevance as a measure of search performance
        keyword_list = keyword_str.split(' ')
        search_relevance = self._calc_relevance(keyword_list, relevant_text)
        logging.info(f'Search relevance: {search_relevance:.2f}')
        # Get auxiliary text
        aux_url = self._get_auxiliary_url(msg, corrected_msg)
        _, aux_text = self.web.parse_page(aux_url, page_type='wikipedia')
        docs = [d for d in [aux_text, *relevant_text] if d]
        total_len = sum(len(d) for d in docs)
        logging.info(
            f'Sending docs of total {total_len} chars into excerpt extraction')
        t0 = time()
        i_excerpts = self.web.get_excerpts(question=corrected_msg, docs=docs)
        logging.info(f'Excerpt extraction took {time()-t0:.1f}s')
        excerpt_relevance = self._calc_relevance(
            keyword_list, [e for _, e in i_excerpts])
        logging.info(f'Excerpt relevance: {excerpt_relevance:.2f}')
        top_excerpts = i_excerpts[:self.n_excerpts_considered]
        t0 = time()
        answer = self.disclaimer['medical'] + \
            self.language.extract_answer(covid_crct_msg, top_excerpts)
        logging.info(f'Answer formatting took {time()-t0:.1f}s')
        urls = [aux_url, *self._get_document_urls(search_results)]
        top_urls = [urls[i] for i, _ in top_excerpts]
        t0 = time()
        short_urls = self._shorten_urls(top_urls)
        logging.info(f'URL shortening took {time()-t0:.1f}s')
        return answer, short_urls

    def _answer_question(self, msg, corrected_msg):
        '''Determine question type and answer each type appropriately'''
        question_type = self.language.classify_question(corrected_msg)
        answer = ''
        urls = []
        png_filename = None
        if question_type == QuestionType.Stats:
            answer, png_filename = self.numerical.handle_request(corrected_msg)
        elif question_type == QuestionType.Textual:
            answer, urls = self._answer_textual(msg, corrected_msg)
        else:
            answer = 'I don\'t know how to answer that.'
        return answer, urls, png_filename, question_type

    def _generate_reply(self, msg):
        '''Returns empty string if input is to be ignored.'''
        # Remove any twitter handles first
        msg = re.sub(r'@(\w){1,15}', '', msg)
        msg = re.sub(r' +', ' ', msg).strip()
        # Set default return values
        answer = ''
        urls = []
        png_filename = None
        question_type = None
        def retvals(): return answer, urls, png_filename, question_type
        # Check for empty message
        if not msg or re.search(r'[a-z]+', msg.lower().strip()) is None:
            # No info inside msg
            logging.warning(f'Message has no info: {msg}')
            answer = self.confused_msg
            return retvals()
        # Autocorrect message
        corrected_msg = self.language.autocorrect(msg)
        logging.info(f'Message corrected to: {corrected_msg}')
        # Check for safe words
        has_safe_word = any(r.match(corrected_msg.lower()) is not None
                            for r in self.safe_words_regex)
        if has_safe_word:
            logging.warning(f'Message has safe word: {corrected_msg}')
            # Simply ignore (answer is empty) and return early
            return retvals()
        # Detect message intent
        intent = self.language.get_intent(corrected_msg)
        logging.info(f'Conversation intent is: {intent.name}')
        if intent == IntentType.Over:
            # Simply ignore (answer is empty)
            pass
        elif intent == IntentType.Confused:
            answer = self.confused_msg
        elif intent == IntentType.AboutMe:
            answer = self.disclaimer['controversy'] + \
                self.language.answer_question_about_me(corrected_msg)
        else:
            # Answer the question
            answer, urls, png_filename, question_type = \
                self._answer_question(msg, corrected_msg)
        return retvals()

    def message_handler(self, msg):
        '''Upon receiving a message this function starts the whole Q&A process
        '''
        logging.info(f'Received new message: {msg}')
        t0 = time()
        reply, urls, png_filename, question_type = self._generate_reply(msg)
        if reply:
            media_ids = []
            if question_type == QuestionType.Stats and \
                    png_filename is not None:
                # upload image first
                media = self.messaging.upload_media(png_filename)
                media_ids = [media.media_id]
            logging.info(f'Time to reply #1: {time()-t0:.1f}s')
            rely_to_id = self.messaging.reply(reply, media_ids=media_ids)
            if 'I think your question is nonsense.'.lower() in reply:
                logging.info(
                    'Not sending sources because question is detected as nonsense.')
                return
            urls = [u for u in urls if u]
            if urls:
                # Send sources, but repeat last url because in Twitter it
                # disappears into a preview.
                failsafe_phrases = ('i don\'t know.', 'i\'m not sure.')
                if any(ph in reply.lower().strip() for ph in failsafe_phrases):
                    # Exclude wiki (first) link
                    sources_str = \
                        self.articles_might_help_heading + '\n' +\
                        '\n'.join(f'[{i+1}]{url}'
                                  for i, url in enumerate(urls[1:]))
                else:
                    sources_str = \
                        self.references_heading + '\n' +\
                        '\n'.join(f'[{i+1}]{url}'
                                  for i, url in enumerate(urls))
                logging.info(f'Time to reply #2: {time()-t0:.1f}s')
                self.messaging.reply(sources_str, reply_to_id=rely_to_id)

    def start(self):
        '''Main entry to start listening for messages'''
        logging.info('Listening for messages...')
        self.messaging.listen(is_async=False)


if __name__ == '__main__':
    logging.basicConfig(
        format='%(asctime)s %(levelname)-8s %(message)s',
        level=logging.INFO,
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    p = Professor(**dict(v.split('=') for v in sys.argv[1:]))
    p.start()
