"""Durable bounded collection history on the dedicated news-state Git branch."""
import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

BRANCH = "news-state"
MAX_STATE_BYTES = 5_000_000


def api(path, payload=None, method=None, *, raw=False):
    repository = os.environ["GITHUB_REPOSITORY"]
    request = urllib.request.Request("https://api.github.com/repos/" + repository + "/" + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
                 "Accept": "application/vnd.github.raw+json" if raw else "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "HeddyNewsCollector"}, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        if raw:
            value = response.read(MAX_STATE_BYTES + 1)
            if len(value) > MAX_STATE_BYTES:
                raise ValueError("State exceeds limit")
            return value
        return json.load(response)


def current_ref():
    try:
        return api("git/ref/heads/" + BRANCH)["object"]["sha"]
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        return None


def pull():
    reference = current_ref()
    Path(".state").mkdir(exist_ok=True)
    if not reference:
        print("No stored history yet")
        return
    for language in ["fr", "en"]:
        try:
            # Contents responses omit inline base64 for files over 1 MB.
            value = api(f"contents/state/{language}.json?ref={reference}", raw=True)
            data = json.loads(value)
            if data["schemaVersion"] != 1 or data["language"] != language:
                raise ValueError("Invalid stored history")
            Path(f".state/{language}.json").write_bytes(value)
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise


def push():
    reference = current_ref()
    # An orphan tree prevents any site or game asset from entering this branch.
    tree = []
    for language in ["fr", "en"]:
        path = Path(f".state/{language}.json")
        if path.exists():
            if path.stat().st_size > MAX_STATE_BYTES:
                raise ValueError("State exceeds limit")
            value = json.loads(path.read_text(encoding="utf-8"))
            if value["language"] != language:
                raise ValueError("Wrong state language")
            tree.append({"path": f"state/{language}.json", "mode": "100644", "type": "blob", "content": path.read_text(encoding="utf-8")})
    if not tree:
        return
    tree_sha = api("git/trees", {"tree": tree})["sha"]
    if reference and api("git/commits/" + reference)["tree"]["sha"] == tree_sha:
        print("Stored state unchanged")
        return
    commit = api("git/commits", {"message": "Update bounded news history", "tree": tree_sha, "parents": [reference] if reference else []})
    if reference:
        api("git/refs/heads/" + BRANCH, {"sha": commit["sha"], "force": False}, "PATCH")
    else:
        api("git/refs", {"ref": "refs/heads/" + BRANCH, "sha": commit["sha"]})
    print("Stored bounded per-language history")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["pull", "push"])
    {"pull": pull, "push": push}[parser.parse_args().action]()
