import contextlib
import io
import ssl
import stat
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import trigger_products as trigger


KEY = "a1" * 32
PRIVATE = "/home/customer/.heddy-private"


class TriggerTests(unittest.TestCase):
    def setUp(self):
        connect = self.enterContext(patch.object(trigger, "connect"))
        self.connect = connect
        self.client = connect.return_value.__enter__.return_value
        self.sftp = self.client.open_sftp.return_value.__enter__.return_value
        self.sftp.normalize.return_value = "/home/customer/www"
        self.folder = SimpleNamespace(st_mode=stat.S_IFDIR | 0o700)
        self.keyfile = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_size=64)
        self.sftp.lstat.side_effect = {PRIVATE: self.folder, PRIVATE + "/scheduler.key": self.keyfile}.__getitem__
        self.stream = self.sftp.file.return_value.__enter__.return_value
        self.stream.read.return_value = KEY.encode()
        self.enterContext(patch.dict(trigger.os.environ, {"NEWS_SFTP_ROOT": "www"}))
        self.https = self.enterContext(patch.object(trigger.http.client, "HTTPSConnection"))
        self.connection = self.https.return_value
        self.sleep = self.enterContext(patch.object(trigger.time, "sleep"))

    def response(self, body=b'{"ok":true,"more":false}', status=200):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = status
        response.read.return_value = body
        return response

    def test_pinned_connector_and_only_one_private_read(self):
        self.assertEqual(KEY, trigger.read_scheduler_key())
        self.connect.assert_called_once_with()
        self.sftp.normalize.assert_called_once_with("www")
        self.sftp.file.assert_called_once_with(PRIVATE + "/scheduler.key", "rb")
        self.stream.read.assert_called_once_with(65)
        self.client.open_sftp.return_value.__exit__.assert_called_once()
        self.connect.return_value.__exit__.assert_called_once()

    def test_sftp_refuses_unexpected_root(self):
        for root in ("www", "/home/customer/public", "/www/../../other/www"):
            with self.subTest(root=root):
                self.sftp.normalize.return_value = root
                with self.assertRaises(trigger.TriggerError):
                    trigger.read_scheduler_key()
        self.sftp.file.assert_not_called()

    def test_symlinks_and_wrong_size(self):
        for mode_folder, mode_file, size in ((stat.S_IFLNK, stat.S_IFREG, 64), (stat.S_IFDIR, stat.S_IFLNK, 64), (stat.S_IFDIR, stat.S_IFREG, 65)):
            with self.subTest(mode_folder=mode_folder, mode_file=mode_file, size=size):
                self.folder.st_mode, self.keyfile.st_mode, self.keyfile.st_size = mode_folder, mode_file, size
                with self.assertRaises(trigger.TriggerError):
                    trigger.read_scheduler_key()
        self.sftp.file.assert_not_called()

    def test_token_format(self):
        for value in (b"A" * 64, b"g" * 64, b"x", KEY.encode() + b"\n"):
            with self.subTest(length=len(value)):
                self.stream.read.return_value = value
                with self.assertRaises(trigger.TriggerError):
                    trigger.read_scheduler_key()

    def test_batches_use_verified_https_and_keep_key_off_sftp_connection(self):
        responses = [self.response(b'{"ok":true,"more":true}'), self.response()]
        self.connection.getresponse.side_effect = responses
        self.connection.request.side_effect = lambda *a, **k: self.connect.return_value.__exit__.assert_called_once()
        trigger.run()
        self.sleep.assert_called_once_with(1)
        self.assertEqual(2, self.connection.request.call_count)
        self.assertEqual(2, self.connection.close.call_count)
        for call in self.https.call_args_list:
            self.assertEqual(("heddy.fr",), call.args)
            self.assertEqual(35, call.kwargs["timeout"])
            self.assertTrue(call.kwargs["context"].check_hostname)
            self.assertEqual(ssl.CERT_REQUIRED, call.kwargs["context"].verify_mode)
        for call in self.connection.request.call_args_list:
            self.assertEqual(("POST", "/private/sync.php", b"{}"), call.args)
            self.assertEqual("Bearer " + KEY, call.kwargs["headers"]["Authorization"])
            self.assertEqual("application/json", call.kwargs["headers"]["Content-Type"])
        for response in responses:
            response.read.assert_called_once_with(4097)

    def test_unconfigured_is_a_completed_batch(self):
        self.connection.getresponse.return_value = self.response(b'{"ok":true,"more":false,"configured":false}')
        self.assertFalse(trigger.request_batch(KEY))

    def test_unauthorized_and_redirects_are_never_followed(self):
        for status in (301, 302, 303, 307, 308, 401, 403):
            with self.subTest(status=status):
                self.connection.request.reset_mock()
                response = self.response(status=status)
                self.connection.getresponse.return_value = response
                with self.assertRaisesRegex(trigger.TriggerError, "rejected"):
                    trigger.request_batch(KEY)
                self.connection.request.assert_called_once()
                response.read.assert_not_called()

    def test_invalid_and_oversized_responses(self):
        for body in [b"{}", b'{', b'{"ok":false,"more":false}', b'{"ok":1,"more":false}',
                     b'{"ok":true,"more":"false"}', b'{"ok":true,"more":false,"configured":0}', b"x" * 4097]:
            with self.subTest(length=len(body)):
                self.connection.getresponse.return_value = self.response(body)
                with self.assertRaises(trigger.TriggerError):
                    trigger.request_batch(KEY)

    def test_batch_limit(self):
        self.connection.getresponse.return_value = self.response(b'{"ok":true,"more":true}')
        with self.assertRaisesRegex(trigger.TriggerError, "batch limit"):
            trigger.run()
        self.assertEqual(210, self.connection.request.call_count)
        self.assertEqual(209, self.sleep.call_count)

    def test_failure_output_has_no_sensitive_errors(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.sftp.normalize.side_effect = OSError("sensitive " + KEY)
            self.assertEqual(1, trigger.main())
            self.sftp.normalize.side_effect = None
            self.connection.request.side_effect = OSError("sensitive " + KEY)
            self.assertEqual(1, trigger.main())
        self.assertNotIn(KEY, err.getvalue())
        self.assertNotIn("sensitive", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())


if __name__ == "__main__":
    unittest.main()
