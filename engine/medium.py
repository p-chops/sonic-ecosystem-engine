"""Medium — shared acoustic environment (reverb, resonance, EQ, noise floor, limiter).

All agents send a portion of their output to the medium bus. The medium
processes the combined signal and outputs to the main stereo bus.

Signal flow:
  medium_bus (mono) → resonance → eq → reverb (→ stereo) → limiter → main out
  noise_floor writes directly to main out (independent of input)
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from engine.bridge import ADD_TO_TAIL

if TYPE_CHECKING:
    from engine.bridge import SCBridge
    from generation.derive import MediumSpec

log = logging.getLogger(__name__)

SILENCE_DB = -96.0


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


class Medium:
    """Runtime shared acoustic environment."""

    def __init__(self, spec: MediumSpec, sc: SCBridge, start_silent: bool = False):
        self.sc = sc
        self.spec = spec

        # Allocate the medium input bus (mono — agents send here)
        self.bus = sc.alloc_bus()

        # Internal buses for chaining
        self._bus_after_reson = sc.alloc_bus()
        self._bus_after_eq = sc.alloc_bus()
        self._bus_after_reverb = sc.alloc_bus(channels=2)  # reverb outputs stereo
        self._buses = [
            self.bus, self._bus_after_reson, self._bus_after_eq, self._bus_after_reverb
        ]

        # Medium group — runs after all agent groups
        self.group = sc.new_group()
        self.nodes: list[int] = []

        # Build the chain
        self._build(spec, start_silent)

    def _build(self, spec: MediumSpec, start_silent: bool):
        sc = self.sc

        # Noise floor level: start silent if requested, ramp up later
        noise_level = SILENCE_DB if start_silent else spec.noise_floor_level
        # Reverb mix: almost full wet — dry signal is already on bus 0 from agents
        self._target_reverb_mix = 0.85
        reverb_mix = 0.0 if start_silent else self._target_reverb_mix
        # Resonance mix: enough to color the sound
        self._target_reson_mix = 0.6

        # 1. Resonance filter bank
        reson_mix = 0.0 if start_silent else self._target_reson_mix
        reson_params = {"in": self.bus, "out": self._bus_after_reson, "mix": reson_mix}
        for i, r in enumerate(spec.resonances[:6]):
            reson_params[f"f{i+1}"] = r.freq
            reson_params[f"q{i+1}"] = r.q
            reson_params[f"a{i+1}"] = r.amp
        # Zero out unused slots
        for i in range(len(spec.resonances), 6):
            reson_params[f"a{i+1}"] = 0.0
        node = sc.synth("med_resonance", target_group=self.group,
                        add_action=ADD_TO_TAIL, **reson_params)
        self.nodes.append(node)
        self._reson_node = node

        # 2. EQ
        node = sc.synth("med_eq", target_group=self.group,
                        add_action=ADD_TO_TAIL,
                        **{"in": self._bus_after_reson, "out": self._bus_after_eq})
        self.nodes.append(node)
        self._eq_node = node

        # 3. Reverb (mono in → stereo out to main bus 0)
        node = sc.synth("med_reverb", target_group=self.group,
                        add_action=ADD_TO_TAIL,
                        **{"in": self._bus_after_eq, "out": 0},
                        time=spec.reverb_time,
                        damping=spec.reverb_damping,
                        mix=reverb_mix)
        self.nodes.append(node)
        self._reverb_node = node

        # 4. Noise floor (independent — writes directly to main out)
        node = sc.synth("med_noise_floor", target_group=self.group,
                        add_action=ADD_TO_TAIL,
                        out=0,
                        level=noise_level,
                        color=spec.noise_floor_color)
        self.nodes.append(node)
        self._noise_node = node

        # 5. Limiter (reads/writes stereo main bus)
        node = sc.synth("med_limiter", target_group=self.group,
                        add_action=ADD_TO_TAIL,
                        **{"in": 0, "out": 0},
                        threshold=spec.limiter_threshold,
                        ratio=4,
                        makeup=6)
        self.nodes.append(node)
        self._limiter_node = node

    # -- Instant setters -------------------------------------------------------

    def set_reverb(self, time: float | None = None, damping: float | None = None,
                   mix: float | None = None):
        params = {}
        if time is not None:
            params["time"] = time
        if damping is not None:
            params["damping"] = damping
        if mix is not None:
            params["mix"] = mix
        if params:
            self.sc.set(self._reverb_node, **params)

    def set_noise_floor(self, level: float | None = None, color: float | None = None):
        params = {}
        if level is not None:
            params["level"] = level
        if color is not None:
            params["color"] = color
        if params:
            self.sc.set(self._noise_node, **params)

    def set_eq(self, **params):
        if params:
            self.sc.set(self._eq_node, **params)

    def set_limiter(self, threshold: float | None = None, ratio: float | None = None):
        params = {}
        if threshold is not None:
            params["threshold"] = threshold
        if ratio is not None:
            params["ratio"] = ratio
        if params:
            self.sc.set(self._limiter_node, **params)

    # -- Gradual fades ---------------------------------------------------------

    def set_resonance(self, mix: float | None = None):
        params = {}
        if mix is not None:
            params["mix"] = mix
        if params:
            self.sc.set(self._reson_node, **params)

    async def fade_in(self, duration: float = 8.0, steps: int = 20):
        """Gradually bring the medium from silence to its target levels."""
        step_dur = duration / steps
        for i in range(1, steps + 1):
            t = i / steps
            self.set_noise_floor(level=_lerp(SILENCE_DB, self.spec.noise_floor_level, t))
            self.set_reverb(mix=_lerp(0.0, self._target_reverb_mix, t))
            self.set_resonance(mix=_lerp(0.0, self._target_reson_mix, t))
            await asyncio.sleep(step_dur)

    async def fade_out(self, duration: float = 10.0, steps: int = 25):
        """Gradually fade the medium to silence."""
        start_noise = self.spec.noise_floor_level
        step_dur = duration / steps
        for i in range(1, steps + 1):
            t = i / steps
            self.set_noise_floor(level=_lerp(start_noise, SILENCE_DB, t))
            self.set_reverb(mix=_lerp(self._target_reverb_mix, 0.0, t))
            self.set_resonance(mix=_lerp(self._target_reson_mix, 0.0, t))
            await asyncio.sleep(step_dur)

    def teardown(self):
        self.sc.free(self.group)
        for bus in self._buses:
            self.sc.free_bus(bus)
        self.nodes.clear()
