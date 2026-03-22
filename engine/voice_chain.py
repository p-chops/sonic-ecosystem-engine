"""VoiceChain — per-agent signal chain management.

A voice chain is a source slot followed by zero or more effects, wired
through private audio buses within a dedicated scsynth group. Sources
fire into the head of the group (self-freeing after their envelope),
while effects persist for the agent's lifetime.

    Agent Group
      ├─ [source synths fire here, self-free after envelope]
      ├─ fx_lpf  (bus A → bus B)
      ├─ fx_fold (bus B → bus C)
      └─ fx_pan_out (bus C → main out + medium send)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pythonosc.osc_bundle_builder import OscBundleBuilder

from engine.bridge import ADD_TO_HEAD, ADD_TO_TAIL

if TYPE_CHECKING:
    from engine.bridge import SCBridge

log = logging.getLogger(__name__)


@dataclass
class ChainSpec:
    """Blueprint for a voice chain, generated per-species."""
    source: str                                    # e.g. "src_fm"
    effects: list[tuple[str, dict]] = field(default_factory=list)  # [(name, params), ...]
    source_params: dict = field(default_factory=dict)  # species-level source params (ratio, index, etc.)
    pan: float = 0.0
    amp: float = 1.0
    send: float = 0.3      # medium bus send level
    send_bus: int = 0       # medium bus index (set at ecosystem level)


class VoiceChain:
    """Runtime signal chain for a single agent."""

    def __init__(self, spec: ChainSpec, sc: SCBridge, medium_bus: int,
                 parent_group: int = 1):
        self.sc = sc
        self.spec = spec
        self._torn_down = False
        self.group = sc.new_group(target=parent_group)
        self.buses: list[int] = []
        self.effect_nodes: list[int] = []

        # Allocate the input bus (sources write here)
        prev_bus = sc.alloc_bus()
        self.input_bus = prev_bus
        self.buses.append(prev_bus)

        # Build effect chain: each reads from prev_bus, writes to next_bus
        for fx_name, fx_params in spec.effects:
            next_bus = sc.alloc_bus()
            self.buses.append(next_bus)
            node = sc.synth(
                fx_name,
                target_group=self.group,
                add_action=ADD_TO_TAIL,
                **{"in": prev_bus, "out": next_bus},
                **fx_params,
            )
            self.effect_nodes.append(node)
            prev_bus = next_bus

        # Final output — pan, amp, and send to main + medium bus
        self.output_node = sc.synth(
            "fx_pan_out",
            target_group=self.group,
            add_action=ADD_TO_TAIL,
            **{"in": prev_bus},
            pan=spec.pan,
            amp=spec.amp,
            send=spec.send,
            send_bus=medium_bus,
        )

    def vocalize(self, **note_params) -> int:
        """Fire a note into the chain. The source self-frees via doneAction: 2.

        Species-level source_params are sent as defaults; note_params override.
        Returns the source synth node ID, or -1 if torn down.
        """
        if self._torn_down:
            return -1
        # Species defaults, overridden by per-note params
        params = {**self.spec.source_params, **note_params}
        return self.sc.synth(
            self.spec.source,
            target_group=self.group,
            add_action=ADD_TO_HEAD,
            transient=True,  # self-frees via doneAction:2
            out=self.input_bus,
            **params,
        )

    def vocalize_song(self, notes: list[dict]) -> None:
        """Fire a sequence of notes as a single OSC bundle for sample-accurate timing.

        Each note dict should contain: freq, amp, decay, dur (sounding duration),
        gap (silence after note). Source-specific params are passed through.
        """
        if self._torn_down:
            return
        bundle = OscBundleBuilder(timestamp=0)  # IMMEDIATELY
        t = time.time()

        for note in notes:
            # Separate timing keys from synth params
            gap = note.get("gap", 0.0)
            dur = note.get("dur", note.get("decay", 0.5))
            synth_params = {
                **self.spec.source_params,
                **{k: v for k, v in note.items() if k not in ("gap", "dur")},
            }

            _, msg = self.sc.make_synth_msg(
                self.spec.source,
                target_group=self.group,
                add_action=ADD_TO_HEAD,
                out=self.input_bus,
                **synth_params,
            )

            # Wrap in a timed sub-bundle
            sub = OscBundleBuilder(timestamp=t)
            sub.add_content(msg.build())
            bundle.add_content(sub.build())

            t += dur + gap

        self.sc.send_bundle(bundle)

    def set_pan(self, pan: float):
        """Update the pan position."""
        if not self._torn_down:
            self.sc.set(self.output_node, pan=pan)

    def set_amp(self, amp: float):
        """Update the output amplitude."""
        if not self._torn_down:
            self.sc.set(self.output_node, amp=amp)

    def set_send(self, send: float):
        """Update the medium bus send level."""
        if not self._torn_down:
            self.sc.set(self.output_node, send=send)

    def set_effect_param(self, effect_index: int, **params):
        """Update parameters on a specific effect in the chain."""
        if not self._torn_down and 0 <= effect_index < len(self.effect_nodes):
            self.sc.set(self.effect_nodes[effect_index], **params)

    def teardown(self):
        """Free the group (kills all synths) and release buses."""
        self._torn_down = True
        self.sc.free(self.group)
        for bus in self.buses:
            self.sc.free_bus(bus)
        self.buses.clear()
        self.effect_nodes.clear()
