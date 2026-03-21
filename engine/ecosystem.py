"""Ecosystem — population manager + main loop.

Manages the lifecycle of agents: spawning to population targets, aging,
culling, activity decay. Also owns the Medium and handles biome transitions.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING

from engine.agent import Agent
from engine.archetypes import create_behavior
from engine.medium import Medium

if TYPE_CHECKING:
    from engine.bridge import SCBridge
    from engine.species import Species
    from generation.derive import BiomeSpec

log = logging.getLogger(__name__)


class EcosystemState:
    """Mutable runtime state. The single source of truth for all live parameters."""

    def __init__(self, biome: BiomeSpec):
        self.species_targets: dict[str, int] = {
            sp.name: sp.population for sp in biome.species
        }
        self.activity: float = 0.0
        self.activity_decay: float = 0.6
        self.tick_interval: float = 3.0

    def get_population_target(self, species: Species) -> int:
        return self.species_targets.get(species.name, 0)


class Ecosystem:
    """Runs a single biome: population management, activity decay, medium."""

    def __init__(self, biome: BiomeSpec, sc: SCBridge, start_silent: bool = False):
        self.biome = biome
        self.sc = sc
        self.state = EcosystemState(biome)
        # Agent group first, medium group second — execution order matters.
        # Agents write to the medium bus; medium must read after agents.
        self.agents_group = sc.new_group()
        self.medium = Medium(biome.medium, sc, start_silent=start_silent)
        self.agents: list[Agent] = []
        self._tasks: list[asyncio.Task] = []
        self.alive = True
        self._spawning = True  # can be disabled for transitions

    async def run(self):
        """Main ecosystem loop."""
        log.info("Ecosystem starting: seed=%d, %d species",
                 self.biome.seed, len(self.biome.species))
        while self.alive:
            self._age_and_cull()
            if self._spawning:
                self._spawn_to_targets()
            self._decay_activity()
            await asyncio.sleep(self.state.tick_interval)

    def _age_and_cull(self):
        for agent in self.agents:
            agent.age += 1
            if agent.age >= agent.max_age:
                agent.die()
        self.agents = [a for a in self.agents if a.alive]
        # Clean up finished tasks
        self._tasks = [t for t in self._tasks if not t.done()]

    def _spawn_to_targets(self):
        for species in self.biome.species:
            target = self.state.get_population_target(species)
            current = sum(1 for a in self.agents if a.species.name == species.name)
            while current < target:
                self._spawn_agent(species)
                current += 1

    def _spawn_agent(self, species) -> Agent:
        rng = random.Random()
        agent = Agent(species, self.sc, self.medium.bus, self.state, rng,
                      parent_group=self.agents_group)
        agent.behavior = create_behavior(agent, species)
        self.agents.append(agent)
        task = asyncio.create_task(agent.run())
        self._tasks.append(task)
        return agent

    def _decay_activity(self):
        self.state.activity *= self.state.activity_decay

    def stop_spawning(self):
        """Stop spawning new agents (used during transitions)."""
        self._spawning = False

    def agent_count(self) -> int:
        return len(self.agents)

    def alive_count(self) -> int:
        return sum(1 for a in self.agents if a.alive)

    async def teardown(self):
        """Kill all agents and free medium. Drones get a graceful fade-out."""
        self.alive = False
        self._spawning = False
        # Graceful death for drones (fade out), instant for others
        fade_tasks = []
        for agent in self.agents:
            if agent.alive:
                fade_tasks.append(asyncio.create_task(agent.graceful_die()))
        if fade_tasks:
            await asyncio.gather(*fade_tasks, return_exceptions=True)
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self.sc.free(self.agents_group)
        self.medium.teardown()
        self.agents.clear()
        self._tasks.clear()


class EcosystemManager:
    """Manages biome transitions — crossfading between ecosystems."""

    def __init__(self, sc: SCBridge):
        self.sc = sc
        self.current: Ecosystem | None = None
        self._run_task: asyncio.Task | None = None
        self._limiter_node: int | None = None

    def _ensure_limiter(self):
        """Create a single persistent limiter on bus 0 if not already running."""
        if self._limiter_node is None:
            # Limiter group goes at the very end of the node tree
            from engine.bridge import ADD_TO_TAIL
            self._limiter_group = self.sc.new_group()
            self._limiter_node = self.sc.synth(
                "med_limiter",
                target_group=self._limiter_group,
                add_action=ADD_TO_TAIL,
                **{"in": 0, "out": 0},
                threshold=-6,
                ratio=4,
                makeup=6,
            )

    async def start_biome(self, biome: BiomeSpec):
        """Start a new biome, transitioning from any current one."""
        self._ensure_limiter()
        if self.current is not None:
            await self._transition_to(biome)
        else:
            self.current = Ecosystem(biome, self.sc)
            self._run_task = asyncio.create_task(self.current.run())

    async def _transition_to(self, new_biome: BiomeSpec):
        """Crossfade from current biome to new one.

        Timeline:
          0s     — stop spawning old agents, begin fading out old medium
          ~3s    — start new ecosystem (silent medium), begin fading in new medium
          ~10s   — old medium fully faded, new medium approaching target levels
          ~15s   — force-teardown any lingering old agents
        """
        old = self.current
        fade_out_dur = 10.0
        fade_in_dur = 8.0
        overlap_delay = 3.0
        deadline = 15.0

        # Phase 1: Stop spawning old agents + begin fading out old medium
        old.stop_spawning()
        log.info("Transition: fading out old biome (seed=%d)", old.biome.seed)
        fade_out_task = asyncio.create_task(old.medium.fade_out(duration=fade_out_dur))

        # Brief pause before starting new biome (let old start to thin)
        await asyncio.sleep(overlap_delay)

        # Phase 2: Start new ecosystem with silent medium, fade it in
        self.current = Ecosystem(new_biome, self.sc, start_silent=True)
        new_task = asyncio.create_task(self.current.run())
        fade_in_task = asyncio.create_task(
            self.current.medium.fade_in(duration=fade_in_dur)
        )

        # Phase 3: Wait for old agents to die off naturally (up to deadline)
        elapsed = overlap_delay
        tick = 1.0
        while old.alive_count() > 0 and elapsed < deadline:
            await asyncio.sleep(tick)
            elapsed += tick
            old._age_and_cull()
            old._decay_activity()

        # Phase 4: Ensure fades have finished
        await asyncio.gather(fade_out_task, fade_in_task, return_exceptions=True)

        # Phase 5: Force-teardown old ecosystem
        old.alive = False
        if self._run_task is not None:
            self._run_task.cancel()
            try:
                await self._run_task
            except asyncio.CancelledError:
                pass
        await old.teardown()
        log.info("Transition: old biome torn down after %.1fs", elapsed)

        self._run_task = new_task

    async def stop(self):
        """Stop everything."""
        if self.current is not None:
            self.current.alive = False
            if self._run_task is not None:
                self._run_task.cancel()
                try:
                    await self._run_task
                except asyncio.CancelledError:
                    pass
            await self.current.teardown()
            self.current = None
        self._limiter_node = None
        self.sc.free_all()
