from adapter.c3aidatalake import evalmetrics
from adapter.gpt3 import GPT3Adapter
from datetime import datetime
from dateutil.relativedelta import relativedelta
import re
import json
import logging

import seaborn as sns
import matplotlib
matplotlib.use('Agg')
sns.set()


def parse_date(date_str):
    return datetime.strptime(date_str, '%Y-%m-%d').date()


def pretty_location(ugly_location):
    return ', '.join([' '.join(re.findall('[A-Z][^A-Z]*', component))
                      for component in ugly_location.replace(' ', '_').split('_')])


class Numerical():
    def __init__(self):
        self.gpt3 = GPT3Adapter()

    @classmethod
    def _clean_spec_str(cls, spec_str):
        res = spec_str.replace('\n', '')
        # Add quotes to keys
        res = re.sub(r'([\w]+):', r'"\1":', res)
        return res

    @classmethod
    def _parse_spec_dates(cls, spec):
        try:
            from_date_str = spec['from']
            to_date_str = spec['to']
            from_date, to_date = cls.resolve_dates(from_date_str, to_date_str)
            spec['from'] = from_date
            spec['to'] = to_date
        except Exception as e:
            logging.error(e)
            logging.error('Bad input from GPT-3?')
            # best thing to do here just might be to ignore exception and tell
            # user we couldn't find the data
            return None, None

    def handle_request(self, text):
        spec_str = self.gpt3.parse_numerical_query(text)
        spec_json_str = self._clean_spec_str(spec_str)
        df = None
        try:
            # Set default spec values and do light preprocess
            spec = {
                'type': 'case',
                'location': 'UnitedStates',
                'from': '1m',
                'to':  datetime.now().strftime('%Y-%m-%d'),
            }
            user_spec = json.loads(spec_json_str)
            no_user_location = 'location' not in user_spec
            no_user_from_date = 'from' not in user_spec
            no_user_to_date = 'to' not in user_spec
            logging.info(f'Numerical spec parsed from user input: {user_spec}')
            user_spec = {
                k.lower(): v.strip() for k, v in user_spec.items() if v.strip()
            }
            spec.update(user_spec)
            self._parse_spec_dates(spec)
            from_date_str = spec['from'].strftime('%Y-%m-%d')
            to_date_str = spec['to'].strftime('%Y-%m-%d')
            logging.info(f'Final numerical spec: {spec}')
            # Map metric name for labels etc
            loc_str = pretty_location(spec['location'])
            df, data_source = self.fetch_data(spec)
            # Deal with when data couldn't be fetched
            metric_name = {
                'case': 'Confirmed Cases',
                'death': 'Confirmed Deaths',
                'recovery': 'Confirmed Recoveries',
            }[spec['type']]
            loc_output = loc_str + \
                (' (you didn\'t specify a location)' if no_user_location else '')
            from_date_output = from_date_str + \
                (' (you didn\'t specify a FROM date)' if no_user_from_date else '') 
            to_date_output = to_date_str + \
                (' (you didn\'t specify a TO date)' if no_user_to_date else '') 
            if df is None:
                reply_text = \
                    (f'It looks like I don\'t have {metric_name} data'
                     f' for {loc_output} from {from_date_output} to '
                     f'{to_date_output}. Try a different location or period?')
                return reply_text, None
        except json.JSONDecodeError:
            logging.error(f'Could not parse spec_str: {spec_str}')
            reply_text = ('I don\'t understand that request. '
                          'Could you be a bit more specific?')
            return reply_text, None
        # Remove missing data
        missing_col = next(c for c in df.columns if c.endswith('missing'))
        df = df[df[missing_col] == 0]
        data_col = next(c for c in df.columns if 'data' in c)
        df = df.rename(columns={data_col: 'metric'})
        df = df.loc[:, ['dates', 'metric']].sort_values('dates')
        # Make figure
        ax = df.plot.line(x='dates', lw=3, color='orange',
                          figsize=(7, 4), legend=False)
        ax.set_xlabel('Dates', fontsize=12)
        ax.set_ylabel(f'No. of {metric_name}', fontsize=12)
        ax.set_title(f'{data_source} {metric_name} in {loc_str}', fontsize=16)
        f = ax.get_figure()
        f.tight_layout()
        png_filename = 'stats_graph.png'
        f.savefig(png_filename, format='png')
        diff = int(df.iloc[-1].metric - df.iloc[0].metric)
        if diff != 0:
            inc_red_str = 'increased' if diff > 0 else 'reduced'
            diff_pct = 100 * ((df.iloc[-1].metric/df.iloc[0].metric) - 1) \
                if df.iloc[0].metric > 0 else float('inf')
            pct_sign = '+' if diff_pct > 0 else '-'
            reply_text = \
                (f'This graph shows the number of {metric_name.lower()} '
                 f'in {loc_output} from {from_date_output} to '
                 f'{to_date_output}, '
                 f'sourced from {data_source} (via C3.ai). '
                 f'Over this period, numbers have {inc_red_str} by '
                 f'{diff} ({pct_sign}{diff_pct:.1f}%).')
        else:
            reply_text = (
                f'Good news! There are no {metric_name.lower()} during this'
                f' period according to {data_source} (via C3.ai).')
        return reply_text, png_filename

    @classmethod
    def fetch_data(cls,
                   spec,
                   sources=['NYT', 'JHU', 'ECDC', 'CovidTrackingProject']):
        metric = spec['type']
        if metric == 'recovery':
            sources = ['JHU']
        spec_loc = spec['location']
        if not spec_loc:
            spec_loc = 'UnitedStates'
        location = cls.resolve_location(spec_loc)
        evalmetrics_ids = cls.gen_evalmetrics_ids(location)
        data = None
        all_cols = []
        stop_searching = False
        for source in sources:
            evalmetrics_expressions = \
                cls.gen_evalmetrics_expressions(metric, source)
            for id_ in evalmetrics_ids:
                df = cls.evalmetrics_request(
                    [id_], evalmetrics_expressions, spec['from'], spec['to'])
                all_cols.extend(df.columns)
                # Discard df if all missing
                missing_col = next(
                    col for col in df.columns if col.endswith('missing'))
                if (df[missing_col] == 100).all():
                    continue
                data = df
                stop_searching = True
                break
            if stop_searching:
                break
        if data is None:
            logging.warning(f'No data for {evalmetrics_ids}')
        return data, source

    @classmethod
    def evalmetrics_request(cls, ids, expressions, from_date, to_date):
        table_name = "outbreaklocation"
        body = {
            'spec': {
                'ids': ids,
                'expressions': expressions,
                'interval': "DAY",
                'start': from_date.strftime("%Y-%m-%d"),
                'end': to_date.strftime("%Y-%m-%d"),
            }
        }
        return evalmetrics(table_name, body, get_all=True)

    @classmethod
    def gen_evalmetrics_ids(cls, location):
        # if the location is in the US and the county and city are both present,
        # query evalmetrics with the county first. if it fails, query evalmetrics using
        # city as county
        # if the location is outside the US and the city and province are both present,
        # query evalmetrics with the province first. if it fails, query evalmetrics using city as
        # province
        if location['country'] == 'UnitedStates':
            if 'city' in location:
                return [
                    '_'.join(
                        [location['county'], location['province'], location['country']]),
                    '_'.join([location['city'], location['province'], location['country']])]
            elif 'county' in location:
                return ['_'.join([location['county'], location['province'], location['country']])]
        else:
            if 'city' in location:
                return [
                    '_'.join([location['province'], location['country']]),
                    '_'.join([location['city'], location['country']])
                ]
        # the below rules apply to both US and non US countries that did not fulfill any of the conditions above
        if 'province' in location:
            return ['_'.join([location['province'], location['country']])]
        return [location['country']]

    @classmethod
    def gen_evalmetrics_expressions(cls, metric, source):
        if metric == 'death':
            return [f'{source}_ConfirmedDeaths']
        elif metric == 'recovery':
            return [f'{source}_ConfirmedRecoveries']
        else:
            return [f'{source}_ConfirmedCases']

    @classmethod
    def resolve_location(cls, location_str):
        resolved = {}
        components = location_str.replace(' ', '_').split('_')
        components.reverse()
        resolved['country'] = components[0]

        if resolved['country'].lower() == 'UnitedStates'.lower():
            if len(components) > 1:
                # this means the location at least contains a state
                resolved['province'] = components[1]
            if len(components) > 2:
                # this means the location at least contains a county
                resolved['county'] = components[2]
            if len(components) > 3:
                # this means the location at least contains a city
                resolved['city'] = components[3]
        else:
            if len(components) > 1:
                # this means the location at least contains a province
                resolved['province'] = components[1]
            if len(components) > 2:
                # this means the location at least contains a city
                resolved['city'] = components[2]

        return resolved

    @classmethod
    def resolve_date_str(cls, date_str):
        abs_date = None
        delta_date = None
        try:
            abs_date = parse_date(date_str)
        except ValueError:
            # must be delta
            search = re.search(r'(\d+)([dwmy])', date_str)
            n = int(search.group(1))
            unit = search.group(2)
            delta_date = relativedelta(**{
                {
                    'd': 'days',
                    'w': 'weeks',
                    'm': 'months',
                    'y': 'years',
                }[unit]: n
            })
        return abs_date, delta_date

    @classmethod
    def resolve_dates(cls, from_date_str, to_date_str):
        '''Convert parsed date strings into date range'''
        from_date, delta_from = cls.resolve_date_str(from_date_str)
        to_date, delta_to = cls.resolve_date_str(to_date_str)
        if from_date:  # From absolute date
            if to_date:  # To absolute date
                pass  # Both absolute, nothing to do
            else:  # To delta date
                to_date = from_date + delta_to
        else:  # From delta date
            if to_date:  # To absolute date
                from_date = to_date - delta_from
            else:  # To delta date
                # Assume TO is relative to today
                to_date = datetime.now().date() - delta_to
                from_date = to_date - delta_from
        # In some rare cases from_date can be in the future
        # e.g. "Thanksgiving" = 11/24 in US, 10/11 in Canada
        if from_date > to_date:
            from_date -= relativedelta(years=1)
        return from_date, to_date
