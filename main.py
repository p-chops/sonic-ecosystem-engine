"""Sonic Ecosystem Engine — continuous runner.

Connects to a running scsynth, loads synthdefs, and cycles through
randomly generated biomes with crossfade transitions. Auto-advances
on a timer. Control via websocket: connect to ws://localhost:8765.

Usage:
  python main.py                     # default settings
  python main.py --port 57110        # custom scsynth port
  python main.py --duration 900      # 15 min per biome
  python main.py --seed 42           # start with a specific seed
  python main.py --archetype drone   # all species are drones (or caller/clicker/swarm/responder)
  python main.py --ws-port 8765      # websocket control port

Requires scsynth already running (boot via SC IDE: s.boot).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import random

from engine.bridge import SCBridge
from engine.control import ControlServer
from engine.ecosystem import EcosystemManager
from generation.derive import generate_biome

SYNTHDEF_DIR = os.path.join(os.path.dirname(__file__), "synthdefs", "compiled")

log = logging.getLogger("see")



async def run(args):
    sc = SCBridge(port=args.port)

    # Load synthdefs
    abs_path = os.path.abspath(SYNTHDEF_DIR)
    print(f"Loading synthdefs from: {abs_path}")
    sc.load_synthdef_dir(abs_path)
    await asyncio.sleep(0.5)

    next_event = asyncio.Event()

    # Manager first — control needs a reference to drive the live ecosystem
    manager = EcosystemManager(sc, empty=args.empty)

    # Start control server, wired to the manager
    control = ControlServer(next_event, manager=manager, port=args.ws_port)
    await control.start()

    manager._on_status = control.push_status


    seed = args.seed if args.seed is not None else random.randint(0, 99999)

    print(f"\n{'=' * 60}")
    print(f"  Sonic Ecosystem Engine")
    print(f"  Auto-advance: {args.duration}s per biome")
    print(f"  Control: ws://localhost:{args.ws_port}")
    print(f"{'=' * 60}\n")

    panic = False
    try:
        while True:
            biome = generate_biome(seed, force_archetype=args.archetype)
            summary = biome.summary()
            print(f"\n--- Biome seed={seed} ---")
            print(summary)
            print()

            control.set_current_biome(biome)
            if panic:
                await manager.panic(biome)
            else:
                await manager.start_biome(biome)

            # Wait for auto-advance timer OR manual skip, pushing status updates
            next_event.clear()
            elapsed = 0.0
            status_interval = 3.0
            while elapsed < args.duration:
                try:
                    await asyncio.wait_for(next_event.wait(), timeout=status_interval)
                    print(">> Skipping to next biome...")
                    break
                except asyncio.TimeoutError:
                    elapsed += status_interval
                    if manager.current:
                        control.push_status(manager.current.get_status())
            else:
                print(">> Auto-advancing...")

            # Check if this was a panic request
            panic = control.is_panic

            # Use requested seed if provided, otherwise random
            requested = control.requested_seed
            seed = requested if requested is not None else random.randint(0, 99999)

    except KeyboardInterrupt:
        print("\n\nShutting down...")

    await control.stop()
    await manager.stop()
    print("Done.")


def main():
    parser = argparse.ArgumentParser(description="Sonic Ecosystem Engine")
    parser.add_argument("--port", type=int, default=57110,
                        help="scsynth UDP port (default: 57110)")
    parser.add_argument("--ws-port", type=int, default=8765,
                        help="websocket control port (default: 8765)")
    parser.add_argument("--duration", type=int, default=600,
                        help="seconds per biome before auto-advance (default: 600)")
    parser.add_argument("--seed", type=int, default=None,
                        help="starting seed (default: random)")
    parser.add_argument("--archetype", type=str, default=None,
                        choices=["caller", "clicker", "drone", "swarm", "responder"],
                        help="force every species to a single archetype (default: mixed)")
    parser.add_argument("--empty", action="store_true",
                        help="start with no agents — populate manually via control (spawn_archetype)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="enable debug logging")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(name)s: %(message)s")

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
