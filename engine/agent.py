"""Agent — a single sound-producing entity in the ecosystem."""

from __future__ import annotations

import asyncio
import logging
import random as stdlib_random
from typing import TYPE_CHECKING

from engine.voice_chain import VoiceChain, ChainSpec

if TYPE_CHECKING:
    from engine.bridge import SCBridge
    from engine.species import Species

log = logging.getLogger(__name__)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


class Agent:
    """A single agent in the ecosystem. Owns a voice chain and delegates
    behavior to its archetype."""

    def __init__(
        self,
        species: Species,
        sc: SCBridge,
        medium_bus: int,
        ecosystem_state,
        rng: stdlib_random.Random,
        parent_group: int = 1,
    ):
        self.species = species
        self.sc = sc
        self.alive = True
        self.age = 0
        self.max_age = rng.randint(*species.age_range)
        self.rng = rng

        # Depth model
        self.depth = species.draw_depth(rng)
        self.pos = rng.uniform(-1.0, 1.0)  # pan position

        # Depth-derived parameters
        self.amp = lerp(0.4, 0.05, self.depth)
        if species.archetype == "drone":
            self.amp *= 0.3  # drones sit underneath
        self.send = lerp(0.1, 0.8, self.depth)
        self.activity_weight = lerp(1.0, 0.0, self.depth)

        # Build voice chain with depth-adjusted params
        spec = ChainSpec(
            source=species.chain_spec.source,
            effects=list(species.chain_spec.effects),
            pan=self.pos,
            amp=self.amp,
            send=self.send,
            send_bus=medium_bus,
        )

        # Apply depth-based LPF darkening: close=full brightness, far=dark
        lpf_cutoff = lerp(12000, 800, self.depth ** 0.7)
        has_lpf = any(name == "fx_lpf" for name, _ in spec.effects)
        if has_lpf:
            # Adjust existing LPF — take the minimum of species cutoff and depth cutoff
            spec.effects = [
                (name, {**params, "cutoff": min(params.get("cutoff", 20000), lpf_cutoff)})
                if name == "fx_lpf" else (name, params)
                for name, params in spec.effects
            ]
        else:
            # Prepend an LPF for depth darkening
            spec.effects.insert(0, ("fx_lpf", {"cutoff": lpf_cutoff, "res": 0.0}))

        self.voice = VoiceChain(spec, sc, medium_bus, parent_group=parent_group)

        # Available pitches for this agent
        self.pitches = species.pitches_in_range()
        if not self.pitches:
            # Fallback: use freq_range midpoint
            mid = (species.freq_range[0] + species.freq_range[1]) / 2
            self.pitches = [mid]

        # Ecosystem state reference (for activity/flocking)
        self.ecosystem_state = ecosystem_state

        # Archetype behavior (set by create_behavior)
        self.behavior = None

    async def run(self):
        """Main loop — delegates to archetype behavior."""
        if self.behavior is None:
            log.warning("Agent has no behavior assigned, dying immediately")
            self.die()
            return
        try:
            await self.behavior.run()
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("Agent behavior crashed")
        finally:
            if self.alive:
                self.die()

    def contribute_activity(self, amount: float = 1.0):
        """Add to the shared activity metric, weighted by depth."""
        self.ecosystem_state.activity += amount * self.activity_weight

    def die(self):
        self.alive = False
        # Drone fade-out is handled async before teardown — see graceful_die()
        self.voice.teardown()

    async def graceful_die(self):
        """Async death — gives behaviors a chance to fade out before teardown."""
        self.alive = False
        from engine.archetypes.drone import DroneBehavior
        if isinstance(self.behavior, DroneBehavior):
            await self.behavior.fade_out()
        self.voice.teardown()
