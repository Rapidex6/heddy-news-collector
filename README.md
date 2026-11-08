# Heddy news collector

Only the public collector and its bounded feed history belong in this repository.
No website source, mascot, Studio/game assets, credentials, image files or PDFs.

## Sources and content

The registry in sources.json contains 27 accessible RSS/Atom feeds, split into
15 French and 12 English feeds. It combines the existing institutional sources
with Numerama, Frandroid, 01net, Les Numériques, Futura, Sciences et Avenir,
Le Monde economy/science, BFM Business, BDM, ActuIA, The Verge, Ars Technica,
ScienceAlert, Live Science, BBC Business, The Guardian Business, NASA and
The Decoder. Availability and directly loadable publisher images determine new
source selection; licence text is not an inclusion/exclusion filter.

Titles and publisher excerpts remain in their original language. Full article
bodies are not republished. Authors, dates, publisher names and original article
links remain available. arXiv entries are marked as research preprints; its
single bounded metadata request is serial and retains its acknowledgement.

Images are optional publisher-hosted HTTPS URLs discovered from media:content,
media:thumbnail, image enclosures, or images embedded in feed descriptions/content.
The largest supplied media candidate is preferred. The four existing HTML
fallback sources have bounded, cached image metadata lookups. The collector never
downloads or stores image bytes. Publisher/CDN host allowlists, public HTTPS
addresses, no credentials/alternate ports, and byte/time limits remain enforced.
A broken picture does not discard the article.

Source presentation (home URL, short name, logo, initials and media hosts) travels
with the JSON data. New registered sources do not require a new frontend map.

## Runtime and bounds

Python 3.13.18, pinned dependencies in requirements.lock. Install with
python -m pip install --require-hashes -r requirements.lock.
Run python -m unittest discover -v, then python collector.py.

Outputs are output/news-feed.fr.json and output/news-feed.en.json.
Each JSON has at most 60 entries and 200,000 UTF-8 bytes, from today and the
previous seven civil days in Europe/Paris. Publication, update, retrieval and
successful-refresh timestamps stay distinct. Missing publication dates and future
entries are excluded. Atom feeds with only an updated timestamp use a separate
feedDateAt field, displayed explicitly as an update; research preprints still
require their publication date. Dates without an offset use Paris; nonexistent DST times
are rejected.

Selection reserves a place for each source before filling the remaining slots,
then sorts the chosen articles chronologically. Per-source caps prevent a busy
publisher dominating the feed. AI categories are also inferred from publisher
tags and explicit AI terminology in titles.

At most four ordinary feeds are requested concurrently; arXiv is requested once,
serially after those connections close, with its three-second delay. Conditional
requests use publisher ETag/Last-Modified values. History remains bounded to eight
Paris dates and 120 entries per source, independently of public caps. Empty feeds
and partial failures retain useful history; complete outages preserve the last
useful public JSON.

HTML fallback metadata has a 24-hour cache, including missing images, a maximum
of eight lookups per language/run, a 1MB HTML limit and ten-second timeout.
Previously valid images survive failed refreshes. Total feed outages trigger no
HTML lookups. No linked arXiv page or PDF is requested.

## History and publication

The news-state Git branch stores separate state/fr.json and state/en.json.
This is durable history, not an expiring Actions cache. Updates are non-forced.

The workflow runs hourly at minute 17 UTC and supports manual runs. Scheduled
workflows may be delayed, or disabled after 60 inactive days.
NEWS_PUBLISH_ENABLED must be true before publication. Configure repository
variables NEWS_SFTP_HOST, NEWS_SFTP_PORT, NEWS_SFTP_USER, NEWS_SFTP_ROOT and the
pinned SHA256 NEWS_SFTP_HOST_FINGERPRINT. The existing SFTP password belongs only
in Actions secret NEWS_SFTP_PASSWORD.

Only the two fixed JSON filenames are sent. Each upload is verified by hash and
published with a temporary sibling plus atomic POSIX rename. Failed renames
preserve the previous file. Website deployments preserve existing runtime feeds.
Deploy a compatible frontend before publishing an expanded source selection.
The full site must remain below 100,000,000 bytes.

Parser revisions invalidate conditional feed validators once, so newly supported
entry formats are backfilled even if the publisher returns unchanged content.
