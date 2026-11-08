"""Publish only the two validated public JSON feeds, independently and atomically."""
import base64
import hashlib
import hmac
import json
import os
import posixpath
import uuid
from pathlib import Path

import paramiko

from collector import FEED_BUDGET, validate_feed


class PinnedHostKey(paramiko.MissingHostKeyPolicy):
    def __init__(self, fingerprint):
        if not fingerprint.startswith("SHA256:"):
            raise ValueError("A pinned SHA256 SSH host fingerprint is required")
        self.fingerprint = fingerprint

    def missing_host_key(self, client, hostname, key):
        actual = "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
        if not hmac.compare_digest(actual, self.fingerprint):
            raise paramiko.SSHException("SFTP host fingerprint mismatch")


def connect(password=None):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(PinnedHostKey(os.environ["NEWS_SFTP_HOST_FINGERPRINT"]))
    client.connect(os.environ["NEWS_SFTP_HOST"], port=int(os.environ.get("NEWS_SFTP_PORT", "22")),
                   username=os.environ["NEWS_SFTP_USER"], password=password or os.environ["NEWS_SFTP_PASSWORD"],
                   look_for_keys=False, allow_agent=False, timeout=25, auth_timeout=25, banner_timeout=25)
    return client


def atomic_upload(sftp, target, data):
    temporary = posixpath.join(posixpath.dirname(target), "." + posixpath.basename(target) + "." + uuid.uuid4().hex + ".tmp")
    try:
        with sftp.file(temporary, "wb") as file:
            file.write(data)
        with sftp.file(temporary, "rb") as file:
            if hashlib.sha256(file.read()).digest() != hashlib.sha256(data).digest():
                raise IOError("SFTP verification failed")
        # Never delete the previous valid feed to work around a failed rename.
        sftp.posix_rename(temporary, target)
    finally:
        try:
            sftp.remove(temporary)
        except IOError:
            pass


def main():
    output = Path("output")
    validated = {}
    for language in ["fr", "en"]:
        data = (output / f"news-feed.{language}.json").read_bytes()
        if len(data) > FEED_BUDGET:
            raise ValueError("Oversized feed")
        feed = validate_feed(json.loads(data), language)
        if feed["lastSuccessfulRefreshAt"]:
            validated[language] = data
    if not validated:
        print("No successful initial selection; remote files preserved")
        return
    client = connect()
    failures = []
    try:
        with client.open_sftp() as sftp:
            root = sftp.normalize(os.environ["NEWS_SFTP_ROOT"])
            for language, data in validated.items():
                try:
                    atomic_upload(sftp, posixpath.join(root, f"news-feed.{language}.json"), data)
                    print(f"Published {language}: {len(data)} bytes")
                except Exception as error:
                    failures.append(language)
                    print(f"Preserved remote {language}: {type(error).__name__}")
    finally:
        client.close()
    if failures:
        raise RuntimeError("Feed publication failed for: " + ", ".join(failures))


if __name__ == "__main__":
    main()
