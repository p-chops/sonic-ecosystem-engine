"""Drone — sustains continuously with slow spectral drift.

Does not use the standard percussive envelope. Instead spawns a persistent
source synth that evolves over time via parameter updates. Optionally
recedes when callers are active (inverse coupling).

Fades in on spawn and fades out on death to avoid hard cuts during
biome transitions.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from engine.archetypes.base import Behavior, lerp
from engine.bridge import ADD_TO_HEAD

if TYPE_CHECKING:
    from engine.agent import Agent
    from engine.species import Species


class DroneBehavior(Behavior):

    def __init__(self, agent: Agent, species: Species):
        super().__init__(agent, species)
        rng = agent.rng

        self.drift_rate = self.params.get("drift_rate", (2.0, 6.0))  # seconds between drifts
        self.drift_range = self.params.get("drift_range", 0.1)  # max freq drift as ratio
        self.brightness_range = self.params.get("brightness_range", (0.3, 0.8))
        self.inverse_coupling = self.params.get("inverse_coupling", True)
        self.fade_time = self.params.get("fade_time", 4.0)  # seconds for fade in/out

        # Pick a base frequency
        self.base_freq = rng.choice(agent.pitches)
        self.current_freq = self.base_freq
        self.target_amp = agent.amp
        self.current_amp = 0.0  # start silent

        # Drone source node (will be created in run)
        self.drone_node = None

    async def run(self):
        rng = self.agent.rng

        # Spawn silent, then fade in
        self.drone_node = self.agent.voice.vocalize(
            freq=self.base_freq,
            amp=0.0,
            decay=self.agent.max_age * 10,  # effectively infinite
        )

        await self._fade_in()

        while self.agent.alive and self.agent.age < self.agent.max_age - 2:
            drift_interval = rng.uniform(*self.drift_rate)
            await self.wait(drift_interval)

            if not self.agent.alive:
                break

            # Drift frequency
            drift = 1.0 + rng.uniform(-self.drift_range, self.drift_range)
            self.current_freq = self.base_freq * drift
            self.agent.sc.set(self.drone_node, freq=self.current_freq)

            # Inverse coupling: duck amplitude when activity is high
            if self.inverse_coupling:
                activity = self.agent.ecosystem_state.activity
                duck = lerp(1.0, 0.2, min(activity / 5.0, 1.0))
                self.current_amp = self.target_amp * duck
                self.agent.sc.set(self.drone_node, amp=self.current_amp)

            # Minimal activity contribution
            self.agent.contribute_activity(0.05)

        # Natural end-of-life: fade out before the agent loop exits
        if self.agent.alive:
            await self.fade_out()

    async def _fade_in(self):
        steps = 20
        step_dur = self.fade_time / steps
        for i in range(1, steps + 1):
            if not self.agent.alive:
                return
            t = i / steps
            self.current_amp = self.target_amp * t
            if self.drone_node and not self.agent.voice._torn_down:
                self.agent.sc.set(self.drone_node, amp=self.current_amp)
            await asyncio.sleep(step_dur)

    async def fade_out(self):
        """Gradually fade the drone to silence. Called before teardown."""
        if self.drone_node is None or self.agent.voice._torn_down:
            return
        steps = 20
        step_dur = self.fade_time / steps
        start_amp = self.current_amp
        for i in range(1, steps + 1):
            t = i / steps
            amp = start_amp * (1 - t)
            try:
                self.agent.sc.set(self.drone_node, amp=amp)
            except Exception:
                return
            await asyncio.sleep(step_dur)
