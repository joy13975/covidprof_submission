import requests
import json
from time import time

# conn_str = 'http://147.192.155.90:58899/get_excerpts'
conn_str = 'http://localhost:8899/get_excerpts'
headers = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
}


def get_excerpts(question,
                 url='https://en.wikipedia.org/wiki/Coronavirus_disease_2019'):
    r = requests.post(conn_str, headers=headers,
                      json={'question': question, 'url': url})
    if r.status_code == 200:
        return json.loads(r.content.decode('utf-8'))
    else:
        print(f'Server returned status {r.status_code}')
        return r


t0 = time()
es = get_excerpts('is covid lethal or not?')
print(f'get_excerpts(): {time()-t0:.1f}s')

for e in es.split('", "'):
    print(e + '\n')
