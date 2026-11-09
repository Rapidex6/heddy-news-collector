"""Trigger the private updater without downloading product data."""
import http.client
import json
import os
import posixpath
import re
import ssl
import stat
import sys
import time

from sftp_publish import connect


MAX_BATCHES = 210
MAX_RESPONSE = 4096


class TriggerError(Exception):
    """A fixed message that is safe to print in a public workflow."""


def read_scheduler_key():
    try:
        with connect() as client, client.open_sftp() as sftp:
            root = sftp.normalize(os.environ["NEWS_SFTP_ROOT"])
            if (not posixpath.isabs(root) or posixpath.normpath(root) != root
                    or posixpath.basename(root) != "www"):
                raise TriggerError("Unexpected website directory.")
            directory = posixpath.join(posixpath.dirname(root), ".heddy-private")
            if not stat.S_ISDIR(sftp.lstat(directory).st_mode):
                raise TriggerError("Scheduler directory unavailable.")
            path = posixpath.join(directory, "scheduler.key")
            info = sftp.lstat(path)
            if not stat.S_ISREG(info.st_mode) or info.st_size != 64:
                raise TriggerError("Scheduler key unavailable.")
            with sftp.file(path, "rb") as stream:
                raw = stream.read(65)
    except TriggerError:
        raise
    except Exception:
        raise TriggerError("Scheduler key unavailable.") from None
    if re.fullmatch(rb"[a-f0-9]{64}", raw) is None:
        raise TriggerError("Scheduler key unavailable.")
    return raw.decode("ascii")


def request_batch(key):
    connection = http.client.HTTPSConnection("heddy.fr", timeout=60, context=ssl.create_default_context())
    try:
        # HTTPSConnection does not follow redirects. The credential stays on this origin.
        connection.request("POST", "/private/sync.php", b"{}", headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        with connection.getresponse() as response:
            if response.status != 200:
                raise TriggerError("Updater rejected the request.")
            body = response.read(MAX_RESPONSE + 1)
            if len(body) > MAX_RESPONSE:
                raise TriggerError("Invalid updater response.")
            result = json.loads(body)
    except TriggerError:
        raise
    except Exception:
        raise TriggerError("Updater response unavailable.") from None
    finally:
        connection.close()
    if (not isinstance(result, dict) or type(result.get("ok")) is not bool
            or type(result.get("more")) is not bool
            or ("configured" in result and type(result["configured"]) is not bool)):
        raise TriggerError("Invalid updater response.")
    if not result["ok"]:
        raise TriggerError("The updater reported a failure.")
    return result["more"]


def run():
    key = read_scheduler_key()
    for batch in range(MAX_BATCHES):
        if not request_batch(key):
            return
        if batch + 1 < MAX_BATCHES:
            time.sleep(1)
    raise TriggerError("The updater exceeded the batch limit.")


def main():
    try:
        run()
    except TriggerError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        print("The updater could not run.", file=sys.stderr)
        return 1
    print("Hourly update completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
