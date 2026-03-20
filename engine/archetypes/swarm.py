"""Swarm — many near-identical micro-events at high density.

Functionally a clicker with very short wait times, tuned for collective
texture rather than individual events. Density-coupled: thickens when
activity is high, thins when low.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from engine.archetypes.base import Behavior, lerp

if TYPE_CHECKING:
    from engine.agent import Agent
    from engine.species import Species


class SwarmBehavior(Behavior):

    def __init__(self, agent: Agent, species: Species):
        super().__init__(agent, species)
        rng = agent.rng

        self.density = self.params.get("density", rng.uniform(5, 30))  # events/sec
        self.pitch_scatter = self.params.get("pitch_scatter", 0.05)  # ratio
        self.amp_scatter = self.params.get("amp_scatter", 0.3)

    async def run(self):
        rng = self.agent.rng
        pitches = self.agent.pitches
        base_interval = 1.0 / max(self.density, 0.1)

        while self.agent.alive:
            # Density coupling: speed up when activity is high
            activity = self.agent.ecosystem_state.activity
            coupling = lerp(0.6, 1.5, min(activity / 5.0, 1.0))
            interval = base_interval / max(coupling, 0.1)

            # Scattered pitch
            freq = rng.choice(pitches) * (1 + rng.uniform(-self.pitch_scatter, self.pitch_scatter))

            # Scattered amplitude
            amp = self.agent.amp * rng.uniform(1 - self.amp_scatter, 1)

            self.agent.voice.vocalize(
                freq=freq,
                amp=amp,
                decay=rng.uniform(0.01, 0.08),
            )

            # Tiny activity contribution per event
            self.agent.contribute_activity(0.05)

            await self.wait(interval)
