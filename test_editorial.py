import unittest
from editorial import is_promotion


def article(title,url='https://publisher.example/news/story',categories=None,**extra):
    return {'title':title,'url':url,'categories':categories or [],**extra}


class EditorialTests(unittest.TestCase):
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
