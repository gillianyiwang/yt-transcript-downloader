"""Lightweight YouTube metadata fetcher without heavy dependencies."""

import re
import json
from typing import Optional
import urllib.request
import urllib.parse


class YouTubeMetadata:
    """Lightweight YouTube video metadata fetcher."""

    def __init__(self, url: str):
        self.url = url
        self._title: Optional[str] = None
        self._description: Optional[str] = None
        self._length: Optional[float] = None
        self._thumbnail_url: Optional[str] = None
        self._fetch_metadata()

    def _fetch_metadata(self) -> None:
        """Fetch video metadata by parsing the YouTube page."""
        try:
            # Get video ID
            video_id = self._extract_video_id(self.url)
            if not video_id:
                return

            # Fetch the video page
            watch_url = f"https://www.youtube.com/watch?v={video_id}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            req = urllib.request.Request(watch_url, headers=headers)

            with urllib.request.urlopen(req, timeout=10) as response:
                html = response.read().decode('utf-8')

            # Extract metadata from ytInitialPlayerResponse JSON
            match = re.search(r'var ytInitialPlayerResponse\s*=\s*({.+?});', html)
            if match:
                data = json.loads(match.group(1))
                video_details = data.get('videoDetails', {})

                self._title = video_details.get('title')
                self._description = video_details.get('shortDescription')

                length_seconds = video_details.get('lengthSeconds')
                if length_seconds:
                    self._length = float(length_seconds)

                # Get thumbnail (highest quality available)
                self._thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"

        except Exception as e:
            print(f"[YouTubeMetadata] Error fetching metadata: {e}")
            # Fallback to basic thumbnail if everything else fails
            video_id = self._extract_video_id(self.url)
            if video_id:
                self._thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

    @staticmethod
    def _extract_video_id(url: str) -> Optional[str]:
        """Extract video ID from YouTube URL."""
        patterns = [
            r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
            r'(?:embed\/)([0-9A-Za-z_-]{11})',
            r'^([0-9A-Za-z_-]{11})$'
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    @property
    def title(self) -> Optional[str]:
        return self._title

    @property
    def description(self) -> Optional[str]:
        return self._description

    @property
    def length(self) -> Optional[float]:
        return self._length

    @property
    def thumbnail_url(self) -> Optional[str]:
        return self._thumbnail_url
