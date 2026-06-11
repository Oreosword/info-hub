from typing import List, Dict, Any

import requests


def fetch(query: str = "", tags: str = "story", hits_per_page: int = 10) -> List[Dict[str, Any]]:
    """Search Hacker News via Algolia API."""
    url = "https://hn.algolia.com/api/v1/search"
    params: Dict[str, Any] = {"tags": tags, "hitsPerPage": hits_per_page}
    if query:
        params["query"] = query

    resp = requests.get(url, params=params, timeout=30, proxies={"http": None, "https": None})
    resp.raise_for_status()
    data = resp.json()

    results = []
    for hit in data.get("hits", []):
        results.append(
            {
                "title": hit.get("title") or hit.get("story_text", "Untitled")[:80],
                "summary": hit.get("url", ""),
                "url": f"https://news.ycombinator.com/item?id={hit['objectID']}",
                "published_at": hit.get("created_at", ""),
            }
        )
    return results
