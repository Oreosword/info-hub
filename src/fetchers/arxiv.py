from typing import List, Dict, Any
from xml.etree import ElementTree as ET

import requests


def fetch(search_query: str = "cat:cs.AI", max_results: int = 10) -> List[Dict[str, Any]]:
    """Search arXiv via OAI-PMH / API."""
    url = "https://export.arxiv.org/api/query"
    params = {"search_query": search_query, "max_results": max_results, "sortBy": "submittedDate", "sortOrder": "descending"}

    resp = requests.get(url, params=params, timeout=30, proxies={"http": None, "https": None})
    resp.raise_for_status()
    xml_text = resp.text

    # Parse Atom XML
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(xml_text)
    results = []
    for entry in root.findall("atom:entry", ns):
        title_el = entry.find("atom:title", ns)
        summary_el = entry.find("atom:summary", ns)
        link_el = entry.find("atom:link[@rel='alternate']", ns) or entry.find("atom:link", ns)
        published_el = entry.find("atom:published", ns)

        title = (title_el.text or "").strip().replace("\n", " ")
        summary = (summary_el.text or "").strip()[:500] if summary_el is not None else ""
        url = link_el.get("href", "") if link_el is not None else ""
        published = published_el.text or "" if published_el is not None else ""

        results.append(
            {
                "title": title,
                "summary": summary,
                "url": url,
                "published_at": published,
            }
        )
    return results
