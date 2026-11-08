# Heddy news collector

This repository contains only the public news collector and its bounded feed history.
It never contains the website, the mascot, the Studio, game assets, credentials, or PDFs.

## Sources and content

`sources.json` is the reviewed selection: Insee, Économie.gouv, CNIL and explicitly
licensed LinuxFr AI contributions in French; Eurostat economy news, NIST News, NSF,
and arXiv cs.AI descriptive metadata in English. The two selections may differ.
The Conversation France is disabled. French science coverage is limited.

The collector keeps original titles, authors and publisher summaries, without
translation or generated summaries. LinuxFr accepts only `/news/` or `/journaux/`
entries with explicit CC BY-SA 4.0 rights; its excerpt is an original paragraph.
arXiv abstracts are identified as research preprints, with all authors and its
required acknowledgement. All public entries carry source, publication date,
retrieval date, applicable reuse terms, attribution and the original HTTPS link.
Images are optional remote URLs, never downloaded or stored as files. The
collector reads bounded article HTML only for Eurostat-owned statistical charts
and CNIL-owned illustrations, from reviewed publisher hosts and paths. Stock
photographs, third-party illustrations and arXiv pages/PDFs are excluded.
Eurostat charts retain CC BY 4.0 attribution. CNIL illustrations retain
CC BY-NC-ND 4.0 attribution and must be displayed whole, without cropping or
alteration, on this personal, noncommercial site. Detailed attribution and
licence links remain available in the website's global Sources disclosure.
CNIL filenames are explicitly reviewed in `media.py`; unreviewed or third-party
artwork hosted on the same site is excluded. Future images need that review.

## Runtime

Python 3.13.18; exact dependency versions and official PyPI hashes are in
`requirements.lock`. Install with `python -m pip install --require-hashes -r requirements.lock`.
Run `python -m unittest discover -v`, then `python collector.py`.
Outputs: `output/news-feed.fr.json` and `output/news-feed.en.json`.

Each JSON has at most 30 entries and 200,000 UTF-8 bytes. Display window: today
and the previous seven civil days in Europe/Paris, using publication dates.
`publishedAt`, `updatedAt`, `retrievedAt` and `lastSuccessfulRefreshAt` remain distinct.
Dates without an offset use Europe/Paris; nonexistent DST local times are rejected.

One bounded arXiv request per run, serial connection, at least a three-second wait
before its request. Other sources use ETag/Last-Modified when supplied. Valid empty
feeds preserve history; partial failures retain other sources; total outages retain
the last useful public JSON. History is bounded to eight Paris dates and 120 entries
per source, independently of public caps. Missing publication dates are excluded.

Image metadata is cached in the language state for 24 hours, including a missing
image result. At most six article pages per language are checked in one run,
with a one-megabyte HTML limit and ten-second timeout. Failures preserve a
previously validated image. A total feed outage triggers no image lookups.

## Durable history and publication

The `news-state` Git branch stores separate `state/fr.json` and `state/en.json`.
This is durable repository state, not a cache or expiring workflow artifact.
No site files are committed to that branch. Updates use non-forced ref changes.
The workflow runs hourly at minute 17 and supports manual runs; standard public
GitHub-hosted runners are used. Scheduled workflows may be delayed or disabled
after 60 inactive days; check the latest run and re-enable if needed.

Publication is disabled until repository variable `NEWS_PUBLISH_ENABLED` is `true`.
Validate a real runner first, deploy the complete website second, then enable it.
Set repository variables `NEWS_SFTP_HOST`, `NEWS_SFTP_PORT`, `NEWS_SFTP_USER`,
`NEWS_SFTP_ROOT`, `NEWS_SFTP_HOST_FINGERPRINT` (SHA256 pinned SSH server key).
The existing SFTP password goes only in Actions secret `NEWS_SFTP_PASSWORD`.
Never place it in source code, an issue, a workflow file, or this document.

Only the two fixed JSON filenames are transferred. Each upload is verified by hash
and published through a temporary sibling and atomic POSIX rename. A failed rename
does not remove the previous file. Languages are published independently.
General website deployments must preserve existing `news-feed.*.json`; only seed
them when absent. The separate website deployment tool implements that rule.

The complete deployed site, including the initial two feeds, must remain below
100,000,000 bytes. This collector repository alone is not the website deployment.
