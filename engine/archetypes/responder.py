"""Responder — only vocalizes in response to detected activity.

Waits silently, monitoring the shared activity level. Fires when it
crosses a threshold. Like a predator call after commotion, or an
echo/reply behavior.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from engine.archetypes.base import Behavior

if TYPE_CHECKING:
    from engine.agent import Agent
    from engine.species import Species


class ResponderBehavior(Behavior):

    def __init__(self, agent: Agent, species: Species):
        super().__init__(agent, species)
        rng = agent.rng

        self.trigger_threshold = self.params.get("trigger_threshold", 2.0)
        self.response_delay = self.params.get("response_delay", (0.2, 1.0))
        self.cooldown = self.params.get("cooldown", (3.0, 8.0))
        song_length = self.params.get("response_song_length", rng.randint(2, 5))

        # Generate a response phrase
        pitches = agent.pitches
        self.response_song = []
        for _ in range(song_length):
            self.response_song.append({
                "freq": rng.choice(pitches),
                "amp": agent.amp * rng.uniform(0.6, 1.0),
                "decay": rng.uniform(0.1, 0.4),
                "gap": rng.uniform(0.03, 0.12),
            })

    async def run(self):
        rng = self.agent.rng

        while self.agent.alive:
            # Poll activity — short interval
            await self.wait(0.2)

            activity = self.agent.ecosystem_state.activity
            if activity < self.trigger_threshold:
                continue

            # Triggered — wait a beat then respond
            await self.wait(rng.uniform(*self.response_delay))

            if not self.agent.alive:
                break

            # Fire the response (does NOT contribute to activity — reactive only)
            self.agent.voice.vocalize_song(self.response_song)

            # Wait for song to finish + cooldown
            song_dur = sum(n["decay"] + n["gap"] for n in self.response_song)
            await self.wait(song_dur + rng.uniform(*self.cooldown))
