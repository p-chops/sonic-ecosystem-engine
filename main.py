"""Sonic Ecosystem Engine — continuous runner.

Connects to a running scsynth, loads synthdefs, and cycles through
randomly generated biomes with crossfade transitions. Auto-advances
on a timer. Control via:
  - stdin: type 'n' + Enter to skip to next biome
  - websocket: connect to ws://localhost:8765, send {"cmd": "next"}

Usage:
  python main.py                     # default settings
  python main.py --port 57110        # custom scsynth port
  python main.py --duration 900      # 15 min per biome
  python main.py --seed 42           # start with a specific seed
  python main.py --ws-port 8765      # websocket control port

Requires scsynth already running (boot via SC IDE: s.boot).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import random
import sys

from engine.bridge import SCBridge
from engine.control import ControlServer
from engine.ecosystem import EcosystemManager
from generation.derive import generate_biome

SYNTHDEF_DIR = os.path.join(os.path.dirname(__file__), "synthdefs", "compiled")

log = logging.getLogger("see")


async def stdin_listener(next_event: asyncio.Event):
    """Listen for 'n' on stdin to trigger next biome.

    Uses a thread to avoid connect_read_pipe which puts stdin/stdout
    into non-blocking mode and causes BlockingIOError on print().
    """
    loop = asyncio.get_event_loop()

    def _read_stdin():
        while True:
            try:
                line = sys.stdin.readline()
            except EOFError:
                break
            if not line:
                break
            cmd = line.strip().lower()
            if cmd in ("n", "next"):
                loop.call_soon_threadsafe(next_event.set)

    await loop.run_in_executor(None, _read_stdin)


async def run(args):
    sc = SCBridge(port=args.port)

    # Load synthdefs
    abs_path = os.path.abspath(SYNTHDEF_DIR)
    print(f"Loading synthdefs from: {abs_path}")
    sc.load_synthdef_dir(abs_path)
    await asyncio.sleep(0.5)

    next_event = asyncio.Event()

    # Start control server
    control = ControlServer(next_event, port=args.ws_port)
    await control.start()

    manager = EcosystemManager(sc, on_status=control.push_status)

    # Start stdin listener
    asyncio.create_task(stdin_listener(next_event))

    seed = args.seed if args.seed is not None else random.randint(0, 99999)

    print(f"\n{'=' * 60}")
    print(f"  Sonic Ecosystem Engine")
    print(f"  Auto-advance: {args.duration}s per biome")
    print(f"  Control: stdin ('n') or ws://localhost:{args.ws_port}")
    print(f"{'=' * 60}\n")

    try:
        while True:
            biome = generate_biome(seed)
            summary = biome.summary()
            print(f"\n--- Biome seed={seed} ---")
            print(summary)
            print()

            control.set_current_biome(biome)
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
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="enable debug logging")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(name)s: %(message)s")

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
