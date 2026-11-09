import unittest
from editorial import is_blocked_source, is_excluded, is_political, is_promotion


def article(title,url='https://publisher.example/news/story',categories=None,**extra):
    return {'title':title,'url':url,'categories':categories or [],**extra}


class EditorialTests(unittest.TestCase):
    def test_all_bfm_sources_are_blocked_by_brand_or_host(self):
        for value in [{'id':'bfm-business'},{'name':'BFMTV'},{'sourceName':'BFM Tech'},
                      {'url':'https://www.bfmtv.com/economie/a.html'},
                      {'feedUrl':'https://tech.bfmtv.com/rss.xml'},
                      {'home':'https://bfmbusiness.fr'},
                      {'allowedHosts':['www.bfmtv.com']}]:
            with self.subTest(value=value):self.assertTrue(is_blocked_source(value))
        self.assertFalse(is_blocked_source({'name':'BBC Business','home':'https://www.bbc.com'}))

    def test_political_sections_and_publisher_categories(self):
        for item in [article('Une décision importante',url='https://publisher.example/politique/story'),
                     article('New technology report',categories=['US midterm elections 2026']),
                     article('AI chatbot complaints',categories=['AI','Politics','Business']),
                     article('Un bilan économique',categories=['Politiques publiques'])]:
            with self.subTest(item=item):self.assertTrue(is_political(item))

    def test_political_and_mixed_topic_headlines_in_both_languages(self):
        for title in ['Deux ans après le retour de Donald Trump au pouvoir, le bilan des climatologues',
                      'Les ministères présents au Salon des maires',
                      'Le Parlement vote une loi sur l’IA',
                      'Le gouvernement prépare le budget de l’État',
                      'Macron annonce de nouvelles mesures économiques',
                      'US midterms vote puts AI datacentres in the spotlight',
                      'Government considers banning under-16s from eBay',
                      'Brexit border posts cost £100 million',
                      'Nvidia launches investigation into CEO’s affair with suspected Chinese spy',
                      'Nvidia enquête sur les liens de son dirigeant avec une espionne chinoise',
                      'Ships near subsea cables amid Iran’s warnings to Trump']:
            with self.subTest(title=title):self.assertTrue(is_political(article(title)))

    def test_politics_only_in_publisher_excerpt_is_excluded(self):
        self.assertTrue(is_political(article('Une nouvelle mission sur les data centers',
            summary='Le Premier ministre a annoncé cette mission lors de sa campagne électorale.')))

    def test_non_political_economics_science_and_technical_policies_remain(self):
        for title in ['L’inflation baisse et les salaires augmentent',
                      'Nvidia présente un nouveau processeur pour l’IA',
                      'NASA announces a new space telescope',
                      'Une étude observe un nouveau mécanisme biologique',
                      'Apple modifie sa politique de confidentialité',
                      'Une politique de sécurité pour les mots de passe',
                      'OpenAI updates its privacy policy',
                      'Le président de Nvidia présente ses résultats financiers']:
            with self.subTest(title=title):self.assertFalse(is_political(article(title)))

    def test_economy_label_cannot_override_politics_or_blocked_publisher(self):
        self.assertTrue(is_excluded(article('Trump annonce une baisse des taxes',categories=['Economy'])))
        self.assertTrue(is_excluded(article('Une découverte scientifique',sourceName='BFM Business')))

    def test_commercial_sections_and_encoded_paths(self):
        for path in ['/bons-plans/phone.html','/%62ons-plans/phone.html','/deals/phone',
                     '/shopping/phone','/guides-d-achat/best-tv','/buying-guides/tvs']:
            with self.subTest(path=path):self.assertTrue(is_promotion(article('A product',url='https://publisher.example'+path)))

    def test_publisher_commercial_categories(self):
        for category in ['Bons Plans','Bons plans TV','Guides d’achat gaming','Codes promo',
                         'Buying guides','Sponsored content']:
            with self.subTest(category=category):self.assertTrue(is_promotion(article('A product',categories=[category])))

    def test_black_friday_product_prices_and_discounts(self):
        for title in ['Actualité : Black Friday 2026 – L’aspirateur Dyson à 248,99 €',
                      'Black Friday : le smartphone Samsung à 499 € (-13%)',
                      'Black Friday avant l’heure : ce projecteur à moins de 100 euros',
                      'Cyber Monday: the best tech deals',
                      'Prime Day: headphones for $99, 30% off']:
            with self.subTest(title=title):self.assertTrue(is_promotion(article(title)))

    def test_offers_without_a_shopping_event(self):
        for title in ['Code promo : économisez 50 euros sur ce casque',
                      'Vente flash : un ordinateur à prix cassé',
                      'This laptop is $500 with 25% off',
                      'Save $100 on these headphones',
                      'Le Google Pixel passe sous les 700 euros',
                      'These headphones are now only $99',
                      'Actualité : Cette table de cuisson présente le meilleur rapport qualité / prix de notre comparatif',
                      'The best laptops you can buy in 2026',
                      'Try this VPN with a free trial']:
            with self.subTest(title=title):self.assertTrue(is_promotion(article(title)))

    def test_editorial_news_is_preserved_even_when_it_mentions_prices(self):
        for title in ['Black Friday : les dépenses des consommateurs devraient dépasser 10 milliards',
                      'Black Friday: retailers face lower profits despite heavy discounts',
                      'Enquête sur les fausses promotions du Black Friday',
                      'Black Friday : les risques de cybersécurité pour les commerçants',
                      'Apple annonce un nouvel iPhone à 799 euros',
                      'OpenAI lance un abonnement à 8 euros',
                      'NASA announces a $1 million Moon base challenge',
                      'Les actions de Samsung chutent de 20 % en Bourse',
                      'Un nouveau processeur consomme 20 % de moins',
                      'Une étude observe 30 % de réduction du risque de cancer',
                      'Au Pakistan, des robots-serveurs offrent un avant-goût de l’avenir']:
            with self.subTest(title=title):self.assertFalse(is_promotion(article(title)))

    def test_advertising_in_summary_does_not_hide_a_real_article(self):
        self.assertFalse(is_promotion(article('A new discovery in quantum computing',
            summary='Subscribe to our newsletter for Black Friday deals and coupons.')))


if __name__=='__main__':unittest.main()
