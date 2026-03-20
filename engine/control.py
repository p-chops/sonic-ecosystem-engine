"""Websocket control server for the Sonic Ecosystem Engine.

Accepts JSON commands and pushes biome change notifications.

Commands (client → server):
  {"cmd": "next"}                 — skip to next biome
  {"cmd": "next", "seed": 42}    — skip to a specific seed
  {"cmd": "info"}                 — request current biome info

Notifications (server → clients):
  {"event": "biome_change", "seed": 12345, "summary": "..."}
  {"event": "info", "seed": 12345, "summary": "..."}
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

import websockets
from websockets.asyncio.server import serve, ServerConnection

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)


class ControlServer:
    """Tiny websocket server for external control (Squeakbot, browser, etc.)."""

    def __init__(self, next_event: asyncio.Event, port: int = 8765):
        self.port = port
        self.next_event = next_event
        self._requested_seed: int | None = None
        self._clients: set[ServerConnection] = set()
        self._current_seed: int | None = None
        self._current_summary: str | None = None
        self._server = None

    @property
    def requested_seed(self) -> int | None:
        """Seed requested by the last 'next' command, or None for random."""
        seed = self._requested_seed
        self._requested_seed = None
        return seed

    def set_current_biome(self, seed: int, summary: str):
        """Update current biome info and notify all connected clients."""
        self._current_seed = seed
        self._current_summary = summary
        msg = json.dumps({
            "event": "biome_change",
            "seed": seed,
            "summary": summary,
        })
        self._broadcast(msg)

    def _broadcast(self, msg: str):
        for ws in list(self._clients):
            try:
                ws.send(msg)
            except Exception:
                pass

    async def _handler(self, ws: ServerConnection):
        self._clients.add(ws)
        remote = ws.remote_address
        log.info("Control client connected: %s", remote)
        try:
            async for raw in ws:
                try:
                    data = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    await ws.send(json.dumps({"error": "invalid JSON"}))
                    continue

                cmd = data.get("cmd", "")

                if cmd == "next":
                    self._requested_seed = data.get("seed")  # None = random
                    self.next_event.set()
                    await ws.send(json.dumps({"ok": True, "cmd": "next"}))
                    log.info("Next biome requested (seed=%s)", self._requested_seed)

                elif cmd == "info":
                    await ws.send(json.dumps({
                        "event": "info",
                        "seed": self._current_seed,
                        "summary": self._current_summary,
                    }))

                else:
                    await ws.send(json.dumps({"error": f"unknown cmd: {cmd}"}))

        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._clients.discard(ws)
            log.info("Control client disconnected: %s", remote)

    async def start(self):
        self._server = await serve(self._handler, "0.0.0.0", self.port)
        log.info("Control server listening on ws://0.0.0.0:%d", self.port)

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
