#!/usr/bin/env python3
"""
Stash scraper script for Instagram URL scraping (Scene/Image).
Reads {"url": "..."} from stdin and returns a JSON fragment.
"""
from __future__ import annotations

import json
import os
import re
import sys
import datetime as _dt

import requests


def _fail(msg: str) -> None:
    # Stash expects valid JSON on stdout; emit empty object on error.
    print(msg, file=sys.stderr, flush=True)
    print(json.dumps({}))


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

SHORTCODE_RE = re.compile(r"(?:instagram\\.com/(?:reel|p|tv)/|/reel/|/p/|/tv/)([A-Za-z0-9_-]{5,})")


def _extract_shortcode(url: str) -> str | None:
    if not url:
        return None
    match = SHORTCODE_RE.search(url)
    return match.group(1) if match else None


def _fetch_instagram_json(shortcode: str, sessionid: str | None) -> dict | None:
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    }
    cookies = {}
    if sessionid:
        cookies["sessionid"] = sessionid
    url = f"https://www.instagram.com/p/{shortcode}/?__a=1&__d=dis"
    try:
        resp = requests.get(url, headers=headers, cookies=cookies, timeout=20)
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    try:
        return resp.json()
    except Exception:
        return None


def _parse_instagram_payload(payload: dict, fallback_url: str) -> dict | None:
    media = None
    if payload.get("graphql", {}).get("shortcode_media"):
        media = payload["graphql"]["shortcode_media"]
    elif payload.get("items"):
        media = payload["items"][0]
    if not media:
        return None

    caption = None
    caption_edges = media.get("edge_media_to_caption", {}).get("edges") or media.get("caption")
    if isinstance(caption_edges, list) and caption_edges:
        node = caption_edges[0].get("node") if isinstance(caption_edges[0], dict) else None
        caption = node.get("text") if node else caption_edges[0].get("text") if isinstance(caption_edges[0], dict) else None
    if not caption and isinstance(media.get("caption"), dict):
        caption = media["caption"].get("text")

    ts = media.get("taken_at_timestamp") or media.get("taken_at")
    date_str = None
    if ts:
        date_str = _dt.datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d")

    username = None
    owner = media.get("owner") or media.get("user")
    if isinstance(owner, dict):
        username = owner.get("username")

    permalink = media.get("shortcode") and f"https://www.instagram.com/p/{media['shortcode']}/" or fallback_url

    if not any([caption, date_str, username, permalink]):
        return None

    return {
        "caption": caption or "",
        "date": date_str,
        "username": username,
        "permalink": permalink or fallback_url,
    }

def main() -> None:
    url = _read_url()
    if not url:
        _fail("No URL provided to scraper script.")
        return

    shortcode = _extract_shortcode(url)
    if not shortcode:
        _fail(f"Could not extract Instagram shortcode from URL: {url}")
        return

    ig_sessionid = os.getenv("IG_SESSIONID")
    instajson = _fetch_instagram_json(shortcode, ig_sessionid)
    if not instajson:
        _fail("Failed to fetch Instagram metadata (check IG_SESSIONID or URL).")
        return

    meta = _parse_instagram_payload(instajson, url)
    if not meta:
        _fail("Instagram response did not contain expected fields.")
        return

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
