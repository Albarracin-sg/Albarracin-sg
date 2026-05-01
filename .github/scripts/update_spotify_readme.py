from __future__ import annotations

import base64
import html
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


README_PATH = os.environ.get("README_PATH", "README.md")
CARD_PATH = os.environ.get("SPOTIFY_CARD_PATH", ".github/assets/spotify-card.svg")
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


def fetch_binary(url: str) -> tuple[bytes, str]:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request) as response:
        return response.read(), response.headers.get_content_type() or "image/jpeg"


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
            "album_image_url": (item.get("album", {}).get("images") or [{}])[0].get("url", ""),
            "duration_ms": item.get("duration_ms") or 0,
            "progress_ms": data.get("progress_ms") or 0,
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
        "album_image_url": (track.get("album", {}).get("images") or [{}])[0].get("url", ""),
        "duration_ms": track.get("duration_ms") or 0,
        "progress_ms": 0,
    }


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def ms_to_clock(milliseconds: int) -> str:
    total_seconds = max(0, milliseconds // 1000)
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}"


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def build_image_data_url(image_url: str) -> str:
    if not image_url:
        return ""
    payload, content_type = fetch_binary(image_url)
    encoded = base64.b64encode(payload).decode("utf-8")
    return f"data:{content_type};base64,{encoded}"


def build_svg(track: dict[str, Any] | None) -> str:
    if not track:
        return """<svg width="460" height="136" viewBox="0 0 460 136" fill="none" xmlns="http://www.w3.org/2000/svg"><rect width="460" height="136" rx="14" fill="#121212"/><rect x="16" y="16" width="104" height="104" rx="10" fill="#2A2A2A"/><text x="144" y="40" fill="#FFFFFF" font-size="18" font-weight="700" font-family="Inter,Segoe UI,Arial,sans-serif">Spotify</text><text x="144" y="66" fill="#B3B3B3" font-size="14" font-family="Inter,Segoe UI,Arial,sans-serif">No listening activity available right now.</text><text x="144" y="92" fill="#1ED760" font-size="13" font-weight="700" font-family="Inter,Segoe UI,Arial,sans-serif">STANDBY</text><rect x="144" y="108" width="300" height="4" rx="2" fill="#3A3A3A"/></svg>"""

    card_width = 460
    card_height = 136
    cover_size = 104
    cover_x = 16
    cover_y = 16
    content_x = 144
    progress_bar_x = 144
    progress_bar_y = 104
    progress_bar_width = 300
    duration_ms = int(track.get("duration_ms") or 0)
    progress_ms = int(track.get("progress_ms") or 0)
    progress_ratio = 0.0 if duration_ms <= 0 else clamp(progress_ms / duration_ms, 0.0, 1.0)
    progress_width = progress_bar_width * progress_ratio

    status_label = "NOW PLAYING" if track.get("type") == "now_playing" else "RECENTLY PLAYED"
    title = html.escape(truncate(track.get("name", "Unknown track"), 28))
    artist = html.escape(truncate(track.get("artists", "Unknown artist"), 34))
    album = html.escape(truncate(track.get("album", "Unknown album"), 32))
    elapsed = ms_to_clock(progress_ms)
    remaining = f"-{ms_to_clock(max(0, duration_ms - progress_ms))}" if duration_ms else "--:--"
    image_data_url = build_image_data_url(track.get("album_image_url", ""))

    image_block = (
        f'<image href="{image_data_url}" x="{cover_x}" y="{cover_y}" width="{cover_size}" height="{cover_size}" preserveAspectRatio="xMidYMid slice" clip-path="url(#coverClip)"/>'
        if image_data_url
        else f'<rect x="{cover_x}" y="{cover_y}" width="{cover_size}" height="{cover_size}" rx="10" fill="#5B5BD6"/>'
    )

    return f"""
<svg width="{card_width}" height="{card_height}" viewBox="0 0 {card_width} {card_height}" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Spotify currently playing card">
  <defs>
    <clipPath id="coverClip">
      <rect x="{cover_x}" y="{cover_y}" width="{cover_size}" height="{cover_size}" rx="10" />
    </clipPath>
  </defs>
  <rect width="{card_width}" height="{card_height}" rx="14" fill="#121212"/>
  {image_block}
  <text x="{content_x}" y="36" fill="#FFFFFF" font-size="18" font-weight="700" font-family="Inter,Segoe UI,Arial,sans-serif">{title}</text>
  <text x="{content_x}" y="60" fill="#B3B3B3" font-size="14" font-family="Inter,Segoe UI,Arial,sans-serif">{artist}</text>
  <circle cx="{content_x + 8}" cy="82" r="8" fill="#1ED760"/>
  <text x="{content_x + 24}" y="87" fill="#1ED760" font-size="13" font-weight="700" font-family="Inter,Segoe UI,Arial,sans-serif">{status_label}</text>
  <text x="{content_x}" y="122" fill="#8E8E8E" font-size="12" font-family="Inter,Segoe UI,Arial,sans-serif">{elapsed}</text>
  <text x="412" y="122" text-anchor="end" fill="#8E8E8E" font-size="12" font-family="Inter,Segoe UI,Arial,sans-serif">{remaining}</text>
  <text x="{content_x}" y="138" fill="#121212" font-size="1">{album}</text>
  <rect x="{progress_bar_x}" y="{progress_bar_y}" width="{progress_bar_width}" height="4" rx="2" fill="#4A4A4A"/>
  <rect x="{progress_bar_x}" y="{progress_bar_y}" width="{progress_width:.2f}" height="4" rx="2" fill="#1ED760"/>
</svg>
""".strip()


def build_markdown(track: dict[str, Any] | None) -> str:
    if not track:
        return '<img src="./.github/assets/spotify-card.svg" alt="Spotify card" width="460" />'

    return (
        f'<a href="{html.escape(track["url"], quote=True)}">'
        f'<img src="./.github/assets/spotify-card.svg" alt="Spotify now playing card" width="460" />'
        f"</a>"
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

    os.makedirs(os.path.dirname(CARD_PATH), exist_ok=True)
    with open(CARD_PATH, "w", encoding="utf-8") as file:
        file.write(build_svg(track))

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise
