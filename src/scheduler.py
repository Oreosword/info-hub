import asyncio
from typing import List

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

import database as db
import workflow
from fetchers import rss, github, hackernews, arxiv
from fetchers.summarizer import generate_summary
from routers import sse

scheduler = AsyncIOScheduler()


def _fetch_and_store(source: db.FeedSource) -> List[int]:
    cfg = source.config
    items: List[dict] = []

    try:
        if source.type == "rss":
            items = rss.fetch(cfg.get("feed_url", ""))
        elif source.type == "github":
            items = github.fetch(cfg.get("query", ""), cfg.get("sort", "updated"), cfg.get("per_page", 10))
        elif source.type == "hackernews":
            items = hackernews.fetch(cfg.get("query", ""), cfg.get("tags", "story"), cfg.get("hits_per_page", 10))
        elif source.type == "arxiv":
            items = arxiv.fetch(cfg.get("search_query", "cat:cs.AI"), cfg.get("max_results", 10))
        else:
            print(f"[scheduler] Unknown source type: {source.type}")
            return []
    except Exception as e:
        print(f"[scheduler] {source.name}: {e}")
        return []

    normalized = []
    for it in items:
        ai_summary = generate_summary(it["title"], it.get("summary", ""), source.type)
        normalized.append(
            {"title": it["title"], "summary": it.get("summary", ""), "url": it["url"],
             "source_id": source.id, "source_name": source.name,
             "source_type": source.type, "published_at": it.get("published_at"), "ai_summary": ai_summary}
        )

    inserted_ids = db.insert_items(normalized)
    try:
        workflow.ingest_feed_items(normalized)
    except Exception as e:
        print(f"[scheduler] Candidate ingest failed for {source.name}: {e}")

    if inserted_ids:
        print(f"[scheduler] {source.name}: +{len(inserted_ids)} items")
    else:
        print(f"[scheduler] {source.name}: no new items")
    return inserted_ids


async def run_fetch(source: db.FeedSource) -> None:
    loop = asyncio.get_running_loop()
    inserted_ids = await loop.run_in_executor(None, _fetch_and_store, source)
    if inserted_ids:
        new_items = await loop.run_in_executor(None, lambda: [db.get_item(iid) for iid in inserted_ids])
        sse.broadcast_new_items([i for i in new_items if i is not None])


def schedule_all() -> None:
    scheduler.remove_all_jobs()
    for src in db.get_sources(enabled_only=True):
        scheduler.add_job(
            run_fetch,
            trigger=IntervalTrigger(minutes=src.interval_minutes),
            args=[src],
            id=f"fetch_{src.id}",
            replace_existing=True,
        )
        print(f"[scheduler] Scheduled {src.name} every {src.interval_minutes} min")


def start() -> None:
    scheduler.start()


def shutdown() -> None:
    scheduler.shutdown()
