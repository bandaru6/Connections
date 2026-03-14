"""WebSocket manager for real-time event streaming.

Clients connect to GET /ws/events and receive a JSON message for every
ObservationEvent that completes processing.  This gives a live feed of
the ingestion pipeline without polling.

Architecture:
  - ConnectionManager holds all active WebSocket connections in a set.
  - broadcast() is called from the ingest route after each successful
    (or failed) pipeline run.
  - Connections that have disconnected are silently pruned on next broadcast.

Tesla relevance:
  In a vehicle telemetry system, WebSocket streaming is how a monitoring
  dashboard receives live telemetry events as they arrive from the fleet
  — without polling an HTTP endpoint every second.  The equivalent here
  is watching the ingest pipeline process images in real time: each
  ObservationEvent appears in the dashboard the moment it is persisted.

Usage (browser / wscat):
  wscat -c ws://localhost:8000/ws/events
  # Then POST /ingest/upload in another terminal and watch events appear.
"""

import json
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages a set of active WebSocket connections."""

    def __init__(self):
        self.active: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.add(ws)
        logger.info("WebSocket client connected (total active: %d)", len(self.active))

    def disconnect(self, ws: WebSocket) -> None:
        self.active.discard(ws)
        logger.info("WebSocket client disconnected (total active: %d)", len(self.active))

    async def broadcast(self, payload: dict) -> None:
        """Send payload to all connected clients, pruning dead connections."""
        dead: set[WebSocket] = set()
        message = json.dumps(payload, default=str)

        for ws in list(self.active):
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)

        for ws in dead:
            self.active.discard(ws)

        if dead:
            logger.debug("Pruned %d dead WebSocket connections", len(dead))

    @property
    def connection_count(self) -> int:
        return len(self.active)


# Singleton shared across the app
manager = ConnectionManager()
