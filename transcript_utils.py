from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from urllib.parse import urlparse, parse_qs

import re


# ---------- Data model ----------


@dataclass
class AppState:
    """Holds runtime state for the transcript downloader."""

    full_segments: List[Dict] = field(default_factory=list)
    video_title: Optional[str] = None
    video_description: Optional[str] = None
    current_text: str = ""
    # Seconds (float) from pytube; may be None if unavailable
    video_length: Optional[float] = None
    video_url: Optional[str] = None


# ---------- URL & time utilities ----------


def extract_video_id(url: str) -> Optional[str]:
    """Extract YouTube video ID from typical URL formats."""
    try:
        parsed = urlparse(url.strip())
        if parsed.hostname in ("www.youtube.com", "youtube.com", "m.youtube.com"):
            qs = parse_qs(parsed.query)
            return qs.get("v", [None])[0]
        if parsed.hostname in ("youtu.be",):
            return parsed.path.lstrip("/")
        # Fallback: if it looks like a bare 11-char ID
        if len(url.strip()) == 11:
            return url.strip()
    except Exception:
        return None
    return None


def parse_timecode(s: Optional[str]) -> Optional[float]:
    """Parse 'mm:ss' or 'hh:mm:ss' into seconds (float). Return None if empty/invalid."""
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    parts = s.split(":")
    try:
        parts = [float(p) for p in parts]
    except ValueError:
        return None
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        m, sec = parts
        return m * 60 + sec
    if len(parts) == 3:
        h, m, sec = parts
        return h * 3600 + m * 60 + sec
    return None


def format_timestamp(seconds: float) -> str:
    """Format seconds as hh:mm:ss or mm:ss."""
    total = int(round(seconds))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def get_video_duration(state: AppState) -> Optional[float]:
    """Return best-guess duration in seconds (video_length or from transcript)."""
    if state.video_length is not None:
        return float(state.video_length)
    if state.full_segments:
        last = state.full_segments[-1]
        return float(last["start"] + last.get("duration", 0))
    return None


# ---------- text & size utilities ----------


def estimate_file_size_bytes(text: str) -> int:
    """Approximate file size in bytes for UTF-8 encoded text."""
    return len(text.encode("utf-8"))


def format_size(bytes_count: int) -> str:
    """Human-readable size string (B / KB / MB) for a byte count."""
    if bytes_count < 1024:
        return f"{bytes_count} B"
    kb = bytes_count / 1024
    if kb < 1024:
        return f"{kb:.1f} KB"
    mb = kb / 1024
    return f"{mb:.2f} MB"


# ---------- transcript formatting ----------


def build_filtered_text(
    segments: List[Dict],
    start_str: str,
    end_str: str,
    display_mode: str,
    include_title: bool,
    include_description: bool,
    video_title: Optional[str],
    video_description: Optional[str],
) -> str:
    """
    Apply time filtering, timestamp placement, and optional title/description.

    display_mode options:
      - "ts_newline"  -> [00:10] on its own line, then text
      - "ts_before"   -> [00:10] text
      - "ts_after"    -> text [00:10]
      - "no_ts_lines" -> text, line-breaks kept, no timestamps
      - "no_ts_block" -> one big block, no timestamps
    """
    if not segments:
        return ""

    start_sec = parse_timecode(start_str)
    end_sec = parse_timecode(end_str)

    idx_start = 0
    idx_end = len(segments) - 1

    # "closest previous timestamp" logic for start
    if start_sec is not None:
        for i, seg in enumerate(segments):
            if seg["start"] >= start_sec:
                idx_start = max(0, i - 1)
                break
        else:
            idx_start = max(0, len(segments) - 2)

    # "closest next timestamp" logic for end
    if end_sec is not None:
        last_idx = 0
        for i, seg in enumerate(segments):
            if seg["start"] <= end_sec:
                last_idx = i
        idx_end = min(len(segments) - 1, last_idx + 1)

    filtered = segments[idx_start : idx_end + 1]
    lines = []

    for seg in filtered:
        ts = format_timestamp(seg["start"])
        text = seg["text"].replace("\n", " ").strip()

        if display_mode == "ts_newline":
            line = f"[{ts}]\n{text}"
        elif display_mode == "ts_before":
            line = f"[{ts}] {text}"
        elif display_mode == "ts_after":
            line = f"{text} [{ts}]"
        else:
            # "no_ts_lines" / "no_ts_block"
            line = text

        lines.append(line)

    if display_mode == "no_ts_block":
        body = " ".join(lines)
    else:
        body = "\n".join(lines)

    header_parts = []
    if include_title and video_title:
        header_parts.append(video_title.strip())
    if include_description and video_description:
        header_parts.append(video_description.strip())

    if header_parts:
        header = "\n\n".join(header_parts)
        if body:
            return header + "\n\n" + body
        return header
    return body


def sanitize_filename(name: str) -> str:
    """
    Remove illegal filename characters across macOS/Windows/Linux:
    \ / : * ? " < > |
    Also collapse spaces to underscores.
    """
    # Strip illegal characters
    name = re.sub(r'[\\/:*?"<>|]', "", name)

    # Replace whitespace runs with "_"
    name = re.sub(r"\s+", "_", name)

    # Remove leading/trailing underscores
    name = name.strip("_")

    return name or "transcript"
