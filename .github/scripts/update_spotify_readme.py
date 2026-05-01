from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


README_PATH = os.environ.get("README_PATH", "README.md")
START_MARKER = "<!-- spotify:start -->"
END_MARKER = "<!-- spotify:end -->"
TOKEN_URL = "https://accounts.spotify.com/api/token"
CURRENT_TRACK_URL = "https://api.spotify.com/v1/me/player/currently-playing"
RECENT_TRACKS_URL = "https://api.spotify.com/v1/me/player/recently-played?limit=1"


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def fetch_json(url: str, method: str = "GET", headers: dict[str, str] | None = None, body: bytes | None = None) -> tuple[int, Any]:
    request = urllib.request.Request(url, method=method, headers=headers or {}, data=body)
    try:
        with urllib.request.urlopen(request) as response:
            payload = response.read().decode("utf-8")
            return response.status, json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8")
        data = json.loads(payload) if payload else {}
        return exc.code, data


def refresh_access_token() -> str:
    client_id = require_env("SPOTIFY_CLIENT_ID")
    client_secret = require_env("SPOTIFY_CLIENT_SECRET")
    refresh_token = require_env("SPOTIFY_REFRESH_TOKEN")

    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("utf-8")
    body = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
    ).encode("utf-8")
    headers = {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    status, data = fetch_json(TOKEN_URL, method="POST", headers=headers, body=body)
    if status != 200 or "access_token" not in data:
        raise RuntimeError(f"Unable to refresh Spotify token: {status} {data}")
    return data["access_token"]


def get_current_track(access_token: str) -> dict[str, Any] | None:
    headers = {"Authorization": f"Bearer {access_token}"}
    status, data = fetch_json(CURRENT_TRACK_URL, headers=headers)

    if status == 200 and data:
        item = data.get("item")
        if not item:
            return None
        return {
            "type": "now_playing" if data.get("is_playing") else "last_played",
            "name": item.get("name", "Unknown track"),
            "artists": ", ".join(artist.get("name", "Unknown artist") for artist in item.get("artists", [])),
            "url": item.get("external_urls", {}).get("spotify", "https://open.spotify.com"),
            "album": item.get("album", {}).get("name", "Unknown album"),
        }

    if status == 204:
        return None

    raise RuntimeError(f"Unable to fetch current Spotify track: {status} {data}")


def get_recent_track(access_token: str) -> dict[str, Any] | None:
    headers = {"Authorization": f"Bearer {access_token}"}
    status, data = fetch_json(RECENT_TRACKS_URL, headers=headers)

    if status != 200:
        raise RuntimeError(f"Unable to fetch recent Spotify tracks: {status} {data}")

    items = data.get("items", [])
    if not items:
        return None

    track = items[0].get("track", {})
    return {
        "type": "recently_played",
        "name": track.get("name", "Unknown track"),
        "artists": ", ".join(artist.get("name", "Unknown artist") for artist in track.get("artists", [])),
        "url": track.get("external_urls", {}).get("spotify", "https://open.spotify.com"),
        "album": track.get("album", {}).get("name", "Unknown album"),
    }


def build_markdown(track: dict[str, Any] | None) -> str:
    if not track:
        return "Currently not listening on Spotify."

    prefix = {
        "now_playing": "Currently listening to",
        "last_played": "Last active track was",
        "recently_played": "Recently played",
    }.get(track["type"], "Listening to")

    return (
        f"{prefix} **[{track['name']}]({track['url']})** by **{track['artists']}**  \n"
        f"Album: *{track['album']}*"
    )


def update_readme(content: str, section: str) -> str:
    start = content.find(START_MARKER)
    end = content.find(END_MARKER)

    if start == -1 or end == -1 or end < start:
        raise RuntimeError("Spotify markers were not found in README")

    before = content[: start + len(START_MARKER)]
    after = content[end:]
    return f"{before}\n{section}\n{after}"


def main() -> int:
    access_token = refresh_access_token()
    track = get_current_track(access_token)
    if track is None:
        track = get_recent_track(access_token)

    with open(README_PATH, "r", encoding="utf-8") as file:
        readme = file.read()

    updated = update_readme(readme, build_markdown(track))

    with open(README_PATH, "w", encoding="utf-8") as file:
        file.write(updated)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise
