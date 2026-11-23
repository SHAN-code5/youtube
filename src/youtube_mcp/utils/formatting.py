"""Response formatting utilities for LLM consumption."""

import re
from datetime import timedelta

# YouTube durations: PT#H#M#S, or P#DT#H#M#S (and P#W#DT...) for videos >= 1 day,
# and P0D for live/upcoming broadcasts.
_ISO_DURATION = re.compile(
    r"P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?"
)


def _duration_seconds(iso_duration: str) -> int | None:
    """Parse an ISO 8601 duration into total seconds; None if missing or unparseable."""
    if not iso_duration:
        return None
    m = _ISO_DURATION.fullmatch(iso_duration)
    if not m:
        return None
    weeks, days, hours, minutes, seconds = (int(g) if g else 0 for g in m.groups())
    return weeks * 604800 + days * 86400 + hours * 3600 + minutes * 60 + seconds


def format_duration(iso_duration: str) -> str:
    """Convert ISO 8601 duration (PT1H2M3S) to human-readable format."""
    total = _duration_seconds(iso_duration)
    if total is None:
        return "unknown"
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)


def format_count(n: int | str) -> str:
    """Format large numbers with K/M/B suffixes."""
    n = int(n)
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def format_video_summary(video: dict) -> dict:
    """Extract and format key fields from a YouTube Data API video resource."""
    snippet = video.get("snippet", {})
    stats = video.get("statistics", {})
    content = video.get("contentDetails", {})

    return {
        "id": video.get("id"),
        "title": snippet.get("title"),
        "channel": snippet.get("channelTitle"),
        "published_at": snippet.get("publishedAt"),
        "duration": format_duration(content.get("duration", "")),
        "views": int(stats.get("viewCount", 0)),
        "likes": int(stats.get("likeCount", 0)),
        "comments": int(stats.get("commentCount", 0)),
        "description": snippet.get("description", "")[:500],
        "tags": snippet.get("tags", []),
        "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url"),
        "is_short": _is_likely_short(content.get("duration", "")),
    }


def _is_likely_short(iso_duration: str) -> bool:
    """Heuristic: videos <= 60 seconds are likely Shorts."""
    total_seconds = _duration_seconds(iso_duration)
    # A zero length (P0D for live/upcoming broadcasts) is not a Short.
    return total_seconds is not None and 0 < total_seconds <= 60
