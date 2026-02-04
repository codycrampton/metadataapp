# Instagram Metadata plugin for Stash

Pulls caption, post date, permalink, and username tag from an Instagram post and writes them to the selected Scene or Image via Stash's GraphQL API.

## Files
- `plugin.yml` – plugin manifest (raw interface).
- `instagram_meta.py` – Python entrypoint.

## What it does
- Title → Instagram caption (only if empty unless `overwrite=true`).
- Date → Post date (UTC, `YYYY-MM-DD`).
- URL → Post permalink.
- Tags → Adds/creates a tag equal to the Instagram username.

## How it finds the post
1) `args.url` if provided.  
2) Existing `url` on the item.  
3) Sidecar metadata next to the first media file (`*.info.json` or `*.json`, e.g., gallery-dl/yt-dlp).

## Auth for Instagram
Public posts often require a logged-in cookie. Pass `ig_sessionid` (Instagram `sessionid` cookie value) in task args or set env `IG_SESSIONID`. The cookie is only used for the metadata request.

## Install
1. Copy the `instagram-meta` folder into your Stash plugin directory.
2. Ensure `python3` and `requests` are available on the host running Stash.
3. Restart Stash or reload plugins.

## Usage
- **Task**: Run “Update from Instagram URL” from the Plugins UI.  
  - Args: `url` (optional), `overwrite` (bool), `ig_sessionid` (optional).
- **Hooks**: The plugin is registered for `Scene.Create.Post`, `Scene.Update.Post`, `Image.Create.Post`, `Image.Update.Post`. On import/update it will try to derive the Instagram URL via the rules above.

## Notes / limitations
- Requires a valid Instagram post URL (reel/p/tv). Shortcode is extracted from the URL.
- If Instagram returns 429/403, provide a fresh `ig_sessionid`.
- Only minimal fields are updated; no media downloads are performed.
- The plugin preserves existing title/date/url unless `overwrite=true`.
