"""Vercel Python function for live RSS generation."""

from __future__ import annotations

import os
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from youtube_rss import build_rss, collect_videos, read_queries  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        api_key = os.environ.get("YOUTUBE_API_KEY")
        if not api_key:
            self._send_text(500, "YOUTUBE_API_KEY is not set.")
            return

        try:
            queries = read_queries(ROOT / "youtube_query.txt")
            videos = collect_videos(api_key, queries, max_results=25, timeout=25)
            scheme = self.headers.get("x-forwarded-proto", "https")
            host = self.headers.get("host", "")
            feed_url = f"{scheme}://{host}/api/rss" if host else ""
            payload = build_rss(
                videos,
                title="YouTube Search RSS",
                description="YouTube search results generated from youtube_query.txt.",
                feed_url=feed_url,
            )
        except Exception as exc:
            self._send_text(500, f"RSS generation failed: {exc}")
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/rss+xml; charset=utf-8")
        self.send_header("Cache-Control", "s-maxage=1800, stale-while-revalidate=3600")
        self.end_headers()
        self.wfile.write(payload)

    def _send_text(self, status: int, body: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))
