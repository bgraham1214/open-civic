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


class CrawlDelayTest(unittest.TestCase):
    """robots.txt Crawl-delay is honored per host (Temple Terrace's CivicPlus site asks for 10 s)."""

    def test_waits_crawl_delay_between_requests_to_that_host(self):
        clock = [1000.0]
        slept = []

        def sleep(s):
            slept.append(round(s, 3))
            clock[0] += s

        class Resp:
            headers = {"Content-Type": "text/plain"}

            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return self.body

            def geturl(self):
                return ""

        def urlopen(req, timeout):
            if req.full_url == "https://city.example/robots.txt":
                return Resp(b"User-agent: *\nDisallow: /admin\nCrawl-delay: 10\n")
            if req.full_url.endswith("/robots.txt"):
                return Resp(b"User-agent: *\nDisallow: /admin\n")
            return Resp(b"ok")

        with mock.patch.object(fetch.urllib.request, "urlopen", urlopen), \
                mock.patch.object(fetch.time, "sleep", sleep), \
                mock.patch.object(fetch.time, "monotonic", lambda: clock[0]):
            f = fetch.HttpFetcher(min_interval=1.0, retries=0)
            f.get_text("https://city.example/a")
            f.get_text("https://city.example/b")
            f.get_text("https://other.example/c")  # no robots delay: only the 1 s minimum
        self.assertEqual(f.crawl_delay("city.example"), 10.0)
        # robots.txt counts as a request to the host: robots.txt -> /a and /a -> /b wait 10 s;
        # other.example asks for no delay, so its robots.txt and page wait only the 1 s minimum
        self.assertEqual(slept, [10.0, 10.0, 1.0, 1.0])
