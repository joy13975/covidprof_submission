# Adapter for GPT3 queries
import logging
from datetime import datetime
import json

import openai

from base.config_loader import ConfigLoader
from question_type import QuestionType
from intent_type import IntentType


class GPT3Adapter(ConfigLoader):
    def __init__(self):
        super().__init__()
        openai.api_key = self.api_key
        self._load_prompts()

    def _load_prompts(self):
        '''Read prompt from text files specified in config'''
        for prompt_name, prompt_config in self.prompts.items():
            with open(prompt_config['file'], 'r') as f:
                prompt = ''.join(f.readlines()).strip()
                setattr(self, f'{prompt_name.lower()}_prompt', prompt)
                setattr(self, f'{prompt_name.lower()}_params',
                        prompt_config['params'])

    def _prepare_prompt(self, prompt_name, msg, excerpts=None):
        # Always load latest prompt
        self._load_prompts()
        prompt = getattr(self, prompt_name)
        prepared = prompt\
            .replace(self.prompt_msg_token, msg)\
            .replace(self.prompt_year_token, str(datetime.now().year))\
            .replace(self.prompt_month_token, str(datetime.now().month))\
            .replace(self.prompt_day_token, str(datetime.now().day))
        if excerpts:
            prepared = prepared.replace(self.prompt_excerpts_token, excerpts)
        return prepared

    def _postprocess_answer(self, answer):
        '''Try to make sure answer is in the right form and not dangerous'''
        for stop_word in self.answer_stop_words:
            if stop_word.lower() in answer.lower():
                logging.warn(
                    f'Stop "{stop_word}" word found in answer "{answer}"!')
                logging.warn(
                    f'Altering answer to "{self.dangerous_answer_replacement}"')
                answer = self.dangerous_answer_replacement
        answer = answer.capitalize()
        return answer

    def query(self, prompt, max_retries=10, retry_wait=3, **kwargs):
        '''
        Query GPT3 to generate text based on a prompt.
        Parameter documentation:
        https://beta.openai.com/docs/api-reference/create-completion
        '''
        for i in range(max_retries):
            try:
                return openai.Completion.create(
                    engine=self.engine,
                    prompt=prompt,
                    **kwargs)['choices'][0]['text'].strip()
            except Exception as e:
                if i == max_retries - 1:
                    raise(e)
                logging.error(f'Exception occured during GPT3: {e}')
                logging.warning(
                    f'Retrying ({i+1}/{max_retries}) in {retry_wait}s')

    def get_intent(self, msg):
        '''Determine message intent'''
        prompt = self._prepare_prompt('sentence_intent_prompt', msg)
        intent = self.query(prompt, **self.sentence_intent_params).lower()
        return {
            'q': IntentType.Question,
            'u': IntentType.AboutMe,
            'o': IntentType.Over,
        }.get(intent, IntentType.Confused)

    def answer_question_about_me(self, msg):
        '''Answer personal question'''
        prompt = self._prepare_prompt('about_self_prompt', msg)
        answer = self.query(prompt, **self.about_self_params)
        return self._postprocess_answer(answer)

    def autocorrect(self, msg):
        '''Autocorrect English message'''
        while msg.endswith('\n'):
            msg = msg[:-1]
        prompt = self._prepare_prompt('autocorrect_prompt', msg)
        answer = self.query(prompt, **self.autocorrect_params)
        return self._postprocess_answer(answer)

    def classify_question(self, question):
        '''Classify question into either stats or text search question'''
        if any(ht in question.lower() for ht in self.graph_hashtags):
            return QuestionType.Stats
        prompt = self._prepare_prompt(
            'classify_question_prompt', question)
        qtype = self.query(prompt, **self.classify_question_params).lower()
        return QuestionType.Stats if 'stats' in qtype else QuestionType.Textual

    def parse_numerical_query(self, query):
        '''
        Parse natural language into structured location, metric type,
        from and to dates.
        '''
        prompt = self._prepare_prompt(
            'parse_numbers_prompt', query)
        spec = self.query(prompt, **self.parse_numbers_params)
        logging.info(f'Numerical Query Spec: {spec}')
        return spec

    def extract_answer(self, question, i_excerpts):
        '''
        Produce an explanation to user's textual inquiry using excerpts.
        '''
        excerpts_text = '\n'.join(f'[{i+1}]:\n{e}\n\n'
                                  for i, (_, e) in enumerate(i_excerpts))
        prompt = self._prepare_prompt(
            'extract_answer_prompt', question, excerpts=excerpts_text)
        logging.info(f'Answer extraction prompt is {len(prompt)} chars')
        answer = self.query(prompt, **self.extract_answer_params)
        # Save prompt for post mortem
        words = [w.capitalize() for w in question.split(' ')]
        filename = datetime.now().strftime(r'%Y%m%d-%H%M%S_') + \
            ''.join(c for w in words for c in w if c.isalnum())
        with open(f'logs/{filename}.json', 'w') as f:
            json.dump({
                'question': question,
                'prompt': prompt,
                'answer': answer,
            }, f)
        # Remove random double quote
        if sum(c == '"' for c in answer) == 1:
            answer = answer.replace('"', '')
        return answer
