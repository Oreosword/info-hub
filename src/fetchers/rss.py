import feedparser
from typing import List, Dict, Any


def fetch(feed_url: str) -> List[Dict[str, Any]]:
    """Parse RSS/Atom feed and return normalized items."""
    parsed = feedparser.parse(feed_url)
    results = []
    for entry in parsed.entries:
        published = ""
        if hasattr(entry, "published"):
            published = entry.published
        elif hasattr(entry, "updated"):
            published = entry.updated
        results.append(
            {
                "title": entry.get("title", "Untitled"),
                "summary": _clean_summary(entry.get("summary", "")),
                "url": entry.get("link", ""),
                "published_at": published,
            }
        )
    return results


def _clean_summary(html: str) -> str:
    """Very basic HTML tag stripping."""
    import re
    text = re.sub(r"<[^>]+>", "", html)
    return text.strip()[:500]
