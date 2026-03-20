"""Caller — sings structured phrases with rest periods.

Generates a fixed "song" at birth (a note sequence), repeats it with
occasional transposition. Rest duration is subject to flocking dynamics.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from engine.archetypes.base import Behavior, lerp

if TYPE_CHECKING:
    from engine.agent import Agent
    from engine.species import Species


class CallerBehavior(Behavior):

    def __init__(self, agent: Agent, species: Species):
        super().__init__(agent, species)
        rng = agent.rng

        # Parameters with defaults
        song_length = self.params.get("song_length", rng.randint(3, 8))
        note_dur_range = self.params.get("note_dur_range", (0.1, 0.6))
        note_gap = self.params.get("note_gap", (0.02, 0.15))
        self.base_pause = self.params.get("base_pause", (1.0, 5.0))
        self.glide_prob = self.params.get("glide_prob", 0.2)
        self.transpose_prob = self.params.get("transpose_prob", 0.15)

        # Depth reduces song complexity
        effective_length = max(2, int(song_length * lerp(1.0, 0.4, agent.depth)))

        # Generate the song
        pitches = agent.pitches
        self.song = []
        for _ in range(effective_length):
            self.song.append({
                "freq": rng.choice(pitches),
                "amp": agent.amp * rng.uniform(0.7, 1.0),
                "decay": rng.uniform(*note_dur_range),
                "gap": rng.uniform(*note_gap),
            })

    async def run(self):
        rng = self.agent.rng

        while self.agent.alive:
            # Occasionally transpose the song
            transpose = 1.0
            if rng.random() < self.transpose_prob:
                transpose = rng.choice([0.5, 0.75, 1.0, 1.5, 2.0])

            # Sing the song as a bundle
            transposed = []
            for note in self.song:
                transposed.append({
                    **note,
                    "freq": note["freq"] * transpose,
                    "amp": note["amp"],
                })
            self.agent.voice.vocalize_song(transposed)
            self.agent.contribute_activity(len(self.song) * 0.3)

            # Wait for song to finish
            song_dur = sum(n["decay"] + n["gap"] for n in self.song)
            await self.wait(song_dur)

            # Rest with flocking
            pause = rng.uniform(*self.base_pause)
            pause *= self.get_flocking_factor()
            await self.wait(pause)
