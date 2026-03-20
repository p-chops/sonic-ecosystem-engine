"""Phase 4 milestone test — run full biomes end-to-end with medium and transitions.

Usage:
  python test_phase4.py [seed]

Runs a biome for 45s, transitions to a second biome for 45s, then shuts down.
"""

import asyncio
import os
import random
import sys

from engine.bridge import SCBridge
from engine.ecosystem import EcosystemManager
from generation.derive import generate_biome

SYNTHDEF_DIR = os.path.join(os.path.dirname(__file__), "synthdefs", "compiled")


async def main(seed1: int, seed2: int):
    sc = SCBridge()

    abs_path = os.path.abspath(SYNTHDEF_DIR)
    print(f"Loading synthdefs from: {abs_path}")
    sc.load_synthdef_dir(abs_path)
    await asyncio.sleep(0.5)

    manager = EcosystemManager(sc)

    # --- Biome 1 ---
    biome1 = generate_biome(seed1)
    print(f"\n=== Biome 1 (seed={seed1}) ===")
    print(biome1.summary())
    print()

    await manager.start_biome(biome1)
    print("Biome 1 running...\n")

    try:
        # Run biome 1 with status updates
        for i in range(15):
            await asyncio.sleep(3)
            eco = manager.current
            if eco:
                print(f"  t={((i+1)*3):3d}s  "
                      f"agents={eco.alive_count()}  "
                      f"activity={eco.state.activity:.2f}")

        # --- Transition to biome 2 ---
        biome2 = generate_biome(seed2)
        print(f"\n=== Transitioning to Biome 2 (seed={seed2}) ===")
        print(biome2.summary())
        print()

        await manager.start_biome(biome2)
        print("Biome 2 running...\n")

        # Run biome 2
        for i in range(15):
            await asyncio.sleep(3)
            eco = manager.current
            if eco:
                print(f"  t={((i+1)*3):3d}s  "
                      f"agents={eco.alive_count()}  "
                      f"activity={eco.state.activity:.2f}")

    except KeyboardInterrupt:
        print("\nStopping...")

    await manager.stop()
    print("\nDone.")


if __name__ == "__main__":
    seed1 = int(sys.argv[1]) if len(sys.argv) > 1 else random.randint(0, 99999)
    seed2 = int(sys.argv[2]) if len(sys.argv) > 2 else random.randint(0, 99999)
    print(f"Seeds: {seed1} → {seed2}")
    asyncio.run(main(seed1, seed2))
