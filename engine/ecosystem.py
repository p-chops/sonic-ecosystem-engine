"""Ecosystem — population manager + main loop.

Manages the lifecycle of agents: spawning to population targets, aging,
culling, activity decay. Also owns the Medium and handles biome transitions.
"""

from __future__ import annotations

import asyncio
import logging
import math
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
        # Spawn at most max_per_tick agents total per tick for staggered entry
        max_per_tick = 2
        spawned = 0
        species_list = list(self.biome.species)
        random.shuffle(species_list)
        for species in species_list:
            if spawned >= max_per_tick:
                break
            target = self.state.get_population_target(species)
            current = sum(1 for a in self.agents if a.species.name == species.name)
            if current < target:
                self._spawn_agent(species)
                spawned += 1

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

    def current_energy(self) -> float:
        """Compute actual energy from live agents, modeling dry/wet signal path."""
        duty = {
            "caller": 0.30, "clicker": 0.15, "drone": 1.00,
            "swarm": 0.40, "responder": 0.10,
        }
        med = self.biome.medium
        reverb_return = med.reverb_mix * min(med.reverb_time / 10.0, 1.0)
        total = 0.0
        for agent in self.agents:
            if agent.alive:
                d = duty.get(agent.species.archetype, 0.3)
                send = agent.send
                effective_amp = agent.amp * ((1 - send) + send * reverb_return)
                total += effective_amp * d
        return total

    def get_status(self) -> dict:
        """Snapshot of current ecosystem state for the web UI."""
        species_counts: dict[str, int] = {}
        # Per-agent amplitudes grouped by species (for sized emoji display)
        species_agents: dict[str, list[float]] = {}
        for agent in self.agents:
            if agent.alive and agent.has_voiced:
                name = agent.species.name
                species_counts[name] = species_counts.get(name, 0) + 1
                species_agents.setdefault(name, []).append(round(agent.amp, 4))

        return {
            "agents_alive": self.alive_count(),
            "agents_total": self.agent_count(),
            "activity": round(self.state.activity, 3),
            "spawning": self._spawning,
            "species_counts": species_counts,
            "species_agents": species_agents,
            "nodes": self.sc.node_count_estimate(),
        }

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

    # Energy estimation reference — a "typical" biome's estimated energy.
    # Biomes below this get boosted, above get attenuated.
    _REFERENCE_ENERGY = 1.0
    # Makeup gain range (dB). Default is 6dB; estimation shifts within this range.
    _MAKEUP_MIN = 0.0
    _MAKEUP_MAX = 18.0
    _MAKEUP_DEFAULT = 6.0
    # AGC smoothing — how fast the AGC corrects (0=frozen, 1=instant)
    _AGC_SMOOTHING = 0.25
    _AGC_INTERVAL = 3.0  # seconds between AGC adjustments

    def __init__(self, sc: SCBridge, on_status=None):
        self.sc = sc
        self.current: Ecosystem | None = None
        self._run_task: asyncio.Task | None = None
        self._limiter_node: int | None = None
        self._on_status = on_status  # callable(dict) — called during transitions
        self._current_makeup: float = self._MAKEUP_DEFAULT
        self._target_makeup: float = self._MAKEUP_DEFAULT
        self._agc_task: asyncio.Task | None = None

    def _compute_makeup(self, biome: BiomeSpec) -> float:
        """Compute limiter makeup gain (dB) to normalize a biome's output level."""
        from generation.derive import estimate_biome_energy

        energy = estimate_biome_energy(biome)
        if energy <= 0:
            return self._MAKEUP_DEFAULT

        # dB compensation: quiet biomes get more gain, loud ones get less
        compensation_db = -10 * math.log10(energy / self._REFERENCE_ENERGY)
        makeup = self._MAKEUP_DEFAULT + compensation_db
        makeup = max(self._MAKEUP_MIN, min(self._MAKEUP_MAX, makeup))

        log.info("Biome energy=%.3f → makeup=%.1fdB (compensation=%+.1fdB)",
                 energy, makeup, compensation_db)
        return makeup

    def _set_makeup(self, db: float):
        """Apply makeup gain to the limiter node."""
        self._current_makeup = db
        if self._limiter_node is not None:
            self.sc.set(self._limiter_node, makeup=db)

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
                threshold=-18,  # low threshold — engage on average levels, not just peaks
                ratio=8,        # aggressive leveling
                attack=0.1,     # 100ms — slow enough to not pump on transients
                release=1.0,    # 1s — smooth ride over agent spawns/deaths
                makeup=self._current_makeup,
            )

    async def _agc_loop(self):
        """Reactive automatic gain control — recomputes target from live agent
        state every tick and smoothly adjusts makeup to compensate."""
        while True:
            await asyncio.sleep(self._AGC_INTERVAL)
            if self.current is None or self._limiter_node is None:
                continue

            # Recompute target from actual live energy
            live_energy = self.current.current_energy()
            if live_energy > 0:
                compensation_db = -10 * math.log10(live_energy / self._REFERENCE_ENERGY)
                self._target_makeup = max(self._MAKEUP_MIN,
                    min(self._MAKEUP_MAX, self._MAKEUP_DEFAULT + compensation_db))

            # Log node counts for leak detection
            counts = self.sc.node_count_estimate()
            log.debug("Nodes: %d persistent, %d transient (overcounted), ~%d total",
                      counts["persistent"], counts["transient"], counts["total_estimate"])

            # Smooth exponential approach to target
            error = self._target_makeup - self._current_makeup
            if abs(error) > 0.1:  # don't bother with sub-0.1dB adjustments
                new_makeup = self._current_makeup + error * self._AGC_SMOOTHING
                new_makeup = max(self._MAKEUP_MIN, min(self._MAKEUP_MAX, new_makeup))
                self._set_makeup(new_makeup)

    def _start_agc(self):
        """Start the AGC background loop if not already running."""
        if self._agc_task is None or self._agc_task.done():
            self._agc_task = asyncio.create_task(self._agc_loop())

    async def start_biome(self, biome: BiomeSpec):
        """Start a new biome, transitioning from any current one."""
        self._ensure_limiter()
        self._target_makeup = self._compute_makeup(biome)
        self._start_agc()
        if self.current is not None:
            await self._transition_to(biome)
        else:
            # First biome — apply makeup immediately
            self._set_makeup(self._target_makeup)
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

        # Set new makeup target — AGC will smoothly interpolate during crossfade
        self._target_makeup = self._compute_makeup(new_biome)

        # Phase 1: Stop spawning old agents + begin fading out old medium
        old.stop_spawning()
        log.info("Transition: fading out old biome (seed=%d)", old.biome.seed)
        fade_out_task = asyncio.create_task(old.medium.fade_out(duration=fade_out_dur))
        self._push_status({"transitioning": True, **old.get_status()})

        # Brief pause before starting new biome (let old start to thin)
        await asyncio.sleep(overlap_delay)

        # Phase 2: Start new ecosystem with silent medium, fade it in
        self.current = Ecosystem(new_biome, self.sc, start_silent=True)
        new_task = asyncio.create_task(self.current.run())
        fade_in_task = asyncio.create_task(
            self.current.medium.fade_in(duration=fade_in_dur)
        )
        self._push_status({"transitioning": True, **self.current.get_status()})

        # Phase 3: Wait for old agents to die off naturally (up to deadline)
        elapsed = overlap_delay
        tick = 1.0
        while old.alive_count() > 0 and elapsed < deadline:
            await asyncio.sleep(tick)
            elapsed += tick
            old._age_and_cull()
            old._decay_activity()
            if self.current:
                self._push_status({"transitioning": True, **self.current.get_status()})

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

    def _push_status(self, status: dict):
        if self._on_status:
            self._on_status(status)

    async def panic(self, biome: BiomeSpec):
        """Nuclear option — free all scsynth nodes and start a fresh biome.

        Skips graceful transitions. Use when nodes have leaked or audio is broken.
        """
        log.warning("PANIC — freeing all nodes")
        # Kill everything on the SC server
        self.sc.free_all()
        # Reset Python-side state
        if self._agc_task is not None:
            self._agc_task.cancel()
            try:
                await self._agc_task
            except asyncio.CancelledError:
                pass
            self._agc_task = None
        if self._run_task is not None:
            self._run_task.cancel()
            try:
                await self._run_task
            except asyncio.CancelledError:
                pass
        self.current = None
        self._limiter_node = None
        self._current_makeup = self._MAKEUP_DEFAULT
        # Start fresh
        self._ensure_limiter()
        self._target_makeup = self._compute_makeup(biome)
        self._set_makeup(self._target_makeup)
        self._start_agc()
        self.current = Ecosystem(biome, self.sc)
        self._run_task = asyncio.create_task(self.current.run())
        log.info("PANIC recovery complete — new biome seed=%d", biome.seed)

    async def stop(self):
        """Stop everything."""
        if self._agc_task is not None:
            self._agc_task.cancel()
            try:
                await self._agc_task
            except asyncio.CancelledError:
                pass
            self._agc_task = None
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
