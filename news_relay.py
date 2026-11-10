"""Keep one timed news relay running using only the current Actions job's token."""
import argparse
import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone

RELAY = "actions/workflows/news-relay.yml"
BRANCH = "main"
MINIMUM_WAIT = timedelta(minutes=50)


def github(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/{path}",
        data=data,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
            "Content-Type": "application/json",
            "User-Agent": "HeddyNewsRelay",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read()
    return json.loads(body) if body else None


def check_wait(run_id, now, api=github):
    run = api(f"actions/runs/{int(run_id)}")
    created = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
    elapsed = now - created
    if elapsed < MINIMUM_WAIT:
        raise ValueError(f"Elapsed {elapsed}, below 50 minutes. Check the news-hourly environment wait timer.")
    print(f"GitHub run created at {created.isoformat()}, elapsed {elapsed}.")


def dispatch_relay(api=github, *, bootstrap=False):
    # One POST only. A timeout can follow a successful dispatch.
    api(f"{RELAY}/dispatches", {"ref": BRANCH, "inputs": {"bootstrap": bootstrap}})
    print("Requested one immediate news bootstrap." if bootstrap else "Requested one news relay with its 50-minute wait.")


def seed_if_missing(api=github):
    # Read every status in the same snapshot, so a waiting -> running transition
    # cannot disappear between individual status queries. Unfiltered listing
    # also avoids GitHub's 1,000-result cap on filtered workflow-run searches.
    page = 1
    while True:
        runs = api(f"{RELAY}/runs?per_page=100&page={page}")["workflow_runs"]
        for run in runs:
            if run["event"] == "workflow_dispatch" and run["head_branch"] == BRANCH and run["status"] != "completed":
                print(f"An active news relay exists ({run['status']}).")
                return
        if len(runs) < 100:
            break
        page += 1
    dispatch_relay(api, bootstrap=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["check-wait", "dispatch-next", "seed-if-missing"])
    action = parser.parse_args().action
    if action == "check-wait":
        check_wait(os.environ["GITHUB_RUN_ID"], datetime.now(timezone.utc))
    elif action == "dispatch-next":
        dispatch_relay()
    else:
        seed_if_missing()
