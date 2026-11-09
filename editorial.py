"""Keep publisher news; exclude shopping offers and buying guides."""
import re
import unicodedata
from html import unescape
from urllib.parse import unquote, urlsplit


def normalized(value):
    value=unicodedata.normalize('NFKD',unescape(str(value or ''))).casefold()
    return ' '.join(''.join(c for c in value if not unicodedata.combining(c)).replace('’',"'").replace('−','-').split())


def words(value):
    return re.sub(r'[\W_]+',' ',normalized(value)).strip()


SECTIONS={'shopping','promos','promotions','offres','deals','offers','coupons','vouchers','discounts','best picks'}
CATEGORIES=SECTIONS|{'bon plan','bons plans','bonne affaire','bonnes affaires','code promo','codes promo',
    'guide d achat','guides d achat','guide achat','guides achat','buying guide','buying guides',
    'sponsored','sponsored content','advertorial','contenu sponsorise','article sponsorise','partenariat commercial'}
PRICE=re.compile(r'[$€£]\s*\d|\b\d[\d\s.,]{0,18}\s*(?:[$€£]|\b(?:euros?|eur|usd|dollars?|gbp|pounds?)\b)')
DISCOUNT=re.compile(r'-\s*\d{1,3}\s*%|\b\d{1,3}\s*%\s*(?:off\b|de\s+(?:remise|reduction))')
CAMPAIGN=re.compile(r'\b(?:black[ -]*friday|cyber[ -]*monday|prime[ -]*day|french[ -]*days|soldes)\b')
EDITORIAL=re.compile(r'\b(?:chiffre d.affaires|benefices?|revenus?|bourse|inflation|chomage|bitcoin|cryptomonnaies|spending|revenue|earnings|shares|stock market|retailers?|retail sales|consommateurs?|commercants?|depenses?|enquete|fraude|arnaques?|cybersecurite|cybersecurity|reglementation|regulation|environmental impact|impact environnemental|etude|recherche|research|study|risque|risk)\b')
DIRECT_OFFER=re.compile(r'\b(?:bons? plans?|codes? promo|coupons?|cashback|ventes? flash|essai gratuit|free trial|offre de bienvenue|welcome offer|prix (?:casse|brade|sacrifie|imbattable)|meilleur prix|best price|lowest (?:ever )?price|record low price)\b')
OFFER_WORDS=re.compile(r'\b(?:deals?|discounts?|remises?|reductions?|promos?|promotions?|offres?|acheter|buying guide|sale|off)\b')
CALL_TO_BUY=re.compile(r'\b(?:economisez|profitez|ne ratez pas|a saisir|save|grab|snag)\b')


def is_promotion(item):
    try:
        segments=[words(segment) for segment in unquote(urlsplit(item.get('url','')).path).split('/')]
    except ValueError:
        segments=[]
    for segment in segments:
        if segment in SECTIONS or re.match(r'^(?:bons? plans?|codes? promo|guides? d ?achat|buying guides?)(?: |$)',segment):
            return True
    for category in item.get('categories') or []:
        category=words(category)
        if category in CATEGORIES or re.match(r'^(?:bons? plans?|codes? promo|guides? d achat|buying guides?)(?: |$)',category):
            return True
    title=normalized(item.get('title'))
    # News about retail, earnings, fraud or shopping events is still news.
    if EDITORIAL.search(title):return False
    if DIRECT_OFFER.search(title):return True
    if re.search(r'^(?:actualite\s*:\s*)?(?:promo|promotion|deal|sponsored|sponsorise)\s*[:\[–-]',title):return True
    priced=bool(PRICE.search(title));discounted=bool(DISCOUNT.search(title))
    if CAMPAIGN.search(title) and (priced or discounted or OFFER_WORDS.search(title)):return True
    if discounted and (priced or OFFER_WORDS.search(title)):return True
    return bool(CALL_TO_BUY.search(title) and (priced or discounted))
