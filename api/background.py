"""Loops the API runs for its whole lifetime (started in main.lifespan)."""
import asyncio
import logging

from psycopg2.extras import DictCursor

from auth import evict_user_token_cache
from database import get_connection
from platform_clients import _aioredis_client, get_redis

logger = logging.getLogger('api')


def _relay_outbox_once() -> int:
    """Move up to 10 outbox rows to Redis. Blocking I/O, so run it in a thread."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("""
                SELECT * FROM outbox_events
                ORDER BY id ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 10;
            """)
            events = cur.fetchall()
            if events:
                r = get_redis()
                pipe = r.pipeline()
                for event in events:
                    pipe.xadd(event['stream_name'], event['payload'], maxlen=10000)
                pipe.execute()

                ids = tuple(event['id'] for event in events)
                cur.execute("DELETE FROM outbox_events WHERE id IN %s;", (ids,))
            conn.commit()
            return len(events)


async def outbox_relay():
    """Continuously poll the outbox_events table and forward to Redis.

    The DB and Redis calls are synchronous; running them directly in this
    coroutine froze the event loop (every websocket, SSE stream and async
    request on the replica) for the duration of each poll.
    """
    while True:
        try:
            moved = await asyncio.to_thread(_relay_outbox_once)
        except Exception as e:
            logger.error(f"Outbox relay error: {e}")
            await asyncio.sleep(5)
            continue
        if not moved:
            await asyncio.sleep(1)

async def cache_eviction_listener():
    """Listen for cross-replica cache eviction events."""
    while True:
        try:
            pubsub = _aioredis_client.pubsub()
            await pubsub.subscribe("shipzen:events:cache_evict")
            async for message in pubsub.listen():
                if message["type"] == "message":
                    user_id = message["data"].decode("utf-8") if isinstance(message["data"], bytes) else message["data"]
                    evict_user_token_cache(user_id)
        except Exception as e:
            logger.error(f"Cache eviction listener error: {e}")
            await asyncio.sleep(5)
