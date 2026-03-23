"""Caller — sings structured phrases with rest periods.

All agents of a species share the same song (melody + timing), derived at
species generation time. Each agent maps the shared template to its own
pitch set and amplitude. Repeats with occasional transposition. Rest
duration is subject to flocking dynamics.
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
        self.base_pause = self.params.get("base_pause", (1.0, 5.0))
        self.glide_prob = self.params.get("glide_prob", 0.2)
        self.transpose_prob = self.params.get("transpose_prob", 0.15)

        # Build song from species template — shared melody, per-agent amplitude
        song_template = self.params.get("song_template", [])
        pitches = agent.pitches

        # Depth reduces song complexity — deep agents sing a truncated version
        song_length = self.params.get("song_length", len(song_template))
        effective_length = max(2, int(song_length * lerp(1.0, 0.4, agent.depth)))

        self.song = []
        for note in song_template[:effective_length]:
            self.song.append({
                "freq": pitches[note["pitch_index"] % len(pitches)],
                "amp": agent.amp * note["amp_scale"],
                "decay": note["decay"],
                "gap": note["gap"],
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
