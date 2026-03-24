"""Clicker — emits single impulses at stochastic intervals.

Independent, no social behavior. Each agent has its own tempo drawn at birth.
Polymetric texture emerges from divergent clocks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from engine.archetypes.base import Behavior

if TYPE_CHECKING:
    from engine.agent import Agent
    from engine.species import Species


class ClickerBehavior(Behavior):

    def __init__(self, agent: Agent, species: Species):
        super().__init__(agent, species)
        rng = agent.rng

        self.wait_range = self.params.get("wait_range", (0.3, 3.0))
        self.rest_prob = self.params.get("rest_prob", 0.2)
        self.chord_prob = self.params.get("chord_prob", 0.1)
        self.chord_size = self.params.get("chord_size", (2, 4))

    async def run(self):
        rng = self.agent.rng
        pitches = rng.choices(self.agent.pitches, k=2)

        while self.agent.alive:
            # Occasionally rest (skip a cycle)
            if rng.random() < self.rest_prob:
                await self.wait(rng.uniform(*self.wait_range))
                continue

            # Occasionally fire a chord (multiple simultaneous notes)
            if rng.random() < self.chord_prob and len(pitches) >= 2:
                n = rng.randint(*self.chord_size)
                n = min(n, len(pitches))
                for freq in rng.sample(pitches, n):
                    self.agent.voice.vocalize(
                        freq=freq,
                        amp=self.agent.amp * rng.uniform(0.6, 1.0),
                        decay=rng.uniform(0.05, 0.3),
                    )
                self.agent.contribute_activity(n * 0.2)
            else:
                # Single click
                freq = rng.choice(pitches)
                self.agent.voice.vocalize(
                    freq=freq,
                    amp=self.agent.amp * rng.uniform(0.7, 1.0),
                    decay=rng.uniform(0.05, 0.4),
                )
                self.agent.contribute_activity(0.2)

            await self.wait(rng.uniform(*self.wait_range))
