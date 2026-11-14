"""Period union semantics and exact tracker navigation, without provider/DB calls."""
import copy
import json
import unittest
from unittest.mock import patch,MagicMock
from urllib.parse import urlsplit,parse_qs
from pymysql import ProgrammingError

from zoom_read import periods,constellation,union_questions,month_bounds,parse_date,period_state,filter_questions

RUN='a'*64
JAN='2025-01-04T00:00:00Z'
JAN_LATE='2025-01-22T00:00:00Z'
FEB='2025-02-05T00:00:00Z'


def pair(identity,kind='coverage',languages=('en','fi')):
    return dict(id=identity*64,kind=kind,evidence=[dict(lang=l,revision=1) for l in languages])


def phase(stamp,*pairs):return dict(start=stamp,pairs=list(pairs))


def fixture():
    return dict(run=RUN,topic=dict(id='Q134949',title='Winter War',languages=['en','fi','sv']),
        bounds=['2025-01-01T00:00:00Z','2025-04-30T00:00:00Z'],asOf='2025-04-30T00:00:00Z',
        observations=[dict(stamp=JAN,state='complete'),dict(stamp=JAN_LATE,state='complete'),
            dict(stamp=FEB,state='complete'),dict(stamp='2025-04-04T00:00:00Z',state='complete')],
        progress=dict(stage='ready'),rows=[
            dict(id='b'*64,title='Specific first question?',phases=[phase(JAN,pair('c'),pair('d','framing',('fi','sv'))),phase(JAN_LATE,pair('e')),phase(FEB,pair('f'))]),
            dict(id='7'*64,title='Specific second question?',phases=[phase(JAN,pair('8','coverage',('en','sv')))])])


class ZoomReadTests(unittest.TestCase):
    def setUp(self):
        source_titles=patch('zoom_read.source_titles',return_value={},create=True)
        source_titles.start();self.addCleanup(source_titles.stop)

    def test_month_deduplicates_passages_pairs_and_observations(self):
        result=periods(fixture(),['en','fi','sv'],'month',2025)['periods'][0]
        self.assertEqual(result['total'],2)
        self.assertEqual(result['counts'],dict(coverage=1,framing=1,contradiction=0))

    def test_year_is_union_not_sum_of_months(self):
        data=fixture();year=periods(data,['en','fi','sv'])['periods'][0]
        months=periods(data,['en','fi','sv'],'month',2025)['periods']
        self.assertEqual(year['total'],2)
        self.assertEqual(sum(m['total'] for m in months),3)

    def test_duplicates_of_same_row_still_count_once(self):
        data=fixture();data['rows'].append(copy.deepcopy(data['rows'][0]))
        self.assertEqual(periods(data,['en','fi','sv'])['periods'][0]['total'],2)

    def test_pair_scope_cannot_inherit_third_edition_framing(self):
        result=periods(fixture(),['en','fi'],'month',2025)['periods'][0]
        self.assertEqual(result['total'],1);self.assertEqual(result['counts']['coverage'],1)
        self.assertEqual(result['counts']['framing'],0)

    def test_language_reordering_changes_no_counts(self):
        a=periods(fixture(),['en','fi','sv'])['periods']
        b=periods(fixture(),['sv','fi','en'])['periods']
        self.assertEqual(a,b)

    def test_strongest_category_precedes_newest_checkpoint(self):
        result=union_questions(fixture(),['en','fi','sv'],*month_bounds('2025-01'))
        first=next(i for i in result if i['id']=='b'*64)
        self.assertEqual(first['kind'],'framing');self.assertEqual(first['stamp'],JAN)
        self.assertEqual(first['pair'],'FI ↔ SV')

    def test_latest_supporting_checkpoint_precedes_current_language(self):
        data=fixture();data['rows']=[dict(id='b'*64,title='Question?',phases=[
            phase(JAN,pair('c','framing',('en','fi'))),phase(JAN_LATE,pair('d','framing',('fi','sv')))])]
        result=union_questions(data,['en','fi','sv'],*month_bounds('2025-01'))[0]
        self.assertEqual(result['stamp'],JAN_LATE);self.assertEqual(result['left'],'fi')

    def test_reader_language_preferred_on_same_category_and_date(self):
        data=fixture();data['rows']=[dict(id='b'*64,title='Question?',phases=[
            phase(JAN,pair('c','framing',('fi','sv')),pair('d','framing',('en','sv')))])]
        result=union_questions(data,['en','fi','sv'],*month_bounds('2025-01'))[0]
        self.assertEqual(result['left'],'en');self.assertEqual(result['occurrence'],'d'*64)

    def test_unknown_zero_and_outside_periods_are_distinct(self):
        months=periods(fixture(),['en','fi','sv'],'month',2025)['periods']
        self.assertEqual((months[2]['state'],months[2]['total']),('unknown',0))
        self.assertEqual((months[3]['state'],months[3]['total']),('complete',0))
        self.assertEqual(months[4]['state'],'unavailable')

    def test_partial_status_is_not_complete(self):
        data=fixture();data['observations'][0]['state']='partial'
        self.assertEqual(period_state(data,*month_bounds('2025-01')),'partial')

    def test_constellation_count_matches_month_blob(self):
        data=fixture()
        with patch('question_titles.labels',return_value={}):result=constellation(data,['en','fi','sv'],'2025-01')
        blob=periods(data,['en','fi','sv'],'month',2025)['periods'][0]
        self.assertEqual(result['total'],blob['total']);self.assertEqual(result['counts'],blob['counts'])

    def test_exact_observation_does_not_borrow_other_dates(self):
        with patch('question_titles.labels',return_value={}):result=constellation(fixture(),['en','fi','sv'],'2025-01',JAN_LATE)
        self.assertEqual(result['total'],1);self.assertEqual(result['questions'][0]['kind'],'coverage')
        self.assertEqual(result['questions'][0]['stamp'],JAN_LATE)

    def test_unassessed_checkpoint_is_rejected(self):
        with self.assertRaises(ValueError):constellation(fixture(),['en','fi','sv'],'2025-01','2025-01-15T00:00:00Z')

    def test_pagination_does_not_cap_questions(self):
        data=fixture();template=data['rows'][0];data['rows']=[dict(id=f'{i:064x}',title='Question?',phases=copy.deepcopy(template['phases'])) for i in range(215)]
        with patch('question_titles.labels',return_value={}):
            first=constellation(data,['en','fi','sv'],'2025-01',page=1)
            last=constellation(data,['en','fi','sv'],'2025-01',page=3)
        self.assertEqual(first['total'],215);self.assertEqual(first['pages'],3)
        self.assertEqual(len(first['questions']),100);self.assertEqual(len(last['questions']),15)

    def test_tracker_link_keeps_actual_pair_category_and_back(self):
        back='topic=Q134949&view=dots&period=2025-01&q=peace&search_mode=hybrid'
        with patch('question_titles.labels',return_value={}):result=constellation(fixture(),['en','fi','sv'],'2025-01',back=back)
        item=next(i for i in result['questions'] if i['id']=='b'*64);q=parse_qs(urlsplit(item['href']).query)
        self.assertEqual(item['kind'],'framing');self.assertEqual(item['pair'],'FI ↔ SV')
        self.assertEqual(q['lang'],['fi']);self.assertEqual(q['stamp'],[JAN]);self.assertEqual(q['occurrence'],['d'*64])
        self.assertEqual(q['skyline'],[back]);self.assertEqual(set(q['languages']),{'en','fi','sv'})

    def test_cached_accepted_title_replaces_fallback_without_generation(self):
        with patch('question_titles.labels',return_value={'b'*64:dict(title='Who initiated the Winter War?',status='accepted')}),patch('question_titles.structured',side_effect=AssertionError('GET must not generate')):
            result=constellation(fixture(),['en','fi','sv'],'2025-01')
        item=next(i for i in result['questions'] if i['id']=='b'*64)
        self.assertEqual(item['title'],'Who initiated the Winter War?');self.assertEqual(item['title_status'],'accepted')

    def test_missing_title_table_is_graceful(self):
        with patch('question_titles.connect',side_effect=ProgrammingError(1146,'missing table')):
            result=constellation(fixture(),['en','fi','sv'],'2025-01')
        self.assertTrue(all(q['title_status']=='provisional' for q in result['questions']))

    def test_search_only_receives_ids_eligible_in_view(self):
        data=fixture();data['rows'].append(dict(id='9'*64,title='Another date',phases=[phase(FEB,pair('0'))]))
        with patch('question_search.search',return_value=dict(mode='keyword',warning='',matches=[dict(id='b'*64,relevance=1)])) as search,patch('question_titles.labels',return_value={}):
            result=constellation(data,['en','fi'],'2025-01',query='peace')
        self.assertEqual(search.call_args.args[:3],('Q134949',['en','fi'],['b'*64]))
        self.assertEqual(result['total'],1)


class ProviderGateTests(unittest.TestCase):
    def test_general_text_generation_remains_disabled(self):
        import live_api
        with patch('live_api.connect') as connect,patch('live_api.requests.post') as post:
            with self.assertRaises(live_api.APIError):live_api.call('responses',{},'summaries')
        connect.assert_not_called();post.assert_not_called()

    def test_question_generation_and_decisions_reuse_cached_response(self):
        import live_api
        for endpoint,stage in [('responses','question_titles'),('decisions','decisions')]:
            db=MagicMock();cursor=db.__enter__.return_value.cursor.return_value.__enter__.return_value
            cursor.fetchone.side_effect=[dict(locked=1),dict(status='done',result=json.dumps(dict(cached=True)))]
            with patch('live_api.connect',return_value=db),patch('live_api.requests.post') as post:
                self.assertEqual(live_api.call(endpoint,{},stage),dict(cached=True))
            post.assert_not_called()


if __name__=='__main__':unittest.main()
