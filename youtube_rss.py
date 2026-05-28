#!/usr/bin/env python3
"""Generate an RSS feed from YouTube Data API search results."""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import sys
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Iterable


YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_WATCH_URL = "https://www.youtube.com/watch"
ATOM_NS = "http://www.w3.org/2005/Atom"


@dataclass(frozen=True)
class SearchQuery:
    text: str
    days: int


@dataclass(frozen=True)
class VideoItem:
    video_id: str
    title: str
    description: str
    channel_title: str
    published_at: datetime
    query: str
    thumbnail_url: str

    @property
    def url(self) -> str:
        return f"{YOUTUBE_WATCH_URL}?v={urllib.parse.quote(self.video_id)}"


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def read_queries(path: Path) -> list[SearchQuery]:
    if not path.exists():
        raise FileNotFoundError(f"query file not found: {path}")

    queries: list[SearchQuery] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        for line_number, row in enumerate(reader, start=1):
            if not row or not "".join(row).strip():
                continue
            if row[0].lstrip().startswith("#"):
                continue
            if len(row) < 2:
                raise ValueError(f"{path}:{line_number}: expected 'query,days'")

            query = row[0].strip()
            days_text = row[1].strip()
            try:
                days = int(days_text)
            except ValueError as exc:
                if line_number == 1 and "検索" in query:
                    continue
                raise ValueError(f"{path}:{line_number}: invalid days: {days_text}") from exc

            if not query:
                raise ValueError(f"{path}:{line_number}: query is empty")
            if days < 0:
                raise ValueError(f"{path}:{line_number}: days must be 0 or greater")

            queries.append(SearchQuery(query, days))

    if not queries:
        raise ValueError(f"no queries found in {path}")
    return queries


def parse_youtube_datetime(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def youtube_request(params: dict[str, str | int], timeout: int) -> dict:
    url = f"{YOUTUBE_SEARCH_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": "youtube_rss/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"YouTube API HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"YouTube API request failed: {exc.reason}") from exc


def search_videos(
    api_key: str,
    search_query: SearchQuery,
    *,
    max_results: int,
    timeout: int,
    now: datetime,
) -> list[VideoItem]:
    published_after = (now - timedelta(days=search_query.days)).replace(microsecond=0)
    published_after_text = published_after.isoformat().replace("+00:00", "Z")

    params: dict[str, str | int] = {
        "part": "snippet",
        "type": "video",
        "order": "date",
        "maxResults": max_results,
        "q": search_query.text,
        "publishedAfter": published_after_text,
        "key": api_key,
    }
    payload = youtube_request(params, timeout)

    items: list[VideoItem] = []
    for item in payload.get("items", []):
        video_id = item.get("id", {}).get("videoId")
        snippet = item.get("snippet", {})
        if not video_id or not snippet:
            continue
        thumbnails = snippet.get("thumbnails", {})
        thumbnail = (
            thumbnails.get("high")
            or thumbnails.get("medium")
            or thumbnails.get("default")
            or {}
        )
        items.append(
            VideoItem(
                video_id=video_id,
                title=snippet.get("title", "").strip(),
                description=snippet.get("description", "").strip(),
                channel_title=snippet.get("channelTitle", "").strip(),
                published_at=parse_youtube_datetime(snippet["publishedAt"]),
                query=search_query.text,
                thumbnail_url=thumbnail.get("url", ""),
            )
        )
    return items


def collect_videos(
    api_key: str,
    queries: Iterable[SearchQuery],
    *,
    max_results: int,
    timeout: int,
    request_delay: float,
) -> list[VideoItem]:
    now = datetime.now(timezone.utc)
    videos_by_id: dict[str, VideoItem] = {}
    for index, query in enumerate(queries):
        if index > 0 and request_delay > 0:
            time.sleep(request_delay)
        print(f"searching: {query.text} ({query.days} day(s))", flush=True)
        for video in search_videos(
            api_key,
            query,
            max_results=max_results,
            timeout=timeout,
            now=now,
        ):
            videos_by_id.setdefault(video.video_id, video)
    return sorted(videos_by_id.values(), key=lambda item: item.published_at, reverse=True)


def build_rss(
    videos: list[VideoItem],
    *,
    title: str,
    description: str,
    feed_url: str,
) -> bytes:
    ET.register_namespace("atom", ATOM_NS)
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = title
    ET.SubElement(channel, "link").text = feed_url or "https://www.youtube.com/"
    ET.SubElement(channel, "description").text = description
    ET.SubElement(channel, "language").text = "ja"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(
        datetime.now(timezone.utc), usegmt=True
    )
    ET.SubElement(channel, "generator").text = "youtube_rss.py"

    if feed_url:
        ET.SubElement(
            channel,
            f"{{{ATOM_NS}}}link",
            {"href": feed_url, "rel": "self", "type": "application/rss+xml"},
        )

    for video in videos:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = video.title
        ET.SubElement(item, "link").text = video.url
        ET.SubElement(item, "guid", {"isPermaLink": "true"}).text = video.url
        ET.SubElement(item, "pubDate").text = format_datetime(video.published_at, usegmt=True)

        body_parts = [
            f"Channel: {video.channel_title}",
            f"Matched query: {video.query}",
            f"Published: {video.published_at.isoformat()}",
        ]
        if video.thumbnail_url:
            escaped_url = html.escape(video.thumbnail_url, quote=True)
            body_parts.append(f'<p><img src="{escaped_url}" alt=""></p>')
        if video.description:
            body_parts.append(video.description)
        ET.SubElement(item, "description").text = "\n\n".join(body_parts)

    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)


def write_index(path: Path, videos: list[VideoItem], feed_name: str) -> None:
    rows = []
    for video in videos[:100]:
        title = html.escape(video.title)
        channel = html.escape(video.channel_title)
        query = html.escape(video.query)
        published = html.escape(video.published_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
        url = html.escape(video.url, quote=True)
        rows.append(
            f'<li><a href="{url}">{title}</a><br><small>{channel} / {query} / {published}</small></li>'
        )

    body = "\n".join(rows) if rows else "<li>No videos found.</li>"
    html_text = textwrap.dedent(
        f"""\
        <!doctype html>
        <html lang="ja">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>YouTube Search RSS</title>
          <link rel="alternate" type="application/rss+xml" title="YouTube Search RSS" href="{html.escape(feed_name, quote=True)}">
          <style>
            body {{ font-family: system-ui, sans-serif; margin: 2rem; line-height: 1.6; max-width: 900px; }}
            code {{ background: #f3f3f3; padding: .1rem .3rem; border-radius: 4px; }}
            li {{ margin: 0 0 1rem; }}
          </style>
        </head>
        <body>
          <h1>YouTube Search RSS</h1>
          <p>RSS: <a href="{html.escape(feed_name, quote=True)}"><code>{html.escape(feed_name)}</code></a></p>
          <ol>
            {body}
          </ol>
        </body>
        </html>
        """
    )
    path.write_text(html_text, encoding="utf-8")


def write_json(path: Path, videos: list[VideoItem]) -> None:
    payload = [
        {
            "video_id": video.video_id,
            "title": video.title,
            "url": video.url,
            "description": video.description,
            "channel_title": video.channel_title,
            "published_at": video.published_at.isoformat(),
            "query": video.query,
            "thumbnail_url": video.thumbnail_url,
        }
        for video in videos
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def generate_feed(
    *,
    query_file: Path,
    output_file: Path,
    api_key: str,
    max_results: int,
    timeout: int,
    request_delay: float,
    title: str,
    description: str,
    feed_url: str,
    json_output: Path | None = None,
    create_index: bool = True,
) -> list[VideoItem]:
    queries = read_queries(query_file)
    videos = collect_videos(
        api_key,
        queries,
        max_results=max_results,
        timeout=timeout,
        request_delay=request_delay,
    )

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_bytes(
        build_rss(videos, title=title, description=description, feed_url=feed_url)
    )

    if json_output:
        json_output.parent.mkdir(parents=True, exist_ok=True)
        write_json(json_output, videos)

    if create_index:
        write_index(output_file.with_name("index.html"), videos, output_file.name)

    return videos


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query-file", default="youtube_query.txt", type=Path)
    parser.add_argument("--output", default=Path("public/rss.xml"), type=Path)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--max-results", default=25, type=int)
    parser.add_argument("--timeout", default=30, type=int)
    parser.add_argument(
        "--request-delay",
        default=float(os.environ.get("YOUTUBE_REQUEST_DELAY", "7")),
        type=float,
        help="Seconds to wait between YouTube search requests.",
    )
    parser.add_argument("--title", default="YouTube Search RSS")
    parser.add_argument(
        "--description",
        default="YouTube search results generated from youtube_query.txt.",
    )
    parser.add_argument(
        "--feed-url",
        default=os.environ.get("PUBLIC_FEED_URL", ""),
        help="Absolute RSS URL used for the channel link and atom:self.",
    )
    parser.add_argument("--no-index", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    load_dotenv(Path(".env"))

    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("YOUTUBE_API_KEY is not set. Set it in the environment or .env.", file=sys.stderr)
        return 2

    if args.max_results < 1 or args.max_results > 50:
        print("--max-results must be between 1 and 50.", file=sys.stderr)
        return 2

    try:
        videos = generate_feed(
            query_file=args.query_file,
            output_file=args.output,
            api_key=api_key,
            max_results=args.max_results,
            timeout=args.timeout,
            request_delay=args.request_delay,
            title=args.title,
            description=args.description,
            feed_url=args.feed_url,
            json_output=args.json_output,
            create_index=not args.no_index,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"wrote {args.output} ({len(videos)} item(s))")
    if args.json_output:
        print(f"wrote {args.json_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
