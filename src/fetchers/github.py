from typing import List, Dict, Any

import requests


def fetch(query: str = "stars:>100", sort: str = "updated", per_page: int = 10) -> List[Dict[str, Any]]:
    """Search GitHub repositories."""
    url = "https://api.github.com/search/repositories"
    params = {"q": query, "sort": sort, "order": "desc", "per_page": per_page}
    resp = requests.get(url, params=params, timeout=30, proxies={"http": None, "https": None})
    resp.raise_for_status()
    data = resp.json()

    items = data.get("items", [])
    results = []
    for item in items:
        results.append(
            {
                "title": item.get("full_name", "Unknown"),
                "summary": item.get("description") or "",
                "url": item.get("html_url", ""),
                "published_at": item.get("updated_at", ""),
            }
        )
    return results
