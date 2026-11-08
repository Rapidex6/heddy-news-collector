"""Bounded image-URL discovery. No image bytes, PDF, proxy or tracking service.

Eurostat: its own article charts, excluding the separately licensed stock cover.
CNIL: original illustrations, CC BY-NC-ND; personal non-commercial use confirmed.
"""
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

MAX_PAGE_BYTES=1_000_000
MAX_LOOKUPS=6
TIMEOUT=10
USER_AGENT='HeddyNewsCollector/1.0 (+https://heddy.fr/news; contact@heddy.fr)'
# CNIL also hosts third-party artwork (for example the EDPB's Privacy for Kids).
# Its general illustration licence cannot be assigned to those pictures.
CNIL_REVIEWED_FILES={'recherche_sante_interne.png','rejeu-session-part.png','rejeu-session-pro.png'}
MEDIA_SPECS={
    'eurostat-en':{'hosts':{'ec.europa.eu'},'path':'/eurostat/o/adaptive-media/image/',
                   'licenseName':'CC BY 4.0','licenseUrl':'https://creativecommons.org/licenses/by/4.0/',
                   'attribution':'Eurostat / European Union. Original statistical chart.', 'kind':'chart'},
    'cnil':{'hosts':{'www.cnil.fr','cnil.fr'},'path':'/sites/default/files/styles/contenu_generique_visuel/',
            'licenseName':'CC BY-NC-ND 4.0','licenseUrl':'https://creativecommons.org/licenses/by-nc-nd/4.0/',
            'attribution':'Source : CNIL – https://www.cnil.fr. Original illustration, displayed unchanged.', 'kind':'illustration'}
}

def valid_image(image,source_id):
    spec=MEDIA_SPECS.get(source_id)
    if not spec or not isinstance(image,dict):return False
    if not all(isinstance(image.get(key),str) and len(image[key])<=2048 for key in ('src','alt','attribution','licenseName','licenseUrl')):return False
    try:
        url=urllib.parse.urlsplit(image['src'])
        return (url.scheme=='https' and url.hostname in spec['hosts'] and not url.username and not url.password
                and url.port in (None,443) and url.path.startswith(spec['path'])
                and (source_id!='cnil' or urllib.parse.unquote(url.path).rsplit('/',1)[-1] in CNIL_REVIEWED_FILES)
                and image['licenseUrl']==spec['licenseUrl'] and image['licenseName']==spec['licenseName'])
    except ValueError:return False

class Images(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.images=[]
    def handle_starttag(self,tag,attrs):
        if tag=='img':self.images.append(dict(attrs))

def extract_image(html,page_url,source_id,title):
    spec=MEDIA_SPECS.get(source_id)
    if not spec:return None
    # Related-article graphics must never become the current article's preview.
    if source_id=='eurostat-en':
        related=html.lower().find('you might also like')
        if related>=0:html=html[:related]
    parser=Images();parser.feed(html)
    for element in parser.images:
        url=urllib.parse.urljoin(page_url,(element.get('src') or '').strip())
        if re.search(r'shutterstock|adobestock|stock\.adobe|gettyimages|istockphoto',url,re.I):continue
        image={'src':url,'alt':element.get('alt') or title,'attribution':spec['attribution'],
               'licenseName':spec['licenseName'],'licenseUrl':spec['licenseUrl'],'kind':spec['kind']}
        if valid_image(image,source_id):return image
    return None

class PublisherRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self,hosts):super().__init__();self.hosts=hosts
    def redirect_request(self,request,fp,code,msg,headers,newurl):
        url=urllib.parse.urlsplit(newurl)
        if url.scheme!='https' or url.hostname not in self.hosts or url.username or url.password:
            raise ValueError('Unapproved publisher redirect')
        return super().redirect_request(request,fp,code,msg,headers,newurl)

def fetch_image(item,source):
    # Only publisher HTML metadata is read. Remote images are loaded by visitors.
    parsed=urllib.parse.urlsplit(item['url'])
    if parsed.scheme!='https' or parsed.hostname not in source['allowedHosts']:raise ValueError('Unapproved page URL')
    opener=urllib.request.build_opener(PublisherRedirect(set(source['allowedHosts'])))
    request=urllib.request.Request(item['url'],headers={'User-Agent':USER_AGENT,'Accept':'text/html'})
    with opener.open(request,timeout=TIMEOUT) as response:
        if 'text/html' not in response.headers.get('Content-Type',''):raise ValueError('Metadata is not HTML')
        body=response.read(MAX_PAGE_BYTES+1)
        if len(body)>MAX_PAGE_BYTES:raise ValueError('Metadata page exceeds limit')
        return extract_image(body.decode(response.headers.get_content_charset() or 'utf-8','replace'),response.url,source['id'],item['title'])

def enrich_media(state,sources,now,fetch=fetch_image):
    stamp=now.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
    if state['feed'].get('lastSuccessfulRefreshAt')!=stamp:return state
    active={source['id']:source for source in sources};previous=state.get('mediaState',{});lookups=0
    for item in state['feed']['items']:
        if item['sourceId'] not in MEDIA_SPECS:continue
        cached=previous.get(item['id'],{});signature=item['url']+'|'+str(item.get('updatedAt'))
        try:age=(now-datetime.fromisoformat(cached.get('checkedAt','').replace('Z','+00:00'))).total_seconds()
        except ValueError:age=float('inf')
        current=cached
        if (cached.get('signature')!=signature or age>=86400) and lookups<MAX_LOOKUPS:
            lookups+=1
            try:
                image=fetch(item,active[item['sourceId']])
                if image is not None and not valid_image(image,item['sourceId']):raise ValueError('Unapproved image')
                current={'signature':signature,'checkedAt':stamp,'image':image}
            except (OSError,ValueError,urllib.error.URLError,socket.timeout) as error:
                current={**cached,'signature':signature,'checkedAt':stamp,'lastError':type(error).__name__}
            previous[item['id']]=current
        image=current.get('image')
        if image and valid_image(image,item['sourceId']):item['image']=image
        else:item.pop('image',None)
    retained={item['id'] for item in state.get('history',[])}
    state['mediaState']={key:value for key,value in previous.items() if key in retained}
    return state
