import copy
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import Mock
from media import extract_image,enrich_media,valid_image,MEDIA_SPECS

NOW=datetime(2026,11,8,20,tzinfo=timezone.utc)
def stamp(now):return now.isoformat().replace('+00:00','Z')
def item(index=0,source='eurostat-en'):
    return {'id':f'{source}:{index}','sourceId':source,'url':f'https://ec.europa.eu/eurostat/product?code={index}','updatedAt':None,'title':'Original title'}
def state(items):return {'feed':{'lastSuccessfulRefreshAt':stamp(NOW),'items':items},'history':items,'mediaState':{}}
SOURCES=[{'id':'eurostat-en','allowedHosts':['ec.europa.eu']},{'id':'cnil','allowedHosts':['www.cnil.fr']},{'id':'arxiv-ai-en','allowedHosts':['arxiv.org']}]
def image():return extract_image('<img src="/eurostat/o/adaptive-media/image/1/Preview/chart.jpg" alt="Original chart">','https://ec.europa.eu/eurostat/product','eurostat-en','Title')

class MediaTests(unittest.TestCase):
    def test_chart_not_stock_photo_or_related_article(self):
        html='<img src="/eurostat/documents/shutterstock.jpg"><img src="/eurostat/o/adaptive-media/image/1/Preview/chart.jpg" alt="Original chart"><h2>You might also like</h2><img src="/eurostat/o/adaptive-media/image/2/other.jpg">'
        result=extract_image(html,'https://ec.europa.eu/eurostat/product','eurostat-en','Title')
        self.assertEqual(result['alt'],'Original chart');self.assertTrue(result['src'].endswith('/chart.jpg'))
        self.assertIsNone(extract_image('You might also like<img src="/eurostat/o/adaptive-media/image/2/other.jpg">','https://ec.europa.eu','eurostat-en','Title'))

    def test_cnil_whole_illustration_and_correct_license(self):
        result=extract_image('<img src="/themes/custom/logo.png"><img src="/sites/default/files/styles/contenu_generique_visuel/public/2026-11/recherche_sante_interne.png?itok=public" alt="Source caption">','https://www.cnil.fr/fr/article','cnil','Title')
        self.assertEqual(result['licenseName'],'CC BY-NC-ND 4.0');self.assertEqual(result['alt'],'Source caption');self.assertTrue(valid_image(result,'cnil'))
        self.assertIsNone(extract_image('<img alt="EDPB" src="/sites/default/files/styles/contenu_generique_visuel/public/2026-11/privacy_for_kids.png">','https://www.cnil.fr','cnil','Title'))

    def test_source_path_protocol_and_license_validation(self):
        original=image()
        for url in ['http://ec.europa.eu/eurostat/o/adaptive-media/image/1/x.jpg','https://ec.europa.eu.evil.test/eurostat/o/adaptive-media/image/1/x.jpg','https://user:pass@ec.europa.eu/eurostat/o/adaptive-media/image/1/x.jpg','https://ec.europa.eu/private/pixel','https://ec.europa.eu:8443/eurostat/o/adaptive-media/image/1/x.jpg']:
            self.assertFalse(valid_image({**original,'src':url},'eurostat-en'))
        self.assertFalse(valid_image({**original,'licenseUrl':'https://example.com'},'eurostat-en'))
        self.assertFalse(valid_image(original,'arxiv-ai-en'))

    def test_daily_cache_and_empty_media_cache(self):
        initial=state([item()]);fetch=Mock(return_value=image());result=enrich_media(initial,SOURCES,NOW,fetch)
        self.assertEqual(fetch.call_count,1);self.assertIn('image',result['feed']['items'][0])
        later=NOW+timedelta(hours=1);result['feed']['lastSuccessfulRefreshAt']=stamp(later);fetch.reset_mock()
        enrich_media(result,SOURCES,later,fetch);fetch.assert_not_called()
        empty=state([item()]);none=Mock(return_value=None);enrich_media(empty,SOURCES,NOW,none)
        empty['feed']['lastSuccessfulRefreshAt']=stamp(later);none.reset_mock();enrich_media(empty,SOURCES,later,none);none.assert_not_called()

    def test_lookup_cap_and_no_arxiv_page_or_pdf(self):
        entries=[item(index) for index in range(8)]+[item(0,'arxiv-ai-en')];fetch=Mock(return_value=image())
        enrich_media(state(entries),SOURCES,NOW,fetch);self.assertEqual(fetch.call_count,6)
        self.assertTrue(all(call.args[0]['sourceId']!='arxiv-ai-en' for call in fetch.call_args_list))

    def test_failed_metadata_preserves_prior_image(self):
        initial=state([item()]);enrich_media(initial,SOURCES,NOW,Mock(return_value=image()))
        later=NOW+timedelta(days=1);initial['feed']['lastSuccessfulRefreshAt']=stamp(later)
        enrich_media(initial,SOURCES,later,Mock(side_effect=OSError('offline')))
        self.assertTrue(valid_image(initial['feed']['items'][0]['image'],'eurostat-en'))

    def test_total_feed_outage_does_not_make_new_metadata_requests(self):
        initial=state([item()]);initial['feed']['lastSuccessfulRefreshAt']=stamp(NOW-timedelta(days=1));fetch=Mock()
        self.assertIs(enrich_media(initial,SOURCES,NOW,fetch),initial);fetch.assert_not_called()

if __name__=='__main__':unittest.main()
