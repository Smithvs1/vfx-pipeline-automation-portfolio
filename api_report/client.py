"""HTTP client for a ShotGrid/ftrack-style production-tracking REST API."""
from __future__ import annotations

import logging
from collections.abc import Iterator

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)


class ApiError(RuntimeError):
    pass


class ShotTrackClient:
    def __init__(self, base_url: str, token: str, timeout: float = 15, retries: int = 5, backoff: float = 0.2):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/json",
                                     "User-Agent": "vfx-api-report/1.0"})
        retry = Retry(
            total=retries,
            backoff_factor=backoff,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
        )
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise ApiError(f"GET {url} failed: {exc}") from exc
        if resp.status_code == 401:
            raise ApiError("401 Unauthorized: check SHOTTRACK_TOKEN")
        if not resp.ok:
            raise ApiError(f"GET {url} -> {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def paginate(self, path: str, per_page: int = 10, **filters) -> Iterator[dict]:
        page = 1
        while page:
            body = self._get(path, {"page": page, "per_page": per_page, **filters})
            log.debug("%s page %s: %s items", path, page, len(body["data"]))
            yield from body["data"]
            page = body.get("next_page")

    def shots(self, **filters) -> list[dict]:
        return list(self.paginate("/api/v1/shots", **filters))

    def vendors(self) -> list[dict]:
        return list(self.paginate("/api/v1/vendors"))
