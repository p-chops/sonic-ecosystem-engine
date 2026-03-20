"""Phase 3 milestone test — generate biomes from seeds, verify determinism,
then play one live.

Usage:
  python test_phase3.py [seed]
"""

import asyncio
import os
import random
import sys
import time

from engine.bridge import SCBridge
from engine.agent import Agent
from engine.archetypes import create_behavior
from generation.derive import generate_biome

SYNTHDEF_DIR = os.path.join(os.path.dirname(__file__), "synthdefs", "compiled")


def test_determinism():
    """Verify same seed produces identical biome."""
    seed = 42
    b1 = generate_biome(seed)
    b2 = generate_biome(seed)

    assert b1.dna == b2.dna, "DNA mismatch"
    assert b1.pitch_set_strategy == b2.pitch_set_strategy, "Pitch strategy mismatch"
    assert b1.pitch_set == b2.pitch_set, "Pitch set mismatch"
    assert len(b1.species) == len(b2.species), "Species count mismatch"
    for s1, s2 in zip(b1.species, b2.species):
        assert s1.archetype == s2.archetype, f"Archetype mismatch: {s1.name}"
        assert s1.chain_spec.source == s2.chain_spec.source, f"Source mismatch: {s1.name}"
        assert s1.population == s2.population, f"Population mismatch: {s1.name}"
    print("Determinism check passed.\n")


def test_variety():
    """Generate several biomes and show their variety."""
    print("--- Sample biomes ---\n")
    for seed in [1, 42, 100, 777, 9999]:
        biome = generate_biome(seed)
        print(biome.summary())
        print()


class SimpleEcosystemState:
    def __init__(self):
        self.activity = 0.0
        self.activity_decay = 0.6


async def play_biome(seed: int, duration: float = 60.0):
    """Generate and play a biome."""
    sc = SCBridge()

    abs_path = os.path.abspath(SYNTHDEF_DIR)
    print(f"Loading synthdefs from: {abs_path}")
    sc.load_synthdef_dir(abs_path)
    await asyncio.sleep(0.5)

    biome = generate_biome(seed)
    print(f"\n{biome.summary()}\n")

    medium_bus = sc.alloc_bus()
    state = SimpleEcosystemState()
    agents: list[Agent] = []
    tasks: list[asyncio.Task] = []

    # Spawn all agents
    for sp in biome.species:
        for i in range(sp.population):
            rng = random.Random()
            agent = Agent(sp, sc, medium_bus, state, rng)
            agent.behavior = create_behavior(agent, sp)
            agents.append(agent)
            tasks.append(asyncio.create_task(agent.run()))

    total = len(agents)
    print(f"{total} agents spawned. Running for {duration}s... (Ctrl+C to stop)\n")

    try:
        elapsed = 0.0
        tick = 2.0
        while elapsed < duration:
            await asyncio.sleep(tick)
            elapsed += tick
            state.activity *= state.activity_decay
            alive = sum(1 for a in agents if a.alive)
            print(f"  t={elapsed:5.1f}s  activity={state.activity:.2f}  alive={alive}/{total}")
    except KeyboardInterrupt:
        print("\nStopping...")

    for agent in agents:
        if agent.alive:
            agent.die()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    sc.free_all()
    print("Done.")


if __name__ == "__main__":
    test_determinism()
    test_variety()

    seed = int(sys.argv[1]) if len(sys.argv) > 1 else random.randint(0, 99999)
    print(f"=== Playing biome seed={seed} ===\n")
    asyncio.run(play_biome(seed))
