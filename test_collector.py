import copy
import io
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from collector import (PARIS, canonical_url, collect_language, in_window, parse_date,
                       parse_feed, plain, stamp, validate_feed)
from sftp_publish import atomic_upload

NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
REGISTRY = json.loads(Path(__file__).with_name('sources.json').read_text(encoding='utf-8'))['sources']


def source(name='insee'):
    return copy.deepcopy(next(s for s in REGISTRY if s['id'] == name))


def rss(items='', language='fr'):
    return f'<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><language>{language}</language>{items}</channel></rss>'.encode()


def rss_item(number=1, date='2026-11-06T12:00:00Z'):
    return f'<item><guid>{number}</guid><title>Publication {number}</title><link>https://www.insee.fr/fr/statistiques/{number}?utm_source=x&amp;detail=keep</link><dc:date>{date}</dc:date><description>Un résumé original fourni par la source.</description></item>'


class CollectorTests(unittest.TestCase):
    def test_rss_namespaces_and_original_summary(self):
        item = parse_feed(rss(rss_item()), source(), NOW)[0]
        self.assertEqual(item['publishedAt'], '2026-11-06T12:00:00Z')
        self.assertEqual(item['summary'], 'Un résumé original fourni par la source.')
        self.assertEqual(item['url'], 'https://www.insee.fr/fr/statistiques/1?detail=keep')

    def test_atom_alternate_all_authors_and_distinct_dates(self):
        data = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>x</id><title>Research</title><link rel="self" href="https://export.arxiv.org/api/query"/><link rel="alternate" href="http://arxiv.org/abs/2611.12345v1"/><published>2026-11-05T23:30:00Z</published><updated>2026-11-07T01:00:00Z</updated><author><name>Author One</name></author><author><name>Author Two</name></author><summary>Original abstract.</summary></entry></feed>'''
        item = parse_feed(data, source('arxiv-ai-en'), NOW)[0]
        self.assertEqual(item['authors'], ['Author One', 'Author Two'])
        self.assertEqual(item['url'], 'https://arxiv.org/abs/2611.12345v1')
        self.assertEqual(item['publishedAt'], '2026-11-05T23:30:00Z')
        self.assertEqual(item['updatedAt'], '2026-11-07T01:00:00Z')
        self.assertEqual(item['contentKind'], 'research_preprint')

    def test_undated_article_not_promoted_by_updated_or_retrieval(self):
        data = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>x</id><title>Undated</title><link href="https://arxiv.org/abs/2611.12345"/><updated>2026-11-08T01:00:00Z</updated></entry></feed>'
        self.assertEqual(parse_feed(data, source('arxiv-ai-en'), NOW), [])

    def test_atom_updated_only_has_an_explicit_feed_date(self):
        data=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>x</id><title>News</title><link href="https://www.lesnumeriques.com/news.html"/><updated>2026-11-08T00:00:00Z</updated></entry></feed>'
        item=parse_feed(data,source('lesnumeriques'),NOW)[0]
        self.assertIsNone(item['publishedAt']);self.assertEqual(item['feedDateAt'],'2026-11-08T00:00:00Z')
        self.assertTrue(in_window(item,NOW))

    def test_ministry_local_zone_and_duplicate_author(self):
        data = rss('<item><title>Publication</title><author>Publication</author><link>https://www.economie.gouv.fr/test</link><pubDate>2026-11-06 12:00:00</pubDate></item>')
        item = parse_feed(data, source('economie'), NOW)[0]
        self.assertEqual(item['publishedAt'], '2026-11-06T11:00:00Z')
        self.assertEqual(item['authors'], [])

    def test_paris_midnight_and_eight_civil_dates(self):
        now = datetime(2026, 11, 8, 23, 5, tzinfo=timezone.utc)
        self.assertTrue(in_window({'publishedAt': '2026-11-01T23:00:00Z'}, now))
        self.assertFalse(in_window({'publishedAt': '2026-11-01T22:59:59Z'}, now))
        self.assertFalse(in_window({'publishedAt': '2026-11-09T01:00:00Z'}, now))
        self.assertTrue(in_window({'publishedDate': '2026-11-02'}, now))

    def test_dst_and_nonexistent_local_time(self):
        self.assertEqual(parse_date('2026-10-25T00:30:00Z')[0], '2026-10-25T00:30:00Z')
        self.assertEqual(parse_date('2026-10-25T01:30:00Z')[0], '2026-10-25T01:30:00Z')
        self.assertEqual(parse_date('2026-03-29T02:30:00'), (None, None))
        self.assertEqual(parse_date('2026-11-06'), (None, '2026-11-06'))

    def test_linuxfr_entries_do_not_depend_on_rights_metadata(self):
        def entry(path, rights):
            return f'<entry><id>{path}</id><title>Contribution</title><link href="https://linuxfr.org/{path}"/><published>2026-11-06T00:00:00Z</published><rights>{rights}</rights><author><name>Auteur</name></author><content type="html">&lt;p&gt;Un paragraphe original suffisamment long pour constituer un extrait.&lt;/p&gt;&lt;p&gt;Un autre paragraphe, non repris.&lt;/p&gt;</content></entry>'
        data = ('<feed xmlns="http://www.w3.org/2005/Atom">'+entry('journaux/test','https://creativecommons.org/licenses/by-sa/4.0/')+entry('liens/test','https://creativecommons.org/licenses/by-sa/4.0/')+entry('news/test','Tous droits réservés')+entry('news/sans-licence','')+'</feed>').encode()
        result = parse_feed(data, source('linuxfr-ai-fr'), NOW)
        self.assertEqual(len(result), 4)
        self.assertEqual(result[0]['contentKind'], 'opinion')
        self.assertEqual(result[0]['summary'], 'Un paragraphe original suffisamment long pour constituer un extrait.')

    def test_safe_text_and_untrusted_links(self):
        self.assertEqual(plain('Texte&amp;nbsp;?'), 'Texte ?')
        self.assertEqual(plain('<p>Texte <strong>visible</strong></p><script>danger()</script><iframe>hidden</iframe><img src="https://example.org/a">'), 'Texte visible')
        self.assertIsNone(canonical_url('javascript:alert(1)', source()))
        self.assertIsNone(canonical_url('https://evil.example/article', source()))
        self.assertIsNone(canonical_url('https://user:pass@www.insee.fr/test', source()))

    def test_empty_feed_and_invalid_xml_are_distinct(self):
        self.assertEqual(parse_feed(rss(), source(), NOW), [])
        with self.assertRaises(ValueError):
            parse_feed(b'<html>Access denied</html>', source(), NOW)
        with self.assertRaises(ValueError):
            parse_feed(b'<!DOCTYPE rss [<!ENTITY x "bad">]><rss/>', source(), NOW)
        with self.assertRaises(ValueError):
            parse_feed(rss(rss_item(), 'en'), source(), NOW)

    def initial(self):
        return collect_language([source()], 'fr', {}, NOW, lambda s, p: (rss(rss_item()), {'etag': 'v1'}))

    def test_empty_and_304_keep_bounded_history(self):
        first = self.initial()
        second = collect_language([source()], 'fr', first, NOW+timedelta(hours=1), lambda s, p: (rss(), {}))
        self.assertEqual(len(second['feed']['items']), 1)
        third = collect_language([source()], 'fr', second, NOW+timedelta(hours=2), lambda s, p: (None, {}))
        self.assertEqual(len(third['feed']['items']), 1)
        self.assertEqual(third['feed']['sources'][0]['status'], 'ok')

    def test_complete_outage_preserves_last_public_file(self):
        first = self.initial()
        def failed(s, p):
            raise OSError('unavailable')
        second = collect_language([source()], 'fr', first, NOW+timedelta(hours=1), failed)
        self.assertEqual(second['feed'], first['feed'])
        self.assertEqual(second['lastSuccessfulRefreshAt'], first['lastSuccessfulRefreshAt'])
        self.assertEqual(second['sourceState']['insee']['lastError'], 'OSError')

    def promotion_in_history(self):
        previous=self.initial()
        promo=copy.deepcopy(previous['history'][0]);promo.update(id='insee:cached-promo',title='Black Friday : un smartphone à 499 € (-30%)',url='https://www.insee.fr/fr/statistiques/cached-promo')
        previous['history'].append(promo);previous['feed']['items'].append(promo)
        return previous

    def test_cached_promotions_are_purged_even_on_304(self):
        previous=self.promotion_in_history()
        current=collect_language([source()],'fr',previous,NOW+timedelta(hours=1),lambda s,p:(None,{}))
        self.assertEqual(len(current['feed']['items']),1)
        self.assertEqual(len(current['history']),1)
        self.assertEqual(len(previous['feed']['items']),2,'Do not mutate the prior snapshot')

    def test_complete_outage_cannot_restore_a_cached_promotion(self):
        previous=self.promotion_in_history()
        def failed(s,p):raise OSError('unavailable')
        current=collect_language([source()],'fr',previous,NOW+timedelta(hours=1),failed)
        self.assertEqual(len(current['feed']['items']),1)
        self.assertEqual(current['lastSuccessfulRefreshAt'],previous['lastSuccessfulRefreshAt'])

    def test_new_commercial_category_removes_the_old_cached_item(self):
        previous=self.initial()
        revised=rss(rss_item().replace('</item>','<category>Bons Plans</category></item>'))
        current=collect_language([source()],'fr',previous,NOW+timedelta(hours=1),lambda s,p:(revised,{}))
        self.assertEqual(current['feed']['items'],[])
        self.assertEqual(current['history'],[])

    def test_partial_failure_does_not_discard_healthy_source(self):
        def fetch(s, p):
            if s['id'] == 'cnil':
                raise OSError('unavailable')
            return rss(rss_item()), {}
        result = collect_language([source(), source('cnil')], 'fr', {}, NOW, fetch)
        self.assertEqual(len(result['feed']['items']), 1)
        self.assertEqual([s['status'] for s in result['feed']['sources']], ['ok', 'unavailable'])

    def test_caps_budget_and_language_isolation(self):
        configured = source()
        configured['maxItems'] = 80
        result = collect_language([configured], 'fr', {}, NOW, lambda s, p: (rss(''.join(rss_item(i) for i in range(90))), {}))
        self.assertEqual(len(result['feed']['items']), 60)
        self.assertLess(len(json.dumps(result['feed']).encode()), 200_000)
        invalid = copy.deepcopy(result['feed'])
        invalid['items'][0]['language'] = 'en'
        with self.assertRaises(ValueError):
            validate_feed(invalid, 'fr')

    def test_busy_sources_share_the_public_selection(self):
        configured=[source('insee'),source('cnil')]
        for item in configured:item['maxItems']=40
        def fetch(item,prior):
            body=''.join(rss_item(i) for i in range(40))
            if item['id']=='cnil':body=body.replace('https://www.insee.fr/fr/statistiques/','https://www.cnil.fr/fr/article/')
            return rss(body),{}
        result=collect_language(configured,'fr',{},NOW,fetch)
        self.assertEqual(len(result['feed']['items']),60)
        self.assertEqual(sum(item['sourceId']=='insee' for item in result['feed']['items']),30)
        self.assertEqual(sum(item['sourceId']=='cnil' for item in result['feed']['items']),30)
        invalid = copy.deepcopy(result['feed'])
        invalid['items'][1]['id'] = invalid['items'][0]['id']
        with self.assertRaises(ValueError):
            validate_feed(invalid, 'fr')


class MemoryFile(io.BytesIO):
    def __init__(self, storage, name, writing):
        self.storage, self.name, self.writing = storage, name, writing
        super().__init__(b'' if writing else storage[name])

    def close(self):
        if self.writing:
            self.storage[self.name] = self.getvalue()
        super().close()


class FakeSFTP:
    def __init__(self, fail=False):
        self.files = {'/www/news-feed.fr.json': b'last-valid'}
        self.fail = fail

    def file(self, name, mode):
        return MemoryFile(self.files, name, 'w' in mode)

    def posix_rename(self, old, new):
        if self.fail:
            raise IOError('rename failed')
        self.files[new] = self.files.pop(old)

    def remove(self, name):
        if name not in self.files:
            raise IOError('not found')
        del self.files[name]


class TransferTests(unittest.TestCase):
    def test_atomic_replacement(self):
        remote = FakeSFTP()
        atomic_upload(remote, '/www/news-feed.fr.json', b'new-valid')
        self.assertEqual(remote.files, {'/www/news-feed.fr.json': b'new-valid'})

    def test_rename_failure_preserves_last_valid(self):
        remote = FakeSFTP(fail=True)
        with self.assertRaises(IOError):
            atomic_upload(remote, '/www/news-feed.fr.json', b'new-valid')
        self.assertEqual(remote.files, {'/www/news-feed.fr.json': b'last-valid'})


if __name__ == '__main__':
    unittest.main()
