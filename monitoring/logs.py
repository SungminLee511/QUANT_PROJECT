"""Logs page — real-time session activity log streamed via SSE.

Shows every strategy tick evaluation, signal, risk decision, order fill,
and session lifecycle event in a raw chronological stream.
"""

import asyncio
import json
import logging
from collections import deque
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from starlette.responses import StreamingResponse

from monitoring.auth import get_current_user
from shared.redis_client import RedisClient, session_channel

logger = logging.getLogger(__name__)

# Per-session in-memory ring buffer (last 10,000 entries)
_BUFFER_SIZE = 10_000
_buffers: dict[str, deque] = {}

# Active SSE client queues — each connected browser gets one
_sse_queues: set[asyncio.Queue] = set()

# Track which session log channels we've subscribed to
_subscribed_sessions: set[str] = set()


def _get_buffer(session_id: str) -> deque:
    if session_id not in _buffers:
        _buffers[session_id] = deque(maxlen=_BUFFER_SIZE)
    return _buffers[session_id]


def cleanup_session_logs(session_id: str) -> None:
    """Remove log buffer and subscription tracking for a deleted session."""
    _buffers.pop(session_id, None)
    _subscribed_sessions.discard(session_id)
    logger.debug("Cleaned up log buffers for session %s", session_id)


async def _on_log_entry(data: dict) -> None:
    """Called by Redis subscriber for every log entry. Fan out to buffers + SSE queues."""
    session_id = data.get("session_id", "")
    if session_id:
        _get_buffer(session_id).append(data)

    # Push to all SSE client queues (non-blocking)
    for queue in list(_sse_queues):
        try:
            queue.put_nowait(data)
        except asyncio.QueueFull:
            pass  # Drop if client is too slow


def create_logs_router(config, redis, templates, session_manager) -> APIRouter:
    router = APIRouter()

    async def _ensure_subscribed(session_id: str) -> None:
        """Subscribe to a session's logs channel if not already."""
        if session_id in _subscribed_sessions:
            return
        channel = session_channel(session_id, "logs")
        await redis.subscribe(channel, _on_log_entry)
        _subscribed_sessions.add(session_id)
        logger.info("Subscribed to logs channel for session %s", session_id)

    @router.get("/logs")
    async def logs_page(request: Request, session_id: Optional[str] = Query(None)):
        user = get_current_user(request)
        if not user:
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url="/login", status_code=302)

        sessions = await session_manager.get_all_sessions()

        # Ensure we're subscribed to all sessions' log channels
        for s in sessions:
            await _ensure_subscribed(s["id"])

        # Enrich with is_running
        for s in sessions:
            s["is_running"] = session_manager.is_running(s["id"])

        return templates.TemplateResponse(request, "logs.html", {
            "user": user,
            "sessions": sessions,
            "active_page": "logs",
            "selected_session": session_id,
        })

    @router.get("/logs/api/entries")
    async def get_entries(request: Request, session_id: Optional[str] = Query(None)):
        user = get_current_user(request)
        if not user:
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        if session_id:
            await _ensure_subscribed(session_id)
            entries = list(_get_buffer(session_id))
        else:
            # Merge all buffers, sort by timestamp
            all_entries = []
            for buf in _buffers.values():
                all_entries.extend(buf)
            all_entries.sort(key=lambda e: e.get("timestamp", ""))
            entries = all_entries[-_BUFFER_SIZE:]

        return JSONResponse({"entries": entries})

    @router.get("/logs/api/stream")
    async def stream_logs(request: Request, session_id: Optional[str] = Query(None)):
        user = get_current_user(request)
        if not user:
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        if session_id:
            await _ensure_subscribed(session_id)

        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        _sse_queues.add(queue)

        async def event_generator():
            try:
                while True:
                    try:
                        entry = await asyncio.wait_for(queue.get(), timeout=25)
                        # Filter by session if specified
                        if session_id and entry.get("session_id") != session_id:
                            continue
                        yield f"data: {json.dumps(entry)}\n\n"
                    except asyncio.TimeoutError:
                        # SSE keepalive comment
                        yield ": keepalive\n\n"
            except asyncio.CancelledError:
                pass
            finally:
                _sse_queues.discard(queue)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return router
