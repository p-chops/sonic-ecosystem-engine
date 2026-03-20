"""Minimal test: does signal reach the medium bus and come back as reverb?

Spawns one agent, one medium, and fires notes. Listen for reverb tail.
"""

import os
import time

from engine.bridge import SCBridge, ADD_TO_TAIL, ADD_TO_HEAD
from engine.medium import Medium
from generation.derive import MediumSpec, Resonance

SYNTHDEF_DIR = os.path.join(os.path.dirname(__file__), "synthdefs", "compiled")


def main():
    sc = SCBridge()
    sc.load_synthdef_dir(os.path.abspath(SYNTHDEF_DIR))
    time.sleep(0.5)

    # Create a medium with obvious reverb
    spec = MediumSpec(
        reverb_time=0.9,
        reverb_damping=0.3,
        resonances=[Resonance(freq=400, q=10, amp=1.0)],
        noise_floor_level=-96,  # silent noise floor so we can hear reverb clearly
        noise_floor_color=0.5,
        limiter_threshold=-3,
    )
    medium = Medium(spec, sc)
    print(f"Medium bus: {medium.bus}")
    print(f"Medium group: {medium.group}")

    # Create an agent group (before medium group in execution order)
    agent_group = sc.new_group(target=medium.group, add_action=2)  # ADD_BEFORE
    print(f"Agent group: {agent_group}")

    # Allocate a bus for the voice chain
    voice_bus = sc.alloc_bus()

    # Simple effect chain: just fx_pan_out with high send
    pan_out = sc.synth("fx_pan_out", target_group=agent_group,
                       add_action=ADD_TO_TAIL,
                       **{"in": voice_bus},
                       pan=0, amp=0.5, send=0.8, send_bus=medium.bus)
    print(f"Pan out node: {pan_out}, send_bus={medium.bus}")

    # Dump the node tree
    sc.dump_tree(controls=True)
    time.sleep(0.2)

    # Fire some notes — should hear dry + reverb tail
    print("\nFiring notes — listen for reverb tail...")
    for freq in [300, 400, 500, 600]:
        sc.synth("src_fm", target_group=agent_group,
                 add_action=ADD_TO_HEAD,
                 out=voice_bus, freq=freq, amp=0.3, decay=0.3,
                 ratio=1.5, index=3)
        time.sleep(1.0)

    print("\nSilence — reverb tail should linger...")
    time.sleep(4)

    # Compare: same notes without medium send
    print("\nSame notes with send=0 (no reverb)...")
    sc.set(pan_out, send=0.0)
    for freq in [300, 400, 500, 600]:
        sc.synth("src_fm", target_group=agent_group,
                 add_action=ADD_TO_HEAD,
                 out=voice_bus, freq=freq, amp=0.3, decay=0.3,
                 ratio=1.5, index=3)
        time.sleep(1.0)

    print("\nSilence — should be dry, no tail...")
    time.sleep(4)

    # Cleanup
    sc.free(agent_group)
    medium.teardown()
    print("Done.")


if __name__ == "__main__":
    main()
