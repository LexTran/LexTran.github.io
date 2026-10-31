import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from publication_presentation import prepare, rank_paper, find_ccf, short_title, acceptance_month


class PresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogue = json.loads((ROOT / '_data/venue_rankings.json').read_text())

    def paper(self, id='p', venue='BIBM 2026', section='publications', year=2026):
        return {'id':id,'title':'DEMO: A complete paper title','section':section,'year':year,
                'venue':{'en':venue,'zh':venue},'publication':{'venue':venue,'kind':'conference','confirmed':True},
                'scholar':{'id':'test:'+id,'url':'https://scholar.google.com/citations?user=wtordYAAAAAJ'}}

    def test_ccf_full_catalogue_and_current_venues(self):
        self.assertEqual(len(self.catalogue['venues']),681)
        for venue,expected in [('ACM MM 2024','A'),('ACM Multimedia 2024','A'),('BIBM 2026','B'),('ICLR 2027','A')]:
            self.assertEqual(find_ccf(venue,self.catalogue)['ccf'],expected)
        unknown='2026 7th International Conference on Computer Vision, Image and Deep Learning (CVIDL)'
        self.assertIsNone(find_ccf(unknown,self.catalogue))
        self.assertIsNone(find_ccf('New International Conference on Computer Vision and More',self.catalogue))

    def test_companion_events_do_not_inherit_main_conference_rank(self):
        for venue in ['CVPR Workshops 2026','Findings of NAACL 2026','ACM MM Companion 2026']:
            self.assertIsNone(find_ccf(venue,self.catalogue))
        self.assertIsNone(find_ccf('BIBM 2026',self.catalogue,paper_type='short'))

    def test_conference_and_journal_acronyms_do_not_cross_match(self):
        self.assertIsNone(find_ccf('International Conference on IMAGE Technologies',self.catalogue))
        self.assertIsNone(find_ccf('Journal of BIBM Studies',self.catalogue))

    def jcr(self,quartile='Q1',year=2025,indexes=None):
        return {'name':'Example Medical Journal','year':year,'indexes':indexes if indexes is not None else ['SCIE'],
                'source':'https://jcr.clarivate.com/example','verified_on':'2026-10-31',
                'categories':[{'name':'Medical imaging','quartile':quartile}]}

    def test_jcr_fallback_requires_verified_scie_record(self):
        p=self.paper(venue='Example Medical Journal');p['publication']['kind']='journal'
        rank=rank_paper(p,self.catalogue,{'journals':[self.jcr()]})
        self.assertEqual(rank['priority'],3)
        self.assertEqual(rank['label'],'SCI / JCR Q1')
        for record in [self.jcr(indexes=['ESCI']),dict(self.jcr(),source=''),dict(self.jcr(),verified_on='')]:
            self.assertEqual(rank_paper(p,self.catalogue,{'journals':[record]})['priority'],7)

    def test_jcr_latest_year_then_best_category(self):
        p=self.paper(venue='Example Medical Journal');p['publication']['kind']='journal'
        newest=self.jcr('Q3',2025);newest['categories'].append({'name':'AI','quartile':'Q2'})
        rank=rank_paper(p,self.catalogue,{'journals':[self.jcr('Q1',2024),newest]})
        self.assertEqual(rank['priority'],4)
        self.assertIn('2025',rank['basis'])

    def test_ccf_takes_precedence_over_jcr(self):
        p=self.paper(venue='BIBM 2026')
        j=dict(self.jcr(),name='BIBM 2026')
        self.assertEqual(rank_paper(p,self.catalogue,{'journals':[j]})['priority'],1)

    def test_rank_before_year_and_same_rank_newest_first(self):
        papers=[self.paper('unranked','Unknown Venue',year=2029),self.paper('b','BIBM 2026'),
                self.paper('a-old','ACM MM 2024',year=2024),self.paper('a-new','ICLR 2027',year=2027)]
        out,*_=prepare(papers,[],{'known_publications':[p['id'] for p in papers]},self.catalogue,{},'2026-10')
        ordered=sorted(out,key=lambda p:p['publication_order'])
        self.assertEqual([p['id'] for p in ordered],['a-new','a-old','b','unranked'])

    def test_new_publication_generates_one_acceptance_news(self):
        p=self.paper()
        papers,news,state,added,_=prepare([p],[],{},self.catalogue,{},'2026-10')
        self.assertEqual(len(news),1)
        self.assertEqual(news[0]['short_title'],'DEMO')
        self.assertEqual(news[0]['venue'],'BIBM 2026')
        self.assertTrue(news[0]['celebrate'])
        self.assertEqual(news[0]['date_basis'],'announcement')
        self.assertEqual(news[0]['month'],'2026-10')
        _,again,_,added2,_=prepare(papers,news,state,self.catalogue,{},'2026-11')
        self.assertEqual(again,news)
        self.assertFalse(added2)

    def test_preprint_to_formal_publication_triggers_news(self):
        p=self.paper(section='preprints',venue='arXiv preprint')
        _,news,state,added,_=prepare([p],[],{},self.catalogue,{},'2026-10')
        self.assertFalse(news or added)
        p=self.paper()
        _,news,_,added,_=prepare([p],news,state,self.catalogue,{},'2026-11')
        self.assertEqual(len(added),1)
        self.assertEqual(news[0]['month'],'2026-11')

    def test_explicit_acceptance_date_used_not_publication_date(self):
        p=self.paper();p['publication']['publication_date']='2026/05/22'
        self.assertEqual(acceptance_month(p,'2026-10'),('2026-10','announcement'))
        p['acceptance_date']='2026-09'
        self.assertEqual(acceptance_month(p,'2026-10'),('2026-09','acceptance'))

    def test_manual_acceptance_before_scholar_is_supported(self):
        p=self.paper(venue='BIBM 2026 · Accepted Sep 2026')
        p['publication']['confirmed']=False;p['acceptance_date']='2026-09'
        _,news,*_=prepare([p],[],{},self.catalogue,{},'2026-10')
        self.assertEqual(news[0]['month'],'2026-09')

    def test_uncorroborated_scholar_source_does_not_announce_acceptance(self):
        p=self.paper();p['publication']['confirmed']=False
        _,news,state,added,_=prepare([p],[],{},self.catalogue,{},'2026-10')
        self.assertFalse(news or added)
        self.assertNotIn('p',state['known_publications'])

    def test_existing_manual_news_is_deduplicated_and_keeps_date(self):
        event={'id':'old','type':'acceptance','paper_id':'p','month':'2026-09','date_basis':'acceptance',
               'short_title':'DEMO','venue':'BIBM 2026','celebrate':True}
        _,news,_,added,_=prepare([self.paper()],[event],{},self.catalogue,{},'2026-10')
        self.assertFalse(added)
        self.assertEqual(news,[event])

    def test_historical_baseline_does_not_backfill_acceptance_news(self):
        _,news,_,added,_=prepare([self.paper()],[],{'known_publications':['p']},self.catalogue,{},'2026-10')
        self.assertFalse(news or added)

    def test_short_title_override_and_non_acronym_fallback(self):
        p=self.paper();p['short_title']='Chosen name';self.assertEqual(short_title(p),'Chosen name')
        del p['short_title'];p['title']='A long descriptive paper title with no method acronym to invent'
        self.assertEqual(short_title(p),'A long descriptive paper title with no method…')

    def test_existing_news_order_and_acceptance_state_are_preserved(self):
        news=json.loads((ROOT/'_data/news.json').read_text())
        self.assertEqual([n['id'] for n in news[:4]],['craft-ranking','naacl-submission','iclr-submissions','accepted-paper-gsmedqa'])
        self.assertEqual(len([n for n in news if n['type']=='acceptance']),2)


if __name__=='__main__':unittest.main()
