# Base class for messaging adapter
import logging


class MessagingAdapter:
    def __init__(self,
                 *kargs,
                 message_handler=None,
                 error_handler=None,
                 **kwargs):
        self.message_handler = message_handler
        self.error_handler = error_handler

    def _listen(self, *args, **kwargs):
        pass

    def _reply(self, *args, **kwargs):
        pass

    def _upload_media(self, *args, **kwargs):
        pass

    def listen(self, *args, **kwargs):
        try:
            self._listen(*args, **kwargs)
        except KeyboardInterrupt:
            logging.info('\nStop')

    def reply(self, msg, *args, **kwargs):
        return self._reply(msg, *args, **kwargs)

    def upload_media(self, *args, **kwargs):
        return self._upload_media(*args, **kwargs)
