"""Fetch with retries: fan sites drop the odd connection under a full rebuild."""

from __future__ import annotations

import time
from typing import Any

import httpx

ATTEMPTS = 4
RETRY_STATUS = {429, 500, 502, 503, 504}


def get(
    client: httpx.Client, url: str, *, pause: float = 2.0, **kwargs: Any
) -> httpx.Response:
    """GET that retries dropped connections and server hiccups, never a 404."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            response = client.get(url, **kwargs)
        except httpx.TransportError:
            if attempt == ATTEMPTS:
                raise
        else:
            if response.status_code not in RETRY_STATUS or attempt == ATTEMPTS:
                response.raise_for_status()
                return response
        time.sleep(pause * attempt)
    raise AssertionError("unreachable")
