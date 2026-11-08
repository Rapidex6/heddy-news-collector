"""Bounded publisher image discovery. Image bytes are never downloaded or stored."""
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

MAX_PAGE_BYTES=1_000_000
MAX_LOOKUPS=8
TIMEOUT=10
USER_AGENT='HeddyNewsCollector/1.0 (+https://heddy.fr/news; contact@heddy.fr)'
MEDIA_SPECS={s['id']:s for s in json.loads(Path(__file__).with_name('sources.json').read_text(encoding='utf-8'))['sources']}

def public_https(value):
    try:
        url=urllib.parse.urlsplit(value)
        if url.scheme!='https' or not url.hostname or url.username or url.password or url.port not in (None,443):return False
        host=url.hostname.lower()
        if '.' not in host or host.endswith(('.local','.localhost','.internal')):return False
        try:return ipaddress.ip_address(host).is_global
        except ValueError:return True
    except (ValueError,TypeError):return False

def host_matches(host,allowed):
    return any(host==base or host.endswith('.'+base) for base in allowed)

def valid_image(image,source_id):
    source=MEDIA_SPECS.get(source_id)
    if not source or not isinstance(image,dict):return False
    if not all(isinstance(image.get(key),str) and len(image[key])<=2048 for key in ('src','alt','attribution')):return False
    if not public_https(image['src']):return False
    host=urllib.parse.urlsplit(image['src']).hostname
    if not host_matches(host,source.get('mediaHosts',source['allowedHosts'])):return False
    if image.get('licenseUrl') is not None and not public_https(image['licenseUrl']):return False
    return True

def make_image(value,source,title,alt=''):
    if not value:return None
    url=urllib.parse.urljoin(source.get('home') or source['feedUrl'],unescape(value).strip())
    parsed=urllib.parse.urlsplit(url)
    if parsed.hostname in {'platform.theverge.com','www.nasa.gov'}:
        query=dict(urllib.parse.parse_qsl(parsed.query,keep_blank_values=True))
        query['w']='1200'
        if parsed.hostname=='platform.theverge.com':query['quality']='80'
        url=urllib.parse.urlunsplit((parsed.scheme,parsed.netloc,parsed.path,urllib.parse.urlencode(query),''))
    image={'src':url,'alt':alt or title,'attribution':source['name'],'kind':'publisher_image'}
    return image if valid_image(image,source['id']) else None

class Images(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.images=[];self.meta=[]
    def handle_starttag(self,tag,attrs):
        data=dict(attrs)
        if tag=='img':self.images.append(data)
        if tag=='meta' and (data.get('property') or data.get('name') or '').lower() in {'og:image','og:image:secure_url','twitter:image','twitter:image:src'}:
            self.meta.append(data.get('content',''))

def image_candidates(elements,source,title):
    candidates=[]
    for position,element in enumerate(elements):
        value=element.get('url') or element.get('src') or element.get('data-src')
        if not value:continue
        image=make_image(value,source,title,element.get('alt',''))
        if not image:continue
        try:width=int(element.get('width',0));height=int(element.get('height',0))
        except (ValueError,TypeError):width=height=0
        if width==1 or height==1:continue
        if re.search(r'/avatars?/|gravatar\.com|tracking|spacer\.gif',image['src'],re.I):continue
        score=width*max(height,1)
        candidates.append((score,-position,image))
    return max(candidates,key=lambda entry:entry[:2])[2] if candidates else None

def feed_image(entry,source,title):
    local=lambda tag:tag.rsplit('}',1)[-1].lower()
    elements=[]
    for node in entry.iter():
        name=local(node.tag);data=dict(node.attrib)
        if name in {'thumbnail','enclosure','content'} and data.get('url'):
            kind=data.get('type','')
            if name=='thumbnail' or kind.startswith('image/') or data.get('medium')=='image' or re.search(r'\.(?:jpe?g|png|webp|avif|gif)(?:[?#]|$)',data['url'],re.I):
                elements.append(data)
        if name=='img':elements.append(data)
        if name in {'description','summary','content','encoded'} and node.text:
            parser=Images();parser.feed(node.text);elements.extend(parser.images)
    image=image_candidates(elements,source,title)
    if image:image['origin']='feed'
    return image

def extract_image(html,page_url,source_id,title):
    source=MEDIA_SPECS.get(source_id)
    if not source:return None
    if source_id=='eurostat-en':
        related=html.lower().find('you might also like')
        if related>=0:html=html[:related]
    parser=Images();parser.feed(html)
    # Eurostat's full chart is more useful than its generic cover.
    if source_id=='eurostat-en':
        chart=image_candidates([e for e in parser.images if '/eurostat/o/adaptive-media/image/' in e.get('src','')],source,title)
        if chart:return {**chart,'origin':'page'}
    for value in parser.meta:
        image=make_image(urllib.parse.urljoin(page_url,value),source,title)
        if image:return {**image,'origin':'page'}
    image=image_candidates(parser.images,source,title)
    return {**image,'origin':'page'} if image else None

class PublisherRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self,hosts):super().__init__();self.hosts=hosts
    def redirect_request(self,request,fp,code,msg,headers,newurl):
        url=urllib.parse.urlsplit(newurl)
        if not public_https(newurl) or url.hostname not in self.hosts:
            raise ValueError('Unapproved publisher redirect')
        return super().redirect_request(request,fp,code,msg,headers,newurl)

def fetch_image(item,source):
    parsed=urllib.parse.urlsplit(item['url'])
    if not public_https(item['url']) or parsed.hostname not in source['allowedHosts']:raise ValueError('Unapproved page URL')
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
        source=active.get(item['sourceId'])
        if not source:continue
        if item.get('image') and valid_image(item['image'],item['sourceId']):
            normalized=make_image(item['image']['src'],source,item['title'],item['image']['alt'])
            if normalized:item['image']['src']=normalized['src']
            if item['image'].get('origin')=='feed' or source.get('mediaMode')!='page':continue
        if source.get('mediaMode')!='page':continue
        cached=previous.get(item['id'],{});signature='v2|'+item['url']+'|'+str(item.get('updatedAt'))
        try:age=(now-datetime.fromisoformat(cached.get('checkedAt','').replace('Z','+00:00'))).total_seconds()
        except ValueError:age=float('inf')
        current=cached
        if (cached.get('signature')!=signature or age>=86400) and lookups<MAX_LOOKUPS:
            lookups+=1
            try:
                image=fetch(item,source)
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
