"""Base class for archetype behaviors."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.agent import Agent
    from engine.species import Species


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


class Behavior(ABC):
    """Abstract base for archetype behaviors."""

    def __init__(self, agent: Agent, species: Species):
        self.agent = agent
        self.species = species
        self.params = species.params

    @abstractmethod
    async def run(self):
        """Main behavior loop. Runs until agent dies or is cancelled."""
        ...

    async def wait(self, seconds: float):
        """Sleep, but bail out early if the agent dies."""
        if not self.agent.alive or seconds <= 0:
            return
        await asyncio.sleep(seconds)
        if not self.agent.alive:
            raise asyncio.CancelledError

    def get_flocking_factor(self) -> float:
        """Returns a multiplier for rest pauses based on shared activity.

        activity low  → factor ~1.0 (normal rest)
        activity mid  → factor <1.0 (compressed rest, more active)
        activity high → factor >1.0 (fatigue, longer rest)
        """
        activity = self.agent.ecosystem_state.activity
        fatigue_threshold = self.params.get("fatigue_threshold", 5.0)

        if activity > fatigue_threshold:
            # Fatigue: stretch pauses
            return lerp(1.0, 2.5, min((activity - fatigue_threshold) / fatigue_threshold, 1.0))
        else:
            # Flocking: compress pauses when others are active
            return lerp(1.0, 0.3, activity / max(fatigue_threshold, 0.01))
