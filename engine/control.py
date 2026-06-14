"""Websocket control server for the Sonic Ecosystem Engine.

Accepts JSON commands and pushes biome change + status notifications.
External apps (Squeakbot, browser UIs) drive the live ecosystem over this.

Every command may carry an optional "id"; it is echoed back in the response
so callers can correlate requests (RPC style). Responses keep the legacy
shape for backward compat and add "ok"/"result" fields.

Transport commands (client → server):
  {"cmd": "next"}                  — skip to next biome (random seed)
  {"cmd": "next", "seed": 42}      — skip to a specific seed
  {"cmd": "panic"}                 — free all nodes, start fresh biome
  {"cmd": "info"}                  — request current biome info (legacy)

Query commands:
  {"cmd": "get_state"}             — full snapshot: biome + status + medium
  {"cmd": "capabilities"}          — list of commands + param ranges

Live mix commands (medium; rejected during biome transitions):
  {"cmd": "set_reverb", "roomsize":.., "revtime":.., "damping":.., "mix":..}
  {"cmd": "set_noise_floor", "level":.., "color":..}
  {"cmd": "set_resonance", "mix":..}

Live population / activity commands:
  {"cmd": "set_species_target", "species": "name", "n": 8}
  {"cmd": "spawn", "species": "name", "count": 1}
  {"cmd": "cull", "species": "name", "count": 1}
  {"cmd": "set_activity", "value": 3.0}
  {"cmd": "bump_activity", "amount": 1.0}

Notifications (server → clients, broadcast):
  {"event": "biome_change", "seed": 12345, ...}
  {"event": "status", "agents_alive": N, ...}
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

import websockets
from websockets.asyncio.server import serve, ServerConnection

if TYPE_CHECKING:
    from generation.derive import BiomeSpec
    from engine.ecosystem import EcosystemManager

log = logging.getLogger(__name__)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# Param ranges for clamping + advertised via `capabilities`.
# Ranges mirror the synthdef clip ranges in synthdefs/medium.scd.
_MIX_PARAMS = {
    "set_reverb": {"roomsize": (0.1, 300.0), "revtime": (0.1, 100.0),
                   "damping": (0.0, 1.0), "mix": (0.0, 1.0)},
    "set_noise_floor": {"level": (-96.0, -6.0), "color": (0.0, 1.0)},
    "set_resonance": {"mix": (0.0, 1.0)},
}
_SPECIES_TARGET_RANGE = (0, 64)
_COUNT_RANGE = (1, 16)
_ACTIVITY_RANGE = (0.0, 50.0)


class ControlServer:
    """Websocket server for external control (Squeakbot, browser, etc.)."""

    def __init__(self, next_event: asyncio.Event,
                 manager: EcosystemManager | None = None, port: int = 8765):
        self.port = port
        self.next_event = next_event
        self.manager = manager
        self._requested_seed: int | None = None
        self._panic: bool = False
        self._clients: set[ServerConnection] = set()
        self._current_biome: dict | None = None
        self._server = None

        self._handlers = {
            "next": self._cmd_next,
            "panic": self._cmd_panic,
            "info": self._cmd_info,
            "get_state": self._cmd_get_state,
            "capabilities": self._cmd_capabilities,
            "set_reverb": self._cmd_set_mix,
            "set_noise_floor": self._cmd_set_mix,
            "set_resonance": self._cmd_set_mix,
            "set_species_target": self._cmd_set_species_target,
            "spawn": self._cmd_spawn,
            "cull": self._cmd_cull,
            "set_activity": self._cmd_set_activity,
            "bump_activity": self._cmd_bump_activity,
        }

    # -- Properties read by the main loop --------------------------------------

    @property
    def requested_seed(self) -> int | None:
        """Seed requested by the last 'next' command, or None for random."""
        seed = self._requested_seed
        self._requested_seed = None
        return seed

    @property
    def is_panic(self) -> bool:
        """True if the last skip was a panic (free all, no crossfade)."""
        val = self._panic
        self._panic = False
        return val

    # -- Outbound broadcasts ---------------------------------------------------

    def set_current_biome(self, biome: BiomeSpec):
        """Update current biome info and notify all connected clients."""
        self._current_biome = biome.to_dict()
        msg = json.dumps({"event": "biome_change", **self._current_biome})
        asyncio.ensure_future(self._broadcast(msg))

    def push_status(self, status: dict):
        """Push a live status update to all connected clients."""
        if not self._clients:
            return
        msg = json.dumps({"event": "status", **status})
        asyncio.ensure_future(self._broadcast(msg))

    async def _broadcast(self, msg: str):
        for ws in list(self._clients):
            try:
                await ws.send(msg)
            except Exception:
                self._clients.discard(ws)

    # -- Command handlers ------------------------------------------------------
    #
    # Each returns the response dict. Raise ValueError for client-facing errors.

    def _require_ecosystem(self):
        if self.manager is None or self.manager.current is None:
            raise ValueError("no active biome")
        return self.manager.current

    def _require_idle(self):
        if self.manager is not None and self.manager.transitioning:
            raise ValueError("biome transitioning — try again shortly")

    def _cmd_next(self, data):
        self._requested_seed = data.get("seed")  # None = random
        self.next_event.set()
        log.info("Next biome requested (seed=%s)", self._requested_seed)
        return {"ok": True, "cmd": "next"}

    def _cmd_panic(self, data):
        self._requested_seed = data.get("seed")  # None = random
        self._panic = True
        self.next_event.set()
        log.info("PANIC — free all, fresh start (seed=%s)", self._requested_seed)
        return {"ok": True, "cmd": "panic"}

    def _cmd_info(self, data):
        # Legacy response shape — kept for existing browser UIs.
        return {"event": "info", **(self._current_biome or {})}

    def _cmd_get_state(self, data):
        result = {"biome": self._current_biome}
        eco = self.manager.current if self.manager else None
        if eco is not None:
            result["status"] = eco.get_status()
            result["medium"] = eco.medium_values()
            result["transitioning"] = self.manager.transitioning
        return {"ok": True, "cmd": "get_state", "result": result}

    def _cmd_capabilities(self, data):
        return {"ok": True, "cmd": "capabilities", "result": _CAPABILITIES}

    def _cmd_set_mix(self, data):
        cmd = data["cmd"]
        eco = self._require_ecosystem()
        self._require_idle()
        spec = _MIX_PARAMS[cmd]
        params = {}
        for key, (lo, hi) in spec.items():
            if data.get(key) is not None:
                params[key] = _clamp(float(data[key]), lo, hi)
        if not params:
            raise ValueError(f"{cmd}: no params given")
        if cmd == "set_reverb":
            eco.medium.set_reverb(**params)
        elif cmd == "set_noise_floor":
            eco.medium.set_noise_floor(**params)
        elif cmd == "set_resonance":
            eco.medium.set_resonance(**params)
        return {"ok": True, "cmd": cmd, "result": params}

    def _req_species(self, data) -> str:
        species = data.get("species")
        if not species:
            raise ValueError("missing 'species'")
        return species

    def _cmd_set_species_target(self, data):
        eco = self._require_ecosystem()
        species = self._req_species(data)
        if data.get("n") is None:
            raise ValueError("missing 'n'")
        applied = eco.set_species_target(species, int(data["n"]))
        return {"ok": True, "cmd": "set_species_target",
                "result": {"species": species, "n": applied}}

    def _cmd_spawn(self, data):
        eco = self._require_ecosystem()
        species = self._req_species(data)
        count = int(_clamp(int(data.get("count", 1)), *_COUNT_RANGE))
        spawned = eco.spawn(species, count)
        return {"ok": True, "cmd": "spawn",
                "result": {"species": species, "spawned": spawned}}

    def _cmd_cull(self, data):
        eco = self._require_ecosystem()
        species = self._req_species(data)
        count = max(1, int(data.get("count", 1)))
        culled = eco.cull(species, count)
        return {"ok": True, "cmd": "cull",
                "result": {"species": species, "culled": culled}}

    def _cmd_set_activity(self, data):
        eco = self._require_ecosystem()
        if data.get("value") is None:
            raise ValueError("missing 'value'")
        applied = eco.set_activity(float(data["value"]))
        return {"ok": True, "cmd": "set_activity", "result": {"activity": applied}}

    def _cmd_bump_activity(self, data):
        eco = self._require_ecosystem()
        applied = eco.bump_activity(float(data.get("amount", 1.0)))
        return {"ok": True, "cmd": "bump_activity", "result": {"activity": applied}}

    # -- Connection handling ---------------------------------------------------

    async def _send(self, ws, payload: dict):
        await ws.send(json.dumps(payload))

    async def _handler(self, ws: ServerConnection):
        self._clients.add(ws)
        remote = ws.remote_address
        log.info("Control client connected: %s", remote)
        try:
            async for raw in ws:
                try:
                    data = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    await self._send(ws, {"ok": False, "error": "invalid JSON"})
                    continue

                cmd = data.get("cmd", "")
                req_id = data.get("id")
                handler = self._handlers.get(cmd)
                if handler is None:
                    await self._send(ws, {"ok": False, "cmd": cmd, "id": req_id,
                                          "error": f"unknown cmd: {cmd}"})
                    continue
                try:
                    resp = handler(data)
                except ValueError as e:
                    await self._send(ws, {"ok": False, "cmd": cmd, "id": req_id,
                                          "error": str(e)})
                    continue
                except Exception as e:  # noqa: BLE001 — report, don't drop connection
                    log.exception("cmd %s failed", cmd)
                    await self._send(ws, {"ok": False, "cmd": cmd, "id": req_id,
                                          "error": f"internal error: {e}"})
                    continue

                if req_id is not None:
                    resp["id"] = req_id
                await self._send(ws, resp)

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


# Advertised to clients via the `capabilities` command.
_CAPABILITIES = {
    "version": 1,
    "commands": {
        "next": {"params": {"seed": "int?"}},
        "panic": {"params": {"seed": "int?"}},
        "info": {"params": {}},
        "get_state": {"params": {}},
        "capabilities": {"params": {}},
        "set_reverb": {"params": _MIX_PARAMS["set_reverb"],
                       "note": "rejected during transition"},
        "set_noise_floor": {"params": _MIX_PARAMS["set_noise_floor"],
                            "note": "rejected during transition"},
        "set_resonance": {"params": _MIX_PARAMS["set_resonance"],
                          "note": "rejected during transition"},
        "set_species_target": {"params": {"species": "str", "n": _SPECIES_TARGET_RANGE}},
        "spawn": {"params": {"species": "str", "count": _COUNT_RANGE}},
        "cull": {"params": {"species": "str", "count": "int>=1"}},
        "set_activity": {"params": {"value": _ACTIVITY_RANGE}},
        "bump_activity": {"params": {"amount": "float"}},
    },
}
