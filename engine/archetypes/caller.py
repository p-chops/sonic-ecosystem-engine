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

        # Build song from species template — shared melody, per-agent amplitude.
        song_template = self.params.get("song_template", [])
        pitches = agent.pitches  # sorted ascending

        # Source separation: confine this caller to its OWN register band, fixed
        # at spawn, so one caller reads as a single voice (no register hopping)
        # and multiple callers of a species spread across distinct registers.
        # Band ~1/3 of the species range; random start scatters callers.
        window = max(3, len(pitches) // 3)
        start = rng.randint(0, max(0, len(pitches) - window))
        my_pitches = pitches[start:start + window]

        # Depth reduces song complexity — deep agents sing a truncated version
        song_length = self.params.get("song_length", len(song_template))
        effective_length = max(2, int(song_length * lerp(1.0, 0.4, agent.depth)))

        self.song = []
        for note in song_template[:effective_length]:
            self.song.append({
                "freq": my_pitches[note["pitch_index"] % len(my_pitches)],
                "amp": agent.amp * note["amp_scale"],
                "decay": note["decay"],
                "gap": note["gap"],
            })

    async def run(self):
        rng = self.agent.rng

        while self.agent.alive:
            # Sing the song in this caller's fixed register (no transposition —
            # each caller stays put so it reads as a single source).
            self.agent.voice.vocalize_song(self.song)
            self.agent.contribute_activity(len(self.song) * 0.3)

            # Wait for song to finish
            song_dur = sum(n["decay"] + n["gap"] for n in self.song)
            await self.wait(song_dur)

            # Rest with flocking
            pause = rng.uniform(*self.base_pause)
            pause *= self.get_flocking_factor()
            await self.wait(pause)
