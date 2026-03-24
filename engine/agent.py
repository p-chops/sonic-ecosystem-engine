"""Agent — a single sound-producing entity in the ecosystem."""

from __future__ import annotations

import asyncio
import logging
import math
import random as stdlib_random
from typing import TYPE_CHECKING

from engine.voice_chain import VoiceChain, ChainSpec

if TYPE_CHECKING:
    from engine.bridge import SCBridge
    from engine.species import Species

log = logging.getLogger(__name__)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


# Source-specific gain compensation. Values <1.0 for inherently loud sources,
# >1.0 for quiet ones. Tuned by ear.
_SOURCE_GAIN = {
    "src_sine":    1.2,   # focused energy, needs a boost
    "src_noise":   0.5,   # broadband, inherently loud
    "src_click":   0.8,   # spiky transients
    "src_fm":      1.0,   # reference level
    "src_formant": 0.7,   # multiple resonant bands add up
    "src_grain":   0.6,   # many overlapping grains
    "src_string":  1.0,   # similar energy to FM
}


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
        self.has_voiced = False  # True after first vocalization
        self.age = 0
        self.max_age = rng.randint(*species.age_range)
        self.rng = rng

        # Depth model
        self.depth = species.draw_depth(rng)
        self.pos = rng.uniform(-1.0, 1.0)  # pan position

        # Depth-derived parameters
        #
        # Amplitude model:
        #   Close agents are clearly audible, far agents are quiet texture.
        #   Source gain compensates for inherent loudness differences.
        #   The medium limiter normalizes total biome energy.
        #
        source_gain = _SOURCE_GAIN.get(species.chain_spec.source, 1.0)

        base_amp = lerp(0.5, 0.12, self.depth)  # ~12dB foreground/background spread
        self.amp = base_amp * source_gain

        if species.archetype == "drone":
            self.amp *= 0.7  # drones sit underneath but stay present

        # Size-based amplitude for callers: small/high creatures are quieter
        size = species.params.get("size")
        if size is not None:
            self.amp *= lerp(0.6, 1.0, size)  # small=0.6x, large=1.0x

        self.send = lerp(0.1, 0.8, self.depth)
        if species.archetype == "drone":
            self.send = lerp(0.5, 0.9, self.depth)  # drones live in the reverb
        self.activity_weight = lerp(1.0, 0.0, self.depth)

        # Build voice chain with depth-adjusted params
        spec = ChainSpec(
            source=species.chain_spec.source,
            effects=list(species.chain_spec.effects),
            source_params=dict(species.chain_spec.source_params),
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
        if len(self.pitches) < 3:
            # Range too narrow — fill in by subdividing the range
            lo, hi = species.freq_range
            n_fill = max(5, len(species.pitch_set))
            log_lo, log_hi = math.log2(max(lo, 20)), math.log2(max(hi, 21))
            self.pitches = [2 ** lerp(log_lo, log_hi, i / (n_fill - 1))
                            for i in range(n_fill)]

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
        self.has_voiced = True
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
