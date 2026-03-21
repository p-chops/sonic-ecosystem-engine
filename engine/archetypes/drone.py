"""Drone — sustains continuously with slow spectral drift.

Does not use the standard percussive envelope. Instead spawns a persistent
source synth that evolves over time via parameter updates. Modulates
pan, filter, and reverb send slowly over time for spatial movement.
Optionally recedes when callers are active (inverse coupling).

Fades in on spawn and fades out on death to avoid hard cuts during
biome transitions.
"""

from __future__ import annotations

import asyncio
import math
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

        self.drift_rate = self.params.get("drift_rate", (2.0, 6.0))
        self.drift_range = self.params.get("drift_range", 0.1)
        self.inverse_coupling = self.params.get("inverse_coupling", True)
        self.fade_time = self.params.get("fade_time", 4.0)

        # Pan wander
        self.pan_drift_rate = self.params.get("pan_drift_rate", 0.05)
        self.pan_drift_range = self.params.get("pan_drift_range", 0.6)
        self.pan_center = agent.pos  # starting pan position

        # Send wander (breathe in/out of reverb)
        self.send_drift_rate = self.params.get("send_drift_rate", 0.03)
        self.send_lo = self.params.get("send_lo", 0.3)
        self.send_hi = self.params.get("send_hi", 0.8)

        # Filter sweep
        self.filter_drift_rate = self.params.get("filter_drift_rate", 0.05)
        self.filter_lo = self.params.get("filter_lo", 500)
        self.filter_hi = self.params.get("filter_hi", 4000)

        # Pick a base frequency
        self.base_freq = rng.choice(agent.pitches)
        self.current_freq = self.base_freq
        self.target_amp = agent.amp
        self.current_amp = 0.0

        # Random phase offsets so drones don't move in sync
        self.pan_phase = rng.uniform(0, 2 * math.pi)
        self.send_phase = rng.uniform(0, 2 * math.pi)
        self.filter_phase = rng.uniform(0, 2 * math.pi)

        self.drone_node = None
        self._elapsed = 0.0

    async def run(self):
        rng = self.agent.rng

        # Spawn near-silent, then fade in.
        # amp must be > 0 to prevent DetectSilence from immediately freeing the node.
        self.drone_node = self.agent.voice.vocalize(
            freq=self.base_freq,
            amp=0.0001,
            decay=self.agent.max_age * 10,
        )

        await self._fade_in()

        while self.agent.alive and self.agent.age < self.agent.max_age - 2:
            drift_interval = rng.uniform(*self.drift_rate)
            await self.wait(drift_interval)
            self._elapsed += drift_interval

            if not self.agent.alive:
                break

            # Frequency drift
            drift = 1.0 + rng.uniform(-self.drift_range, self.drift_range)
            self.current_freq = self.base_freq * drift
            if not self.agent.voice._torn_down:
                self.agent.sc.set(self.drone_node, freq=self.current_freq)

            # Pan wander (sinusoidal)
            pan_lfo = math.sin(self._elapsed * self.pan_drift_rate * 2 * math.pi + self.pan_phase)
            new_pan = max(-1, min(1, self.pan_center + pan_lfo * self.pan_drift_range))
            self.agent.voice.set_pan(new_pan)

            # Send wander (breathe in/out of reverb)
            send_lfo = math.sin(self._elapsed * self.send_drift_rate * 2 * math.pi + self.send_phase)
            new_send = lerp(self.send_lo, self.send_hi, (send_lfo + 1) / 2)
            self.agent.voice.set_send(new_send)

            # Filter sweep (modulate the depth LPF)
            filter_lfo = math.sin(self._elapsed * self.filter_drift_rate * 2 * math.pi + self.filter_phase)
            new_cutoff = lerp(self.filter_lo, self.filter_hi, (filter_lfo + 1) / 2)
            self.agent.voice.set_effect_param(0, cutoff=new_cutoff)

            # Inverse coupling: duck amplitude when activity is high
            if self.inverse_coupling:
                activity = self.agent.ecosystem_state.activity
                duck = lerp(1.0, 0.2, min(activity / 5.0, 1.0))
                self.current_amp = self.target_amp * duck
            else:
                self.current_amp = self.target_amp

            if not self.agent.voice._torn_down:
                self.agent.sc.set(self.drone_node, amp=self.current_amp)

            self.agent.contribute_activity(0.05)

        # Natural end-of-life: fade out
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
