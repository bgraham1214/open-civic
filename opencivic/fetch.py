"""Fetchers: a polite live HTTP client and an offline fixture reader.

Every adapter takes a fetcher instead of calling the network directly, so the
same code runs live (on GitHub Actions) and offline (tests, saved samples).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import urllib.robotparser
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from . import __version__

# Identify the project to the servers we read from (guardrail: polite collection).
# Set OCW_CONTACT to a URL or email so site operators can reach a human.
USER_AGENT = f"OpenCivicWeb/{__version__} (public meeting records archive)"
if os.environ.get("OCW_CONTACT"):
    USER_AGENT += f" contact: {os.environ['OCW_CONTACT']}"


class Fetcher(Protocol):
    def get_json(self, url: str) -> dict: ...


class FetchError(RuntimeError):
    pass


class HttpFetcher:
    """Rate-limited, retrying HTTP client that checks robots.txt once per host."""

    def __init__(self, min_interval: float = 1.0, retries: int = 4, timeout: float = 60.0):
        self.min_interval = min_interval
        self.retries = retries
        self.timeout = timeout
        self._last = 0.0
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.last_content_type = ""

    def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                body = self._raw(host + "/robots.txt", check_robots=False)
                rp.parse(body.decode("utf-8", "replace").splitlines())
                self._robots[host] = rp
            except FetchError:
                self._robots[host] = None  # no robots.txt: allowed
        rp = self._robots[host]
        return rp is None or rp.can_fetch(USER_AGENT, url)

    def _wait(self) -> None:
        delay = self.min_interval - (time.monotonic() - self._last)
        if delay > 0:
            time.sleep(delay)
        self._last = time.monotonic()

    def _raw(self, url: str, check_robots: bool = True, accept: str = "*/*") -> bytes:
        if check_robots and not self._allowed(url):
            raise FetchError(f"robots.txt disallows {url}")
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
        for attempt in range(self.retries + 1):
            self._wait()
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    self.last_content_type = resp.headers.get("Content-Type", "")
                    return resp.read()
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt < self.retries:
                    retry_after = e.headers.get("Retry-After", "")
                    time.sleep(float(retry_after) if retry_after.isdigit() else 2 ** (attempt + 1))
                    continue
                raise FetchError(f"HTTP {e.code} for {url}") from e
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < self.retries:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise FetchError(f"{e} for {url}") from e
        raise FetchError(f"gave up on {url}")

    def get_bytes(self, url: str) -> bytes:
        return self._raw(url)

    def download(self, url: str) -> tuple[bytes, str]:
        """Return (body, content type)."""
        body = self._raw(url)
        return body, self.last_content_type

    def get_json(self, url: str) -> dict:
        return json.loads(self._raw(url, accept="application/json"))

    def get_text(self, url: str) -> str:
        return self._raw(url, accept="text/html,*/*;q=0.8").decode("utf-8", "replace")


class FixtureFetcher:
    """Serves saved responses from disk. Unknown URLs raise, so tests can't hit the network.

    `pages` maps URL -> file path. Use `from_files` when you only have saved pages and
    don't care which URL they came from: the first file answers the first request, and
    each later file answers the previous page's @odata.nextLink.
    """

    def __init__(self, pages: dict[str, str | Path]):
        self.pages = {k: Path(v) for k, v in pages.items()}
        self.requested: list[str] = []

    @classmethod
    def from_files(cls, first_url: str, files: list[str | Path]) -> "FixtureFetcher":
        pages: dict[str, Path] = {}
        url = first_url
        for f in files:
            pages[url] = Path(f)
            url = json.loads(Path(f).read_text("utf-8")).get("@odata.nextLink")
            if not url:
                break
        return cls(pages)

    def get_json(self, url: str) -> dict:
        self.requested.append(url)
        if url not in self.pages:
            raise FetchError(f"no saved response for {url}")
        return json.loads(self.pages[url].read_text("utf-8"))

    def get_text(self, url: str) -> str:
        self.requested.append(url)
        if url not in self.pages:
            raise FetchError(f"no saved response for {url}")
        return self.pages[url].read_text("utf-8")
