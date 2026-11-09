"""Keep non-political publisher news, excluding BFM and shopping offers."""
import re
import unicodedata
from html import unescape
from urllib.parse import unquote, urlsplit


def normalized(value):
    value=unicodedata.normalize('NFKD',unescape(str(value or ''))).casefold()
    return ' '.join(''.join(c for c in value if not unicodedata.combining(c)).replace('’',"'").replace('−','-').split())


def words(value):
    return re.sub(r'[\W_]+',' ',normalized(value)).strip()


BFM_HOSTS={'bfmtv.com','bfmbusiness.com','bfmbusiness.fr','bfm.fr'}
POLITICAL_SECTIONS={'politique','politiques','politics','political','geopolitique','geopolitics',
    'election','elections','elections americaines','elections legislatives','us politics','uk politics',
    'government','gouvernement','foreign policy','trade policy'}
POLITICAL_TAG=re.compile(r'\b(?:politics|political|politiques?|geopolitiques?|geopolitics|elections?|government|gouvernement|parliament|parlement|brexit)\b')
POLITICAL_TEXT=re.compile(r'\b(?:politiques?|politics|political|geopolitiques?|geopolitics|elections?|electoral|electorales?|scrutins?|referendums?|midterms?|votes?|brexit|gouvernements?|government|ministres?|ministeres?|ministers?|prime minister|premier ministre|maires?|deputes?|senateurs?|senators?|senat|senate|congress|congres|parlement|parliament|elysee|matignon|white house|maison blanche|house of commons|assemblee nationale|republicains?|democrates?|democrats?|republicans?|labour party|conservative party|rassemblement national|france insoumise|parti socialiste|partis? politiques?|campagne presidentielle|presidentielle|president de la republique|president americain|president francais|president chinois|trump|biden|macron|melenchon|bardella|retailleau|edouard philippe|gabriel attal|marine le pen|bayrou|barnier|starmer|sunak|poutine|putin|zelensky|zelenskyy|netanyahu|netanyahou|xi jinping|ursula von der leyen|orban|meloni|guerres?|wars?|invasion|geopolitical|diplomatie|diplomatic|sanctions|budget de l.etat|budget federal|loi de finances|reforme des retraites|plan de relance)\b')
TECHNICAL_POLICY=re.compile(r'\bpolitiques? (?:de |des |d.)?(?:confidentialite|cookies|securite|moderation|retours?|prix|tarifaires?|mots de passe)\b')
STATE_ESPIONAGE=re.compile(r'\b(?:(?:chinese|russian|iranian|foreign|soviet|state) (?:spy|spies|espionage)|espions? (?:chinois|russes?|iraniens?|etrangers?)|espionnes? (?:chinoises?|russes?|iraniennes?|etrangeres?))\b')


def is_blocked_source(source):
    names=' '.join(words(source.get(key)) for key in ['id','name','sourceId','sourceName','shortName'])
    if re.search(r'\bbfm(?:tv|business)?\b',names):return True
    hosts=list(source.get('allowedHosts') or [])
    for key in ['url','home','feedUrl']:
        try:hosts.append(urlsplit(source.get(key) or '').hostname or '')
        except ValueError:continue
    return any(host.lower().rstrip('.')==blocked or host.lower().rstrip('.').endswith('.'+blocked)
               for host in hosts for blocked in BFM_HOSTS)


def is_political(item):
    try:
        segments=[words(segment) for segment in unquote(urlsplit(item.get('url','')).path).split('/')]
    except ValueError:segments=[]
    if any(segment in POLITICAL_SECTIONS for segment in segments):return True
    if any(POLITICAL_TAG.search(words(category)) for category in item.get('categories') or []):return True
    # Mixed economy/technology stories are excluded too when their title or
    # publisher excerpt covers politics. A company's privacy policy is technical.
    text=TECHNICAL_POLICY.sub('',normalized(str(item.get('title') or '')+' '+str(item.get('summary') or '')))
    return bool(POLITICAL_TEXT.search(text) or STATE_ESPIONAGE.search(text))


def is_excluded(item):
    return is_blocked_source(item) or is_political(item) or is_promotion(item)


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
BUYING_PICK=re.compile(r'\b(?:meilleur rapport qualite\s*/?\s*prix|best (?:[\w-]+ ){0,5}(?:to buy|you can buy))\b')
PRICE_DROP=re.compile(r'\b(?:passe (?:sous|a)|tombe a|chute a|descend (?:sous|a)|desormais a|now (?:only|just)|on sale for|down to)\b')


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
    if BUYING_PICK.search(title):return True
    if re.search(r'^(?:actualite\s*:\s*)?(?:promo|promotion|deal|sponsored|sponsorise)\s*[:\[–-]',title):return True
    priced=bool(PRICE.search(title));discounted=bool(DISCOUNT.search(title))
    if priced and PRICE_DROP.search(title):return True
    if CAMPAIGN.search(title) and (priced or discounted or OFFER_WORDS.search(title)):return True
    if discounted and (priced or OFFER_WORDS.search(title)):return True
    return bool(CALL_TO_BUY.search(title) and (priced or discounted))
