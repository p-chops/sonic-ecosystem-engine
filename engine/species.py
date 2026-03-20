"""Species — the template from which agents are spawned."""

from __future__ import annotations

import math
import random as stdlib_random
from dataclasses import dataclass, field
from typing import Callable

from engine.voice_chain import ChainSpec


@dataclass
class Species:
    """A species definition. All agents of a species share the same voice
    chain topology and archetype, but vary in depth, pan, and per-agent
    randomization."""

    name: str
    archetype: str  # "caller", "clicker", "drone", "swarm", "responder"
    chain_spec: ChainSpec
    freq_range: tuple[float, float]  # (lo_hz, hi_hz)
    pitch_set: list[float]           # available frequencies in Hz
    population: int
    age_range: tuple[int, int]       # (min_ticks, max_ticks) lifespan
    depth_dist: str = "sqrt"         # "sqrt", "uniform", "close"

    # Archetype-specific params (dict so archetypes can pull what they need)
    params: dict = field(default_factory=dict)

    def draw_depth(self, rng: stdlib_random.Random) -> float:
        """Draw a depth value (0=close, 1=far) from the species distribution."""
        if self.depth_dist == "sqrt":
            return math.sqrt(rng.random())  # skews most agents far
        elif self.depth_dist == "close":
            return rng.random() ** 2  # skews most agents close
        else:  # uniform
            return rng.random()

    def pitches_in_range(self) -> list[float]:
        """Return pitch set frequencies mapped into this species' frequency range
        via octave transposition."""
        lo, hi = self.freq_range
        result = []
        for f in self.pitch_set:
            # Transpose into range by octave shifts
            freq = f
            while freq < lo and freq > 0:
                freq *= 2
            while freq > hi:
                freq /= 2
            if lo <= freq <= hi:
                result.append(freq)
        # Deduplicate and sort
        return sorted(set(result))
