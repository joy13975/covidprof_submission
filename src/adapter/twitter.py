# Data adapter to stream realtime twitter content
# API Doc:
# https://docs.tweepy.org/en/latest/streaming_how_to.html
import json
import logging

import tweepy
from urlextract import URLExtract

from .base.messaging import MessagingAdapter


class TwitterAdapter(MessagingAdapter):
    '''
    TwitterAdapter is a helper class that authenticates our app with
    Twitter and offers a method to track a list of keywords via a persistent
    streaming connection. The stream may be set up in a blocking or non blocking
    fashion
    '''

    class TwitterListener(tweepy.StreamListener):
        def __init__(self, data_handler, error_handler=None):
            super().__init__()
            self.data_handler = data_handler
            self.error_handler = error_handler

        def _print_error_as_warning(self, status_code):
            logging.error(f'Twitter Error: {status_code}')
            # tweepy.StreamListener.on_error() returns False by default
            return False

        def on_data(self, data):
            # Parse JSON
            # print('on_data()')
            # import code
            # code.interact(local={**locals(), **globals()})
            return self.data_handler(json.loads(data))

        def on_error(self, status_code):
            if self.error_handler is None:
                return self._print_error_as_warning(status_code)
            return self.error_handler(status_code)

    def __init__(self,
                 secret_file='config/twittersecret.json',
                 message_handler=None,
                 error_handler=None):
        with open(secret_file, 'r') as f:
            secret = json.load(f)
        auth = tweepy.OAuthHandler(secret['api_key'],
                                   secret['api_key_secret'])
        auth.set_access_token(secret['access_token'],
                              secret['access_token_secret'])
        self.api = tweepy.API(auth)
        self.me = self.api.me()
        self.handle = '@' + self.me.screen_name
        self.message_handler = message_handler
        self.error_handler = error_handler
        self.latest_tweet_id = None
        self.tweet_max_chars = 279
        self._load_public_suffix_list()
        self.url_extractor = URLExtract()

    def _load_public_suffix_list(self):
        with open('config/public_suffix.txt', 'r') as file:
            lines = []
            for line in file.readlines():
                line = line.strip().lower()
                if not line or line[0] == '#':
                    continue
                lines.append(line)
        self.public_suffix_list = lines

    def _data_handler(self, data):
        # Preprocess message
        tweet = data['text'].replace(self.handle + ' ', '').strip()
        # Note down latest thread id
        self.latest_tweet_id = data['id']
        if self.message_handler is None:
            logging.warning('No data handler defined!')
            logging.warning(json.dumps(data, indent=4, default=str))
        else:
            self.message_handler(tweet)

    def _error_handler(self, status_code):
        if self.error_handler is None:
            logging.warning('No error handler defined!')
            logging.error(f'Error code: {status_code}')
        else:
            self.error_handler(status_code)

    def _listen(self, tracked_terms=None, is_async=False):
        '''
        listen requires a list of tracked terms, as in
        ["@covidprof", "covid-19", "trump"],
        a message handler function that receives individual tweets, an optional
        error_handler, and an additional argument that determines whether to
        block while listening or start listening on a separate thread
        '''
        if not tracked_terms:
            tracked_terms = [self.handle]
        listener = self.TwitterListener(
            self._data_handler, self._error_handler)
        stream = tweepy.Stream(auth=self.api.auth, listener=listener)
        stream.filter(track=tracked_terms, is_async=is_async)

    def _estimate_tweet_len(self, tweet):
        '''
        Estimate the true length of a tweet by counting links as 23 chars
        and discounting URL chars
        '''
        urls = self.url_extractor.find_urls(tweet)
        for url in urls:
            tweet = tweet.replace(url, '')
        # Twitter counts unicode glyphs not ascii chars!
        total_chars = len(tweet.encode('utf-8')) + 23 * len(urls)
        return total_chars

    def _split_tweet(self, tweet):
        parts = []
        max_chars = self.tweet_max_chars
        ellipsis = '...'
        while self._estimate_tweet_len(tweet) > max_chars:
            # simple cut off can fail when there are links, so use
            # incremental shortening
            ellipsis_max = max_chars - len(ellipsis)
            actual_max = ellipsis_max
            while self._estimate_tweet_len(tweet[:actual_max]) > ellipsis_max:
                # Try to cut at space, but if no space then just reduce 3 chars
                last_good_cutoff = tweet[:actual_max].rfind(' ')
                if last_good_cutoff == -1:
                    # No space then try newline
                    last_good_cutoff = tweet[:actual_max].rfind('\n')
                if last_good_cutoff == -1:
                    actual_max -= 3
                else:
                    actual_max = last_good_cutoff
            parts.append(tweet[:actual_max] + ellipsis)
            tweet = tweet[actual_max:].strip()
        if tweet:
            parts.append(tweet)
        return parts

    def _reply(self, msg, reply_to_id=None, media_ids=[]):
        if reply_to_id is None:
            reply_to_id = self.latest_tweet_id
        for i, part in enumerate(self._split_tweet(msg)):
            logging.info(f'Send tweet: \"{part}\"')
            part_media_ids = media_ids
            if i > 0:
                part_media_ids = []
            try:
                status = self.tweet(part,
                                    in_reply_to_status_id=reply_to_id,
                                    auto_populate_reply_metadata=True,
                                    media_ids=part_media_ids)
            except tweepy.error.TweepError as e:
                if 'attempted to reply to a Tweet that is deleted' in str(e):
                    logging.warning('Original tweet deleted - cannot reply.')
                    return -1
            # mutate reply to id so that the next part tweet is in reply
            # to the previously sent part tweet
            reply_to_id = status.id
        return reply_to_id

    def tweet(self, tweet, **kwargs):
        return self.api.update_status(tweet, **kwargs)

    def _upload_media(self, filename, **kwargs):
        return self.api.media_upload(filename, **kwargs)
