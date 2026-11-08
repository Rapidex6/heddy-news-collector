"""Bounded RSS/Atom collection. Public text metadata only; no linked pages/media.

python collector.py --output ../public --state .state
State is restored from a dedicated Git branch in production, never an expiring cache.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from html import unescape
from pathlib import Path
from zoneinfo import ZoneInfo
from media import enrich_media, valid_image

PARIS = ZoneInfo("Europe/Paris")
UTC = timezone.utc
MAX_BYTES = 2_000_000
FEED_BUDGET = 200_000
MAX_ITEMS = 30
TIMEOUT = 25
USER_AGENT = "HeddyNewsCollector/1.0 (+https://heddy.fr/news; contact@heddy.fr)"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def stamp(value):
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def local_name(tag):
    return tag.rsplit("}", 1)[-1].lower()


def children(element, name):
    return [child for child in element if local_name(child.tag) == name]


def field(element, *names):
    for name in names:
        values = children(element, name)
        if values:
            return "".join(values[0].itertext()).strip()
    return ""


class SafeText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "iframe", "object", "svg", "noscript"}:
            self.hidden.append(tag)
        if not self.hidden and tag in {"p", "br", "div", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.hidden and tag == self.hidden[-1]:
            self.hidden.pop()
        if not self.hidden and tag in {"p", "div", "li"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain(value):
    parser = SafeText()
    parser.feed(value or "")
    return " ".join(unescape("".join(parser.parts)).split())


def excerpt(value):
    # Take an original complete paragraph, without rewriting its words.
    parser = SafeText()
    parser.feed(value or "")
    paragraphs = [" ".join(unescape(p).split()) for p in "".join(parser.parts).split("\n")]
    return next((p for p in paragraphs if len(p) >= 40), "")


def parse_date(value):
    value = (value or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            return None, datetime.strptime(value, "%Y-%m-%d").date().isoformat()
        except ValueError:
            return None, None
    if not value:
        return None, None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            result = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return None, None
    if result.tzinfo is None:
        # The ministry feed uses local Paris time, not the collector's machine zone.
        result = result.replace(tzinfo=PARIS)
        if result.astimezone(UTC).astimezone(PARIS).replace(tzinfo=None) != result.replace(tzinfo=None):
            return None, None
    return stamp(result), None


def publication_day(item):
    if item.get("publishedAt"):
        return datetime.fromisoformat(item["publishedAt"].replace("Z", "+00:00")).astimezone(PARIS).date()
    if item.get("publishedDate"):
        return datetime.strptime(item["publishedDate"], "%Y-%m-%d").date()
    return None


def in_window(item, now):
    day = publication_day(item)
    today = now.astimezone(PARIS).date()
    if day is None or not today - timedelta(days=7) <= day <= today:
        return False
    return not item.get("publishedAt") or datetime.fromisoformat(item["publishedAt"].replace("Z", "+00:00")) <= now


def canonical_url(value, source):
    try:
        url = urllib.parse.urlsplit(value.strip())
        if url.scheme not in {"http", "https"} or url.hostname not in source["allowedHosts"] or url.username or url.password:
            return None
        query = [(k, v) for k, v in urllib.parse.parse_qsl(url.query, keep_blank_values=True)
                 if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid"}]
        return urllib.parse.urlunsplit(("https", url.netloc.lower(), url.path or "/", urllib.parse.urlencode(query), ""))
    except ValueError:
        return None


def parse_feed(data, source, now):
    if len(data) > MAX_BYTES or re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", data, re.I):
        raise ValueError("Unsafe or oversized XML")
    root = ET.fromstring(data)
    if local_name(root.tag) not in {"rss", "rdf", "feed"}:
        raise ValueError("Response is not RSS/Atom")
    atom = local_name(root.tag) == "feed"
    channel = root if atom else next((e for e in root if local_name(e.tag) == "channel"), root)
    declared = channel.get(XML_LANG) or field(channel, "language")
    if declared and declared.lower().split("-")[0].split("_")[0] != source["language"]:
        raise ValueError("Feed language disagrees with registry")
    entries = children(root, "entry") if atom else [e for e in root.iter() if local_name(e.tag) == "item"]
    items = []
    for entry in entries:
        entry_language = entry.get(XML_LANG)
        if entry_language and not entry_language.lower().startswith(source["language"]):
            continue
        title = plain(field(entry, "title"))
        links = children(entry, "link")
        link = next((e.get("href") for e in links if e.get("href") and e.get("rel", "alternate") == "alternate"), "") if atom else field(entry, "link")
        url = canonical_url(link or field(entry, "id", "guid"), source)
        if not title or not url:
            continue
        published, published_date = parse_date(field(entry, "published" if atom else "pubdate", "date"))
        updated, _ = parse_date(field(entry, "updated"))
        rights = field(entry, "rights", "copyright")
        if re.search(r"all rights reserved|tous droits réservés|by-nc", rights, re.I):
            continue
        summary = field(entry, "summary") if atom else field(entry, "description")
        summary_kind = "publisher_excerpt" if summary else "none"
        kind = "news"
        if source["id"] == "linuxfr-ai-fr":
            article_path = urllib.parse.urlsplit(url).path
            if not article_path.startswith(("/news/", "/journaux/")) or not re.search(r"creativecommons\.org/licenses/by-sa/4\.0|CC\s*BY[ -]SA\s*4\.0", rights, re.I):
                continue
            summary = excerpt(field(entry, "content"))
            summary_kind = "licensed_excerpt" if summary else "none"
            kind = "opinion" if article_path.startswith("/journaux/") else "community_news"
        if source["id"] == "arxiv-ai-en":
            if not urllib.parse.urlsplit(url).path.startswith("/abs/"):
                continue
            kind, summary_kind = "research_preprint", "research_abstract" if summary else "none"
        authors = []
        for author in children(entry, "author") + children(entry, "creator"):
            name = plain(field(author, "name") or "".join(author.itertext()))
            if name and name != title and name not in authors:
                authors.append(name)
        summary = plain(summary) or None
        # Never cut protected publisher wording to fit a byte budget.
        if summary and len(summary.encode("utf-8")) > 20_000:
            summary, summary_kind = None, "none"
        identity = field(entry, "id", "guid") or url
        if source["id"] == "arxiv-ai-en":
            identity = re.sub(r"v\d+$", "", identity)
        item = {"id": source["id"] + ":" + hashlib.sha256(identity.encode()).hexdigest()[:24],
                "sourceId": source["id"], "sourceName": source["name"], "sourceType": source["type"],
                "title": title, "url": url, "publishedAt": published, "publishedDate": published_date,
                "updatedAt": updated, "retrievedAt": stamp(now), "topics": source["topics"],
                "summary": summary, "summaryKind": summary_kind, "authors": authors,
                "licenseName": source["licence"], "licenseUrl": source["licenseUrl"],
                "attribution": source["attribution"], "language": source["language"], "contentKind": kind}
        if in_window(item, now):
            items.append(item)
    return items


def fetch_feed(source, previous):
    if source["id"] == "arxiv-ai-en":
        # One connection only. Also safe across back-to-back serial workflow runs.
        time.sleep(3)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/atom+xml, application/rss+xml, application/xml, text/xml"}
    for field_name, header in [("etag", "If-None-Match"), ("lastModified", "If-Modified-Since")]:
        if previous.get(field_name):
            headers[header] = previous[field_name]
    request = urllib.request.Request(source["feedUrl"], headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            if urllib.parse.urlsplit(response.url).scheme != "https":
                raise ValueError("Non-TLS feed redirect")
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError("Feed exceeds size limit")
            return data, {"etag": response.headers.get("ETag"), "lastModified": response.headers.get("Last-Modified")}
    except urllib.error.HTTPError as error:
        if error.code == 304:
            return None, {"etag": previous.get("etag"), "lastModified": previous.get("lastModified")}
        raise


def compact_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def validate_feed(feed, language):
    if feed.get("schemaVersion") != 1 or feed.get("language") != language or feed.get("timeZone") != "Europe/Paris":
        raise ValueError("Invalid feed contract")
    if len(feed["items"]) > MAX_ITEMS or len(compact_json(feed)) > FEED_BUDGET:
        raise ValueError("Feed budget exceeded")
    ids = set()
    for item in feed["items"]:
        if item.get("language") != language or item["sourceId"] not in {s["id"] for s in feed["sources"]}:
            raise ValueError("Mixed language or unknown source")
        if not isinstance(item.get("id"), str) or item["id"] in ids or not isinstance(item.get("title"), str):
            raise ValueError("Invalid item identity")
        ids.add(item["id"])
        if not isinstance(item.get("authors"), list) or not all(isinstance(a, str) for a in item["authors"]):
            raise ValueError("Invalid authors")
        if not item.get("publishedAt") and not item.get("publishedDate"):
            raise ValueError("Missing publication date")
        if item.get("publishedAt") and not parse_date(item["publishedAt"])[0]:
            raise ValueError("Invalid publication date")
        if item.get("publishedDate") and not parse_date(item["publishedDate"])[1]:
            raise ValueError("Invalid publication day")
        for name in ["retrievedAt", "updatedAt"]:
            if item.get(name) and not parse_date(item[name])[0]:
                raise ValueError("Invalid item timestamp")
        if item.get('image') is not None and not valid_image(item['image'],item['sourceId']):
            raise ValueError('Unsafe article image')
        if not item["url"].startswith("https://") or not item["licenseUrl"].startswith("https://"):
            raise ValueError("Unsafe item URL")
    return feed


def collect_language(sources, language, previous, now, fetch=fetch_feed):
    previous_sources = previous.get("sourceState", {})
    history = {item["id"]: item for item in previous.get("history", []) if in_window(item, now)}
    states, statuses, successes = {}, [], 0
    for source in sources:
        prior = previous_sources.get(source["id"], {})
        try:
            data, headers = fetch(source, prior)
            entries = parse_feed(data, source, now) if data is not None else []
            if data is None and not prior.get("lastSuccessAt"):
                raise ValueError("304 without a prior valid result")
            for item in entries:
                history[item["id"]] = item
            current = {**prior, **headers, "lastSuccessAt": stamp(now)}
            status, successes = "ok", successes + 1
        except (OSError, ValueError, ET.ParseError, urllib.error.URLError, socket.timeout) as error:
            current = dict(prior)
            current["lastError"] = type(error).__name__
            status = "stale" if prior.get("lastSuccessAt") else "unavailable"
        states[source["id"]] = current
        relevant = [item for item in history.values() if item["sourceId"] == source["id"]]
        newest = max((item["publishedAt"] or item["publishedDate"] for item in relevant), default=None)
        statuses.append({"id": source["id"], "name": source["name"], "type": source["type"],
                         "status": status, "lastSuccessAt": current.get("lastSuccessAt"),
                         "newestPublicationAt": newest, "licenseName": source["licence"],
                         "licenseUrl": source["licenseUrl"], "policyUrl": source["policyUrl"]})
    active = {s["id"]: s for s in sources}
    unique, counts, selected = set(), {}, []
    ordered = sorted(history.values(), key=lambda i: (i.get("publishedAt") or i.get("publishedDate") or "", i.get("updatedAt") or "", i.get("retrievedAt") or "", i["id"]), reverse=True)
    retained = []
    for item in ordered:
        source_id = item["sourceId"]
        if source_id not in active or item["language"] != language:
            continue
        # Bounded eight-day archive; independent of the narrower public selection.
        if sum(1 for old in retained if old["sourceId"] == source_id) < 120:
            retained.append(item)
        if item["url"] in unique or counts.get(source_id, 0) >= active[source_id]["maxItems"] or len(selected) >= MAX_ITEMS:
            continue
        unique.add(item["url"])
        counts[source_id] = counts.get(source_id, 0) + 1
        selected.append(item)
    refreshed = stamp(now) if successes else previous.get("lastSuccessfulRefreshAt")
    feed = {"schemaVersion": 1, "language": language, "timeZone": "Europe/Paris", "generatedAt": stamp(now),
            "lastSuccessfulRefreshAt": refreshed, "sources": statuses, "items": selected}
    if not successes and previous.get("feed"):
        # A complete outage never overwrites the last useful public file.
        feed = previous["feed"]
    while len(compact_json(feed)) > FEED_BUDGET and feed["items"]:
        feed["items"].pop()
    validate_feed(feed, language)
    state = {"schemaVersion": 1, "language": language, "lastSuccessfulRefreshAt": refreshed,
             "sourceState": states, "history": retained, "feed": feed,
             "mediaState": previous.get('mediaState',{})}
    return state


def atomic_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(compact_json(value))
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument("--state", type=Path, default=Path(".state"))
    parser.add_argument("--force", action="store_true", help="Re-read feed bodies after a parser change; rate limits still apply")
    args = parser.parse_args()
    registry = json.loads(Path(__file__).with_name("sources.json").read_text(encoding="utf-8"))
    now = datetime.now(UTC)
    for language in ("fr", "en"):
        state_path = args.state / f"{language}.json"
        previous = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
        if args.force:
            for state in previous.get("sourceState", {}).values():
                state.pop("etag", None)
                state.pop("lastModified", None)
        sources = [s for s in registry["sources"] if s["language"] == language]
        result = collect_language(sources, language, previous, now)
        result = enrich_media(result,sources,now)
        while len(compact_json(result['feed']))>FEED_BUDGET and result['feed']['items']:
            result['feed']['items'].pop()
        validate_feed(result['feed'],language)
        atomic_write(state_path, result)
        atomic_write(args.output / f"news-feed.{language}.json", result["feed"])
        print(json.dumps({"language": language, "items": len(result["feed"]["items"]),
                          "bytes": len(compact_json(result["feed"])), "sources": [{"id": s["id"], "status": s["status"]} for s in result["feed"]["sources"]]}))


if __name__ == "__main__":
    main()
