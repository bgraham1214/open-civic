# SPDX-License-Identifier: Apache-2.0
"""HttpFetcher gives up on an unreachable host after one retry cycle (offline: urlopen is faked)."""

import unittest
import urllib.error
from unittest import mock

from opencivic import fetch


class HostDownTest(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def fake_urlopen(req, timeout):
            self.calls.append(req.full_url)
            raise urllib.error.URLError(TimeoutError("timed out"))

        patches = [mock.patch.object(fetch.urllib.request, "urlopen", fake_urlopen),
                   mock.patch.object(fetch.time, "sleep", lambda s: None)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_one_retry_cycle_per_host(self):
        f = fetch.HttpFetcher(min_interval=0, retries=2)
        with self.assertRaises(fetch.HostDown):
            f.get_text("https://city.example/a")
        # robots.txt timed out on all 3 attempts; the page itself was never requested
        self.assertEqual(self.calls, ["https://city.example/robots.txt"] * 3)
        with self.assertRaises(fetch.HostDown) as cm:
            f.get_text("https://city.example/b")
        self.assertIn("unreachable earlier this run", str(cm.exception))
        self.assertEqual(len(self.calls), 3)  # no new requests

    def test_other_hosts_still_tried(self):
        f = fetch.HttpFetcher(min_interval=0, retries=0, check_robots=False)
        for url in ("https://a.example/x", "https://b.example/y"):
            with self.assertRaises(fetch.HostDown):
                f.get_bytes(url)
        self.assertEqual(self.calls, ["https://a.example/x", "https://b.example/y"])

    def test_host_down_is_a_fetch_error(self):
        # callers that catch FetchError (manifest, adapters) keep working unchanged
        self.assertTrue(issubclass(fetch.HostDown, fetch.FetchError))

    def test_http_error_does_not_mark_host_down(self):
        def not_found(req, timeout):
            self.calls.append(req.full_url)
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

        with mock.patch.object(fetch.urllib.request, "urlopen", not_found):
            f = fetch.HttpFetcher(min_interval=0, retries=0, check_robots=False)
            for url in ("https://c.example/1", "https://c.example/2"):
                with self.assertRaises(fetch.FetchError) as cm:
                    f.get_bytes(url)
                self.assertNotIsInstance(cm.exception, fetch.HostDown)
        self.assertEqual(len(self.calls), 2)


if __name__ == "__main__":
    unittest.main()
