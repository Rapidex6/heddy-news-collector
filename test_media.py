import copy
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime,timedelta,timezone
from unittest.mock import Mock
from media import extract_image,enrich_media,valid_image,feed_image,MEDIA_SPECS,MAX_LOOKUPS

NOW=datetime(2026,11,8,20,tzinfo=timezone.utc)
def stamp(now):return now.isoformat().replace('+00:00','Z')
def item(index=0,source='eurostat-en'):
    return {'id':f'{source}:{index}','sourceId':source,'url':f'https://ec.europa.eu/eurostat/product?code={index}','updatedAt':None,'title':'Original title'}
def state(items):return {'feed':{'lastSuccessfulRefreshAt':stamp(NOW),'items':items},'history':items,'mediaState':{}}
SOURCES=[copy.deepcopy(MEDIA_SPECS[id]) for id in ['eurostat-en','cnil','arxiv-ai-en']]
def image():return extract_image('<img src="/eurostat/o/adaptive-media/image/1/Preview/chart.jpg" alt="Original chart">','https://ec.europa.eu/eurostat/product','eurostat-en','Title')

class MediaTests(unittest.TestCase):
    def test_chart_not_stock_photo_or_related_article(self):
        html='<img src="/eurostat/documents/shutterstock.jpg"><img src="/eurostat/o/adaptive-media/image/1/Preview/chart.jpg" alt="Original chart"><h2>You might also like</h2><img src="/eurostat/o/adaptive-media/image/2/other.jpg">'
        result=extract_image(html,'https://ec.europa.eu/eurostat/product','eurostat-en','Title')
        self.assertEqual(result['alt'],'Original chart');self.assertTrue(result['src'].endswith('/chart.jpg'))
        self.assertIsNone(extract_image('You might also like<img src="/eurostat/o/adaptive-media/image/2/other.jpg">','https://ec.europa.eu','eurostat-en','Title'))

    def test_publisher_image_does_not_need_a_filename_or_license_allowlist(self):
        result=extract_image('<meta property="og:image" content="https://www.cnil.fr/sites/default/files/another-illustration.png">','https://www.cnil.fr/fr/article','cnil','Title')
        self.assertTrue(valid_image(result,'cnil'));self.assertEqual(result['attribution'],'CNIL')
        self.assertTrue(result['src'].endswith('another-illustration.png'))

    def test_source_path_protocol_and_license_validation(self):
        original=image()
        for url in ['http://ec.europa.eu/eurostat/o/adaptive-media/image/1/x.jpg','https://ec.europa.eu.evil.test/eurostat/o/adaptive-media/image/1/x.jpg','https://user:pass@ec.europa.eu/eurostat/o/adaptive-media/image/1/x.jpg','https://127.0.0.1/private/pixel','https://ec.europa.eu:8443/eurostat/o/adaptive-media/image/1/x.jpg']:
            self.assertFalse(valid_image({**original,'src':url},'eurostat-en'))
        self.assertFalse(valid_image({**original,'licenseUrl':'javascript:alert(1)'},'eurostat-en'))
        self.assertFalse(valid_image(original,'arxiv-ai-en'))

    def test_daily_cache_and_empty_media_cache(self):
        initial=state([item()]);fetch=Mock(return_value=image());result=enrich_media(initial,SOURCES,NOW,fetch)
        self.assertEqual(fetch.call_count,1);self.assertIn('image',result['feed']['items'][0])
        later=NOW+timedelta(hours=1);result['feed']['lastSuccessfulRefreshAt']=stamp(later);fetch.reset_mock()
        enrich_media(result,SOURCES,later,fetch);fetch.assert_not_called()
        empty=state([item()]);none=Mock(return_value=None);enrich_media(empty,SOURCES,NOW,none)
        empty['feed']['lastSuccessfulRefreshAt']=stamp(later);none.reset_mock();enrich_media(empty,SOURCES,later,none);none.assert_not_called()

    def test_lookup_cap_and_no_arxiv_page_or_pdf(self):
        entries=[item(index) for index in range(MAX_LOOKUPS+2)]+[item(0,'arxiv-ai-en')];fetch=Mock(return_value=image())
        enrich_media(state(entries),SOURCES,NOW,fetch);self.assertEqual(fetch.call_count,MAX_LOOKUPS)
        self.assertTrue(all(call.args[0]['sourceId']!='arxiv-ai-en' for call in fetch.call_args_list))

    def test_failed_metadata_preserves_prior_image(self):
        initial=state([item()]);enrich_media(initial,SOURCES,NOW,Mock(return_value=image()))
        later=NOW+timedelta(days=1);initial['feed']['lastSuccessfulRefreshAt']=stamp(later)
        enrich_media(initial,SOURCES,later,Mock(side_effect=OSError('offline')))
        self.assertTrue(valid_image(initial['feed']['items'][0]['image'],'eurostat-en'))

    def test_total_feed_outage_does_not_make_new_metadata_requests(self):
        initial=state([item()]);initial['feed']['lastSuccessfulRefreshAt']=stamp(NOW-timedelta(days=1));fetch=Mock()
        self.assertIs(enrich_media(initial,SOURCES,NOW,fetch),initial);fetch.assert_not_called()

    def test_feed_media_uses_largest_image_and_preserves_query(self):
        entry=ET.fromstring('<item xmlns:media="http://search.yahoo.com/mrss/"><media:thumbnail url="https://i.guim.co.uk/small.jpg" width="140"/><media:content url="https://i.guim.co.uk/large.jpg?width=1000&amp;quality=85" width="1000"/></item>')
        result=feed_image(entry,MEDIA_SPECS['guardian-business'],'Title')
        self.assertIn('large.jpg?width=1000&quality=85',result['src'])

    def test_embedded_feed_image_needs_no_article_request(self):
        initial=state([{**item(),'image':{**image(),'origin':'feed'}}]);fetch=Mock()
        enrich_media(initial,SOURCES,NOW,fetch);fetch.assert_not_called()

if __name__=='__main__':unittest.main()
