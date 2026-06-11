import asyncio
import json
from typing import List, AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

import database as db

router = APIRouter()

# Active SSE clients
_clients: List[asyncio.Queue] = []


@router.get("/sse")
async def sse_endpoint() -> StreamingResponse:
    async def event_generator() -> AsyncGenerator[str, None]:
        queue: asyncio.Queue = asyncio.Queue()
        _clients.append(queue)
        try:
            # Send heartbeat / connection confirmation
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"
            while True:
                data = await queue.get()
                yield f"data: {json.dumps(data)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if queue in _clients:
                _clients.remove(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def broadcast_new_items(items: List[db.FeedItem]) -> None:
    """Push new items to all connected SSE clients."""
    if not items or not _clients:
        return
    payload = {
        "type": "new_items",
        "items": [
            {
                "id": it.id,
                "title": it.title,
                "summary": it.summary,
                "url": it.url,
                "source_id": it.source_id,
                "source_name": it.source_name,
                "published_at": it.published_at,
                "fetched_at": it.fetched_at,
                "is_read": it.is_read,
                "is_starred": it.is_starred,
            }
            for it in items
        ],
    }
    for queue in _clients:
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass
