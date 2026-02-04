#!/usr/bin/env python3
"""
Stash scraper script for Instagram URL scraping (Scene/Image).
Reads {"url": "..."} from stdin and returns a JSON fragment.
"""
from __future__ import annotations

import json
import os
import sys

from instagram_meta import _extract_shortcode, _fetch_instagram_json, _parse_instagram_payload


def _die(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)
    sys.exit(1)


def _read_url() -> str:
    raw = sys.stdin.read().strip()
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except Exception:
        return raw.strip().strip('"')
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        return data.get("url") or data.get("URL") or data.get("Url") or ""
    return ""


def main() -> None:
    url = _read_url()
    if not url:
        _die("No URL provided to scraper script.")

    shortcode = _extract_shortcode(url)
    if not shortcode:
        _die(f"Could not extract Instagram shortcode from URL: {url}")

    ig_sessionid = os.getenv("IG_SESSIONID")
    instajson = _fetch_instagram_json(shortcode, ig_sessionid)
    if not instajson:
        _die("Failed to fetch Instagram metadata (check IG_SESSIONID or URL).")

    meta = _parse_instagram_payload(instajson, url)
    if not meta:
        _die("Instagram response did not contain expected fields.")

    result: dict[str, object] = {}
    if meta.get("caption"):
        result["Title"] = meta["caption"]
    if meta.get("date"):
        result["Date"] = meta["date"]
    if meta.get("permalink"):
        result["URL"] = meta["permalink"]
    if meta.get("username"):
        result["Tags"] = [{"Name": meta["username"]}]

    print(json.dumps(result))


if __name__ == "__main__":
    main()
