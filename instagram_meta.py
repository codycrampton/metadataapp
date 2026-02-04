#!/usr/bin/env python3
"""
Stash plugin entrypoint (raw interface) that pulls Instagram metadata for a scene/image.

Features:
- Fetch caption, post date, permalink, and username for a public Instagram post.
- Sets title->caption, date->post date (YYYY-MM-DD), url->permalink.
- Adds a tag named after the Instagram username (creates it if needed).
- Works as a task or on Scene/Image post hooks.

Config / args:
- url (optional): Instagram post URL. If omitted, the existing item URL is used,
  otherwise a shortcode is inferred from the first media file sidecar (.json/.info.json)
  if present.
- overwrite (bool): overwrite existing title/date/url instead of filling only blanks.
- ig_sessionid (optional): Instagram sessionid cookie for authenticated metadata fetch.
"""
import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _respond(message: str, error: bool = False) -> None:
    out = {"output": message}
    if error:
        out["error"] = message
    print(json.dumps(out))


# ------------ GraphQL helpers ------------
def _build_base_url(server: Dict[str, Any]) -> str:
    scheme = server.get("Scheme") or server.get("scheme") or "http"
    port = server.get("Port") or server.get("port") or 9999
    host = server.get("Host") or server.get("host") or "localhost"
    return f"{scheme}://{host}:{port}"


def _graphql(server: Dict[str, Any], query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = _build_base_url(server).rstrip("/") + "/graphql"
    cookies = {}
    cookie = server.get("SessionCookie") or server.get("sessionCookie")
    if cookie and cookie.get("Name") and cookie.get("Value"):
        cookies[cookie["Name"]] = cookie["Value"]
    headers = {"Accept": "application/json"}
    resp = requests.post(url, json={"query": query, "variables": variables or {}}, cookies=cookies, headers=headers, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        raise RuntimeError(data["errors"])
    return data.get("data", {})


# ------------ Target detection ------------
def _detect_target(hook_ctx: Dict[str, Any], args: Dict[str, Any]) -> Tuple[str, str]:
    """
    Returns (target_type, id) where target_type is "Scene" or "Image".
    Prefers hookContext; falls back to explicit args.
    """
    if isinstance(hook_ctx, dict):
        ctx_type = hook_ctx.get("type") or hook_ctx.get("__typename")
        ctx_id = hook_ctx.get("id")
        if ctx_type in ("Scene", "Image") and ctx_id:
            return ctx_type, str(ctx_id)
        # common hookContext keys
        for key, t in (("sceneId", "Scene"), ("scene_id", "Scene"), ("sceneID", "Scene"), ("imageId", "Image"), ("image_id", "Image"), ("imageID", "Image")):
            if key in hook_ctx:
                return t, str(hook_ctx[key])
    # args fallback
    target_type = args.get("target_type") or args.get("type")
    target_id = args.get("target_id") or args.get("id")
    if target_type in ("Scene", "Image") and target_id:
        return target_type, str(target_id)
    raise RuntimeError("Unable to determine target Scene/Image id from hookContext or args.")


# ------------ Instagram fetching ------------
SHORTCODE_RE = re.compile(r"(?:instagram\\.com/(?:reel|p|tv)/|/reel/|/p/|/tv/)([A-Za-z0-9_-]{5,})")


def _extract_shortcode(url: str) -> Optional[str]:
    if not url:
        return None
    m = SHORTCODE_RE.search(url)
    return m.group(1) if m else None


def _fetch_instagram_json(shortcode: str, sessionid: Optional[str]) -> Optional[Dict[str, Any]]:
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    }
    cookies = {}
    if sessionid:
        cookies["sessionid"] = sessionid
    url = f"https://www.instagram.com/p/{shortcode}/?__a=1&__d=dis"
    resp = requests.get(url, headers=headers, cookies=cookies, timeout=20)
    if resp.status_code != 200:
        _stderr(f"Instagram request failed ({resp.status_code}) for shortcode {shortcode}")
        return None
    try:
        return resp.json()
    except Exception as exc:  # pragma: no cover - defensive
        _stderr(f"Failed to decode Instagram JSON: {exc}")
        return None


def _parse_instagram_payload(payload: Dict[str, Any], fallback_url: str) -> Optional[Dict[str, Any]]:
    # Support legacy / new layouts
    media = None
    if payload.get("graphql", {}).get("shortcode_media"):
        media = payload["graphql"]["shortcode_media"]
    elif payload.get("items"):
        media = payload["items"][0]
    if not media:
        return None

    # caption
    caption = None
    caption_edges = media.get("edge_media_to_caption", {}).get("edges") or media.get("caption")
    if isinstance(caption_edges, list) and caption_edges:
        node = caption_edges[0].get("node") if isinstance(caption_edges[0], dict) else None
        caption = node.get("text") if node else caption_edges[0].get("text") if isinstance(caption_edges[0], dict) else None
    if not caption and isinstance(media.get("caption"), dict):
        caption = media["caption"].get("text")

    # taken at
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


# ------------ Sidecar helpers ------------
def _load_sidecar_data(paths: list[Path]) -> Optional[Dict[str, Any]]:
    for p in paths:
        for suffix in (".info.json", ".json"):
            candidate = p.with_suffix(p.suffix + suffix)
            if candidate.exists():
                try:
                    data = json.loads(candidate.read_text(encoding="utf-8"))
                except Exception:
                    continue
                return data
    return None


def _sidecar_to_url(data: Dict[str, Any]) -> Optional[str]:
    for key in ("webpage_url", "permalink", "url"):
        if key in data and data[key]:
            return data[key]
    shortcode = data.get("shortcode") or data.get("shortcode_id")
    if shortcode:
        return f"https://www.instagram.com/p/{shortcode}/"
    return None


# ------------ Tag utilities ------------
def _ensure_tag(server: Dict[str, Any], name: str) -> str:
    q = """
    query($name: String!) {
      allTags(filter: {name: {equals: $name}}) { id name }
    }
    """
    data = _graphql(server, q, {"name": name})
    existing = (data.get("allTags") or [])
    if existing:
        return existing[0]["id"]
    create = """
    mutation($input: TagCreateInput!) {
      tagCreate(input: $input) { id }
    }
    """
    res = _graphql(server, create, {"input": {"name": name}})
    return res["tagCreate"]["id"]


# ------------ Scene/Image fetching/updating ------------
def _get_item(server: Dict[str, Any], target_type: str, item_id: str) -> Dict[str, Any]:
    if target_type == "Scene":
        query = """
        query($id: ID!) {
          findScene(id: $id) {
            id title url date
            tags { id name }
            files { path }
          }
        }
        """
        data = _graphql(server, query, {"id": item_id})
        return data.get("findScene")
    else:
        query = """
        query($id: ID!) {
          findImage(id: $id) {
            id title url date
            tags { id name }
            path
          }
        }
        """
        data = _graphql(server, query, {"id": item_id})
        return data.get("findImage")


def _update_item(server: Dict[str, Any], target_type: str, item_id: str, updates: Dict[str, Any]) -> None:
    mutation = (
        """
        mutation($input: SceneUpdateInput!){
          sceneUpdate(input: $input){ id }
        }
        """
        if target_type == "Scene"
        else """
        mutation($input: ImageUpdateInput!){
          imageUpdate(input: $input){ id }
        }
        """
    )
    payload = {"input": {"id": item_id} | {k: v for k, v in updates.items() if v is not None}}
    _graphql(server, mutation, payload)


# ------------ Main workflow ------------
def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except Exception as exc:
        _respond(f"Failed to parse input JSON: {exc}", error=True)
        return

    input_block = payload.get("input", {}) or {}
    args = input_block.get("args", {}) or {}
    hook_ctx = input_block.get("hookContext", {}) or {}
    server = payload.get("server_connection") or payload.get("serverConnection") or {}

    try:
        target_type, item_id = _detect_target(hook_ctx, args)
    except Exception as exc:
        _respond(str(exc), error=True)
        return

    overwrite = bool(args.get("overwrite"))
    user_url = args.get("url") or ""
    ig_sessionid = args.get("ig_sessionid") or os.getenv("IG_SESSIONID")

    item = _get_item(server, target_type, item_id)
    if not item:
        _respond(f"{target_type} {item_id} not found", error=True)
        return

    # Determine URL to fetch metadata
    current_url = item.get("url") or ""
    file_paths: list[Path] = []
    if target_type == "Scene":
        for f in item.get("files") or []:
            if f.get("path"):
                file_paths.append(Path(f["path"]))
    else:
        if item.get("path"):
            file_paths.append(Path(item["path"]))

    sidecar_data = _load_sidecar_data(file_paths)
    sidecar_url = _sidecar_to_url(sidecar_data) if sidecar_data else None

    source_url = user_url or current_url or sidecar_url
    if not source_url:
        _respond("No Instagram URL found (provide args.url or ensure item.url/sidecar contains it).", error=True)
        return

    shortcode = _extract_shortcode(source_url)
    if not shortcode:
        _respond(f"Could not extract shortcode from URL: {source_url}", error=True)
        return

    instajson = _fetch_instagram_json(shortcode, ig_sessionid)
    if not instajson:
        _respond("Failed to fetch Instagram metadata (check ig_sessionid or URL).", error=True)
        return

    meta = _parse_instagram_payload(instajson, source_url)
    if not meta:
        _respond("Instagram response did not contain expected fields.", error=True)
        return

    updates: Dict[str, Any] = {}
    if overwrite or not (item.get("title")):
        updates["title"] = meta["caption"]
    if meta.get("date") and (overwrite or not item.get("date")):
        updates["date"] = meta["date"]
    if overwrite or not item.get("url"):
        updates["url"] = meta["permalink"]

    # Tag with username
    tag_ids = [t["id"] for t in item.get("tags") or []]
    if meta.get("username"):
        username_tag = _ensure_tag(server, meta["username"])
        if username_tag not in tag_ids:
            tag_ids.append(username_tag)
        updates["tag_ids"] = tag_ids

    _update_item(server, target_type, item_id, updates)

    summary_bits = [
        f"type={target_type}",
        f"id={item_id}",
        f"title={'set' if 'title' in updates else 'kept'}",
        f"date={meta.get('date') or 'n/a'}",
        f"url={meta.get('permalink')}",
        f"tag={meta.get('username') or 'n/a'}",
    ]
    _respond("Updated Instagram metadata: " + ", ".join(summary_bits))


if __name__ == "__main__":
    main()
