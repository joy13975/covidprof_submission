import logging
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

from excerpt_gen import ExcerptGen
from base.config_loader import ConfigLoader


class ExcerptServer(ConfigLoader):
    def run(self, **kwargs):
        # allow command line arguments to overwrite config
        for k, v in kwargs.items():
            setattr(self, k, v)
        eg = ExcerptGen(accelerator=self.accelerator,
                        model_name=self.model_name)

        class RequestHandler(BaseHTTPRequestHandler):
            def _set_response(self):
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()

            def do_POST(self):
                # refuse to receive non-json content
                ctype = self.headers['Content-Type']
                if ctype != 'application/json':
                    logging.info(f'Got Content-Type={ctype}')
                    self.send_response(400)
                    self.end_headers()
                    return
                content_length = int(self.headers['Content-Length'])
                body = self.rfile.read(content_length)
                logging.info(f'POST request,\nPath: {self.path}')
                if self.path == '/get_excerpts':
                    response = self._get_excerpts(body)
                elif self.path == '/get_excerpts_from_docs':
                    response = self._get_excerpts_from_docs(body)
                else:
                    logging.info(f'Got path={self.path}')
                    self.send_response(400)
                    self.end_headers()
                    return
                self._set_response()
                self.wfile.write(json.dumps(response).encode('utf-8'))

            def _get_excerpts(self, body):
                message = json.loads(body)
                question = message.get('question', '')
                url = message.get(
                    'url', 'https://en.wikipedia.org/wiki/COVID-19_pandemic')
                if question:
                    response = \
                        eg.get_excerpts(question, url=url)
                else:
                    response = {'error': 'No question provided'}
                return response

            def _get_excerpts_from_docs(self, body):
                message = json.loads(body)
                question = message.get('question', '')
                docs = message.get('docs', [])
                if question and docs:
                    response = eg.get_excerpts_from_docs(question, docs)
                else:
                    response = {
                        'error': (f'No question (len={len(question)}) or '
                                  f'docs (len={len(docs)}) provided')
                    }
                return response

        httpd = HTTPServer((self.host, self.port), RequestHandler)
        logging.info(f'Listening on {self.host}:{self.port}')
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            logging.info('KeyboardInterrupt')
        finally:
            httpd.server_close()


if __name__ == '__main__':
    logging.basicConfig(
        format='%(asctime)s %(levelname)-8s %(message)s',
        level=logging.INFO,
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    s = ExcerptServer()
    s.run(**dict(v.split('=') for v in sys.argv[1:]))
