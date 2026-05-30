"""
api_client.py
=============
Low-level HTTP access to the CMS Marketplace API: a single _request() helper
with retry/backoff and rate-limit handling. Endpoint wrappers live in plans.py.
"""

import time

import requests

from marketplace import config
from marketplace.logging_setup import get_logger

log = get_logger("extract.api")


def request(method, path, *, params=None, json_body=None):
    """Make one API call with retry/backoff. Returns parsed JSON or None."""
    if not config.API_KEY:
        raise RuntimeError(
            "No API key found. Set MARKETPLACE_API in your .env file."
        )

    url = f"{config.BASE_URL}/{path}"
    params = dict(params or {})
    params["apikey"] = config.API_KEY

    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            resp = requests.request(
                method, url, params=params, json=json_body, timeout=30
            )

            # Rate limited — back off and retry.
            if resp.status_code == 429:
                wait = 2 ** attempt
                log.warning("Rate limited. Waiting %ss before retry.", wait)
                time.sleep(wait)
                continue

            # Client error — log what the API actually said. Don't retry a 400;
            # a malformed request won't fix itself by repeating.
            if 400 <= resp.status_code < 500:
                log.error("HTTP %d on %s — API response: %s",
                          resp.status_code, path, resp.text[:600])
                if resp.status_code == 400:
                    return None

            resp.raise_for_status()
            time.sleep(config.REQUEST_DELAY)
            return resp.json()
        except requests.RequestException as exc:
            log.warning("Request failed (attempt %d/%d): %s",
                        attempt, config.MAX_RETRIES, exc)
            time.sleep(2 ** attempt)

    log.error("Giving up on %s after %d attempts.", path, config.MAX_RETRIES)
    return None
