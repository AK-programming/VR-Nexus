"""
Task 7.1.1 - WebSocket streaming during tender processing
Linked requirement: TRK-01

Keeps track of which browser tabs are currently watching which tender, so
that when the pipeline (real or simulated) updates a tender's progress, we
can push that update out to everyone watching, live.

Deliberately kept as a simple in-process dict rather than Redis pub/sub.
That's a real simplification worth knowing about: this only works because
the app runs as a single uvicorn process on one laptop, not deployed. If
this were ever split across multiple worker processes (e.g. Celery workers
running the real pipeline in a separate process from the FastAPI process
serving WebSockets), broadcast() would need to publish through Redis
instead, since two separate processes can't share this Python dict.
Flagging this now so it isn't a surprise later - Celery/Redis are already
in requirements.txt for exactly that future step.

The Evidence Library progress socket does NOT use this class - see
app/api/routes/library_ws.py, which polls the persisted index_jobs row
instead, precisely so it keeps working when the stage transitions happen
inside a Celery worker process.
"""
import asyncio
from collections import defaultdict
from uuid import UUID

from fastapi import WebSocket


class TenderProgressConnectionManager:
    def __init__(self) -> None:
        # tender_id -> set of open sockets currently watching it. A tender
        # can have more than one watcher (e.g. two teammates with the same
        # tender open, or one person with two tabs).
        self._connections: dict[UUID, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, tender_id: UUID, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[tender_id].add(websocket)

    async def disconnect(self, tender_id: UUID, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections[tender_id].discard(websocket)
            if not self._connections[tender_id]:
                del self._connections[tender_id]

    async def broadcast(self, tender_id: UUID, payload: dict) -> None:
        """Sends payload to every socket currently watching this tender.
        Silently drops sockets that have gone stale (closed without us
        noticing yet) rather than letting one dead connection break the
        broadcast for everyone else watching the same tender."""
        dead: list[WebSocket] = []
        for ws in list(self._connections.get(tender_id, ())):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections[tender_id].discard(ws)


# Single shared instance - imported by both the WebSocket route (to
# register/remove watchers) and the pipeline runner (to broadcast updates).
manager = TenderProgressConnectionManager()
