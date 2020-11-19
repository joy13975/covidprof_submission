# import json
# from adapter.elastic_search import ElasticSearchAdapter
# from adapter.gpt3 import GPT3Adapter
# from numerical import Numerical, pretty_location

# se = ElasticSearchAdapter()
# results = se.search("transmission routes of covid-19", 1)

# for result in results:
#     print(extract_highlights(result))


# print([d['body'] for d in results])

# g = GPT3Adapter()
# print(g.parse_evalmetrics_query("how many cases has there been in Panama since January 2020?"))

# n = Numerical()
# specs = json.loads('{"type": "case", "location": "Seattle_King_Washington_UnitedStates", "reference": "2020-06-01", "period": "until 2020-06-07"}')
# df = n.fetch_data(specs)
# print(df.head())

# for col in df.columns:
#     print(col)

# res = n.fetch_data({'type': 'case', 'location': 'UnitedStates', 'reference': 'today', 'period': '-1w'})
# res = n.resolve_dates("today", "until today")
# print(res)

# g = GPT3Adapter()
# res = g.parse_numerical_query("#plot the deaths from January to now for new york,")
# print(res)

# print(pretty_location('NewYorkCity_NewYork_NewYork_UnitedStates'))

def remove_til(query):
    til_prefixes = [' until', ' til', ' till', ' \'til', ' \'till', ' to', ' up to']
    til_suffixes = ['now', 'today', 'present', 'the present', 'present day', 'the present day',
        'present time', 'the present time', 'current day', 'the current day', 'current time', 'the current time']
    unwanted_tokens = [' '.join([prefix, suffix]) for prefix in til_prefixes for suffix in til_suffixes]

    for token in unwanted_tokens:
        if query.lower().find(token) > -1:
            query = query.replace(token, '')
    
    return query

req = remove_til("#plot death curve for new york from jan 'til now")
print(req)