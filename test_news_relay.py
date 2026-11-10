import unittest
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

from news_relay import RELAY, check_wait, dispatch_relay, seed_if_missing

NOW = datetime(2026, 11, 10, 2, tzinfo=timezone.utc)


class RelayTests(unittest.TestCase):
    def test_age_guard_uses_github_run_creation_time(self):
        for elapsed in (timedelta(seconds=-2), timedelta(0), timedelta(minutes=50, microseconds=-1), timedelta(minutes=50)):
            with self.subTest(elapsed=elapsed):
                calls = []
                def api(path):
                    calls.append(path)
                    return {"created_at": (NOW-elapsed).isoformat()}
                if elapsed < timedelta(minutes=50):
                    with self.assertRaisesRegex(ValueError, 'below 50 minutes'):
                        check_wait(42, NOW, api)
                else:
                    check_wait(42, NOW, api)
                self.assertEqual(calls, ['actions/runs/42'])

    def test_successor_is_one_non_bootstrap_dispatch_even_on_ambiguous_timeout(self):
        calls = []
        def api(path, payload):
            calls.append((path, payload))
            raise TimeoutError("server may have accepted the request")
        with self.assertRaises(TimeoutError):
            dispatch_relay(api)
        self.assertEqual(calls, [(RELAY+'/dispatches', {'ref': 'main', 'inputs': {'bootstrap': False}})])

    def test_watchdog_preserves_each_kind_of_active_relay_and_seeds_an_empty_chain(self):
        for active in ('waiting', 'in_progress', 'queued', 'pending', 'requested', None):
            with self.subTest(active=active):
                posts = []
                def api(path, payload=None):
                    if payload is not None:
                        posts.append((path, payload))
                        return None
                    parts = urlsplit(path)
                    self.assertEqual(parts.path, RELAY+'/runs')
                    query = parse_qs(parts.query)
                    self.assertEqual(query['per_page'], ['100'])
                    if query['page'] == ['1']:
                        # The current watchdog and other-branch runs must not
                        # conceal a still-active relay from the second page.
                        ignored = [
                            {'event':'workflow_run','head_branch':'main','status':'in_progress'},
                            {'event':'workflow_dispatch','head_branch':'dev','status':'waiting'},
                            {'event':'workflow_dispatch','head_branch':'main','status':'completed'},
                            {'event':'workflow_dispatch','head_branch':'main','status':'completed'},
                        ]
                        return {'workflow_runs': ignored * 25}
                    self.assertEqual(query['page'], ['2'])
                    run = {'event':'workflow_dispatch','head_branch':'main','status':active}
                    return {'workflow_runs': [run] if active else []}
                seed_if_missing(api)
                expected = [] if active else [(RELAY+'/dispatches', {'ref':'main','inputs':{'bootstrap':True}})]
                self.assertEqual(posts, expected)


if __name__ == '__main__':
    unittest.main()
