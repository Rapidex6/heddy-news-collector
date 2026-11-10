"""Check the freshness and exact bytes of Heddy's two public news feeds."""
import argparse
import hashlib
import json
import os
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from http.client import HTTPException
from pathlib import Path

from collector import FEED_BUDGET, USER_AGENT

LANGUAGES = ("fr", "en")
# Allow one polling interval before the hourly target.
REFRESH_AFTER = timedelta(minutes=45)


def read_public(language):
    url = f"https://heddy.fr/news-feed.{language}.json"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
    with urllib.request.urlopen(request, timeout=15) as response:
        if response.geturl() != url:
            raise ValueError("Unexpected public feed redirect")
        data = response.read(FEED_BUDGET + 1)
    if len(data) > FEED_BUDGET:
        raise ValueError("Public feed exceeds its byte limit")
    return data


def refresh_due(now, read=read_public, fresh_for=REFRESH_AFTER):
    due = False
    for language in LANGUAGES:
        try:
            feed = json.loads(read(language))
            if feed["schemaVersion"] != 1 or feed["language"] != language:
                raise ValueError("Invalid feed identity")
            last = datetime.fromisoformat(feed["lastSuccessfulRefreshAt"].replace("Z", "+00:00"))
            age = now - last
            print(f"{language}: last successful refresh {last.isoformat()}")
            if age < timedelta(0) or age >= fresh_for:
                due = True
        except (HTTPException, OSError, ValueError, TypeError, KeyError, AttributeError) as error:
            print(f"{language}: public freshness unavailable ({type(error).__name__})")
            due = True
    return due


def verify_public(output, read=read_public, sleep=time.sleep):
    for language in LANGUAGES:
        expected = (output / f"news-feed.{language}.json").read_bytes()
        feed = json.loads(expected)
        if not feed.get("lastAttemptAt") or feed["lastAttemptAt"] != feed.get("lastSuccessfulRefreshAt"):
            raise ValueError(f"{language}: no successful source in this collection")
        for attempt in range(3):
            try:
                if read(language) != expected:
                    raise ValueError(f"{language}: public bytes differ from the validated output")
                break
            except (HTTPException, ValueError, OSError):
                if attempt == 2:
                    raise
                sleep(3)
        digest = hashlib.sha256(expected).hexdigest()
        print(f"{language}: verified HTTP bytes={len(expected)} sha256={digest} refreshed={feed['lastSuccessfulRefreshAt']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["due", "verify"])
    parser.add_argument("--fresh-for-minutes", type=int, choices=[5, 45], default=45)
    args = parser.parse_args()
    if args.action == "due":
        due = refresh_due(datetime.now(timezone.utc), fresh_for=timedelta(minutes=args.fresh_for_minutes))
        print(f"Refresh due: {due}")
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
                print(f"due={str(due).lower()}", file=output)
    else:
        verify_public(Path("output"))
