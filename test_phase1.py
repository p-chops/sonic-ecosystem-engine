"""Phase 1 milestone test — fire notes through a voice chain.

Prerequisites:
  - scsynth running (boot via SC IDE: s.boot)
  - SynthDefs compiled (.store from the SC IDE)
  - pip install -e .

Usage:
  python test_phase1.py
"""

import os
import time
import sys

from engine.bridge import SCBridge
from engine.voice_chain import VoiceChain, ChainSpec

SYNTHDEF_DIR = os.path.join(os.path.dirname(__file__), "synthdefs", "compiled")


def main():
    sc = SCBridge()

    # Load synthdefs
    abs_path = os.path.abspath(SYNTHDEF_DIR)
    print(f"Loading synthdefs from: {abs_path}")
    sc.load_synthdef_dir(abs_path)
    time.sleep(0.5)  # give server time to load

    # Verify server is responding
    print("Requesting server status...")
    sc.status()
    time.sleep(0.2)

    # Allocate a dummy medium bus
    medium_bus = sc.alloc_bus()

    # --- Test 1: simple FM note ---
    print("\n--- Test 1: FM through LPF ---")
    spec_fm = ChainSpec(
        source="src_fm",
        effects=[
            ("fx_lpf", {"cutoff": 3000, "res": 0.3}),
        ],
        pan=0.0,
        amp=0.5,
        send=0.0,
        send_bus=medium_bus,
    )
    voice_fm = VoiceChain(spec_fm, sc, medium_bus)
    time.sleep(0.1)

    print("  Playing FM note (220 Hz)...")
    voice_fm.vocalize(freq=220, amp=0.3, decay=1.5, ratio=2.01, index=4)
    time.sleep(2)

    print("  Playing FM note (330 Hz)...")
    voice_fm.vocalize(freq=330, amp=0.2, decay=1.5, ratio=1.5, index=2)
    time.sleep(2)

    # --- Test 2: song bundle ---
    print("\n--- Test 2: FM song bundle (3 notes, sample-accurate) ---")
    voice_fm.vocalize_song([
        {"freq": 440, "amp": 0.2, "decay": 0.3, "gap": 0.15, "ratio": 1.5, "index": 3},
        {"freq": 550, "amp": 0.15, "decay": 0.3, "gap": 0.15, "ratio": 1.5, "index": 2},
        {"freq": 330, "amp": 0.25, "decay": 0.6, "gap": 0.0, "ratio": 2.0, "index": 4},
    ])
    time.sleep(2)

    voice_fm.teardown()

    # --- Test 3: plucked string with delay ---
    print("\n--- Test 3: String through delay ---")
    spec_str = ChainSpec(
        source="src_string",
        effects=[
            ("fx_delay", {"delay_time": 0.15, "feedback": 0.5, "mix": 0.4}),
        ],
        pan=-0.5,
        amp=0.5,
        send=0.0,
        send_bus=medium_bus,
    )
    voice_str = VoiceChain(spec_str, sc, medium_bus)
    time.sleep(0.1)

    print("  Playing string note (180 Hz)...")
    voice_str.vocalize(freq=180, amp=0.3, decay=2.0, brightness=0.7, damping=0.3)
    time.sleep(3)

    voice_str.teardown()

    # --- Test 4: sine partials ---
    print("\n--- Test 4: Sine with partials ---")
    spec_sine = ChainSpec(
        source="src_sine",
        effects=[],
        pan=0.3,
        amp=0.5,
        send=0.0,
        send_bus=medium_bus,
    )
    voice_sine = VoiceChain(spec_sine, sc, medium_bus)
    time.sleep(0.1)

    print("  Playing sine (pure, 1 partial)...")
    voice_sine.vocalize(freq=300, amp=0.2, decay=1.5, n_partials=1)
    time.sleep(2)

    print("  Playing sine (4 partials, spread)...")
    voice_sine.vocalize(freq=200, amp=0.15, decay=2.0, n_partials=4, partial_spread=0.5, partial_falloff=0.6)
    time.sleep(2.5)

    voice_sine.teardown()

    # --- Test 5: noise burst ---
    print("\n--- Test 5: Filtered noise ---")
    spec_noise = ChainSpec(
        source="src_noise",
        effects=[
            ("fx_hpf", {"cutoff": 500, "res": 0.2}),
        ],
        pan=-0.3,
        amp=0.5,
        send=0.0,
        send_bus=medium_bus,
    )
    voice_noise = VoiceChain(spec_noise, sc, medium_bus)
    time.sleep(0.1)

    print("  Playing noise burst...")
    voice_noise.vocalize(freq=1000, amp=0.2, decay=1.0, center_freq=2000, bandwidth=800, noise_type=0)
    time.sleep(1.5)

    print("  Playing pink noise burst...")
    voice_noise.vocalize(freq=1000, amp=0.2, decay=1.5, center_freq=1000, bandwidth=400, noise_type=1)
    time.sleep(2)

    voice_noise.teardown()

    print("\nDone. All tests complete.")


if __name__ == "__main__":
    main()
