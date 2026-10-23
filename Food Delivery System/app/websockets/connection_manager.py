
import asyncio
import logging
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.connections = defaultdict(set)
        self.loop = None

    async def connect(self, websocket: WebSocket, room: str):
        await websocket.accept()
        self.loop = asyncio.get_running_loop()
        self.connections[room].add(websocket)

    def disconnect(self, websocket: WebSocket, room: str):
        clients = self.connections.get(room)

        if clients:
            clients.discard(websocket)

            if not clients:
                self.connections.pop(room, None)

    async def broadcast(self, room: str, message: dict):
        clients = list(self.connections.get(room, set()))

        for websocket in clients:
            try:
                await websocket.send_json(message)
            except Exception:
                logger.exception(
                    "Failed to send WebSocket message to room %s",
                    room,
                )
                self.disconnect(websocket, room)

    def broadcast_sync(self, room: str, message: dict):
        """Schedule a broadcast from a synchronous FastAPI endpoint."""
        loop = self.loop

        if loop is None or not loop.is_running():
            logger.warning(
                "WebSocket broadcast skipped: no active event loop (room=%s)",
                room,
            )
            return

        try:
            asyncio.run_coroutine_threadsafe(
                self.broadcast(room, message),
                loop,
            )
        except RuntimeError:
            logger.exception(
                "Unable to schedule WebSocket broadcast to room %s",
                room,
            )


manager = ConnectionManager()

