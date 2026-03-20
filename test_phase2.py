"""Phase 2 milestone test — spawn agents with hardcoded species, hear them interact.

Prerequisites:
  - scsynth running (boot via SC IDE: s.boot)
  - SynthDefs loaded (evaluate .scd files or load from compiled/)
  - pip install -e .

Usage:
  python test_phase2.py
"""

import asyncio
import os
import random
import time

from engine.bridge import SCBridge
from engine.voice_chain import ChainSpec
from engine.species import Species
from engine.agent import Agent
from engine.archetypes import create_behavior

SYNTHDEF_DIR = os.path.join(os.path.dirname(__file__), "synthdefs", "compiled")


class SimpleEcosystemState:
    """Minimal ecosystem state for testing."""

    def __init__(self):
        self.activity = 0.0
        self.activity_decay = 0.6


# A simple shared pitch set (harmonic series on 150 Hz)
PITCH_SET = [150 * n for n in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 16]]


def make_species() -> list[Species]:
    """Hardcoded species for testing — one of each archetype."""
    return [
        Species(
            name="forest_caller",
            archetype="caller",
            chain_spec=ChainSpec(
                source="src_fm",
                effects=[("fx_lpf", {"cutoff": 4000, "res": 0.2})],
            ),
            freq_range=(200, 1600),
            pitch_set=PITCH_SET,
            population=3,
            age_range=(20, 40),
            depth_dist="sqrt",
            params={
                "song_length": 5,
                "note_dur_range": (0.1, 0.4),
                "note_gap": (0.03, 0.1),
                "base_pause": (2.0, 5.0),
                "transpose_prob": 0.15,
                "fatigue_threshold": 4.0,
            },
        ),
        Species(
            name="night_clicker",
            archetype="clicker",
            chain_spec=ChainSpec(
                source="src_click",
                effects=[],
            ),
            freq_range=(800, 4000),
            pitch_set=PITCH_SET,
            population=4,
            age_range=(15, 30),
            depth_dist="sqrt",
            params={
                "wait_range": (0.5, 2.5),
                "rest_prob": 0.15,
                "chord_prob": 0.08,
                "chord_size": (2, 3),
            },
        ),
        Species(
            name="deep_drone",
            archetype="drone",
            chain_spec=ChainSpec(
                source="src_sine",
                effects=[
                    ("fx_chorus", {"rate": 0.2, "depth": 0.004, "voices": 2}),
                ],
            ),
            freq_range=(60, 300),
            pitch_set=PITCH_SET,
            population=2,
            age_range=(30, 60),
            depth_dist="uniform",
            params={
                "drift_rate": (3.0, 8.0),
                "drift_range": 0.05,
                "inverse_coupling": True,
            },
        ),
        Species(
            name="dust_swarm",
            archetype="swarm",
            chain_spec=ChainSpec(
                source="src_noise",
                effects=[("fx_hpf", {"cutoff": 2000, "res": 0.1})],
            ),
            freq_range=(2000, 8000),
            pitch_set=PITCH_SET,
            population=3,
            age_range=(10, 25),
            depth_dist="sqrt",
            params={
                "density": 12,
                "pitch_scatter": 0.1,
                "amp_scatter": 0.4,
            },
        ),
        Species(
            name="echo_responder",
            archetype="responder",
            chain_spec=ChainSpec(
                source="src_string",
                effects=[
                    ("fx_delay", {"delay_time": 0.2, "feedback": 0.4, "mix": 0.5}),
                ],
            ),
            freq_range=(150, 800),
            pitch_set=PITCH_SET,
            population=1,
            age_range=(25, 50),
            depth_dist="close",
            params={
                "trigger_threshold": 2.0,
                "response_delay": (0.3, 0.8),
                "cooldown": (4.0, 8.0),
                "response_song_length": 3,
            },
        ),
    ]


async def run_ecosystem(duration: float = 60.0):
    sc = SCBridge()

    # Load synthdefs
    abs_path = os.path.abspath(SYNTHDEF_DIR)
    print(f"Loading synthdefs from: {abs_path}")
    sc.load_synthdef_dir(abs_path)
    await asyncio.sleep(0.5)

    # Allocate medium bus (no medium processing in phase 2, just a bus)
    medium_bus = sc.alloc_bus()

    state = SimpleEcosystemState()
    species_list = make_species()
    agents: list[Agent] = []
    tasks: list[asyncio.Task] = []

    print(f"\nSpawning agents for {duration}s ecosystem run...\n")

    # Spawn initial agents
    for sp in species_list:
        for i in range(sp.population):
            rng = random.Random()
            agent = Agent(sp, sc, medium_bus, state, rng)
            agent.behavior = create_behavior(agent, sp)
            agents.append(agent)
            task = asyncio.create_task(agent.run())
            tasks.append(task)
            print(f"  Spawned {sp.name} #{i+1}  depth={agent.depth:.2f}  pan={agent.pos:.2f}")

    print(f"\n{len(agents)} agents running. Ctrl+C to stop early.\n")

    # Activity decay loop
    try:
        elapsed = 0.0
        tick = 1.0
        while elapsed < duration:
            await asyncio.sleep(tick)
            elapsed += tick
            state.activity *= state.activity_decay
            alive_count = sum(1 for a in agents if a.alive)
            print(f"  t={elapsed:5.1f}s  activity={state.activity:.2f}  alive={alive_count}/{len(agents)}")
    except KeyboardInterrupt:
        print("\nStopping early...")

    # Teardown
    print("\nTearing down...")
    for agent in agents:
        if agent.alive:
            agent.die()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    sc.free_all()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(run_ecosystem(duration=60))
