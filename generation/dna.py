"""Macro DNA — the five high-level dimensions that define a biome's character."""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class MacroDNA:
    """Five dimensions, each 0.0–1.0, drawn from a seed RNG."""
    density: float          # sparse ↔ saturated
    spectral_center: float  # dark ↔ bright
    temporal: float         # static/drones ↔ rhythmic/transients
    sociality: float        # independent ↔ interactive/flocking
    room_scale: float       # intimate/dry ↔ vast/wet

    def summary(self) -> str:
        return (
            f"density={self.density:.2f}  spectral={self.spectral_center:.2f}  "
            f"temporal={self.temporal:.2f}  sociality={self.sociality:.2f}  "
            f"room={self.room_scale:.2f}"
        )


def draw_dna(rng: random.Random) -> MacroDNA:
    """Draw a MacroDNA from the given RNG."""
    return MacroDNA(
        density=rng.random(),
        spectral_center=rng.random(),
        temporal=rng.random(),
        sociality=rng.random(),
        room_scale=rng.random(),
    )
