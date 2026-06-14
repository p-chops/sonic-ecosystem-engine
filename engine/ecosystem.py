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

ARCHETYPES = ("caller", "clicker", "drone", "swarm", "responder")


class EcosystemState:
    """Mutable runtime state. The single source of truth for all live parameters."""

    def __init__(self, biome: BiomeSpec, empty: bool = False):
        self.species_targets: dict[str, int] = {
            sp.name: (0 if empty else sp.population) for sp in biome.species
        }
        self.activity: float = 0.0
        self.activity_decay: float = 0.6
        self.tick_interval: float = 3.0
        self.send_scale: float = 1.0  # global agent→medium send multiplier

    def get_population_target(self, species: Species) -> int:
        return self.species_targets.get(species.name, 0)


class Ecosystem:
    """Runs a single biome: population management, activity decay, medium."""

    def __init__(self, biome: BiomeSpec, sc: SCBridge, start_silent: bool = False,
                 empty: bool = False):
        self.biome = biome
        self.sc = sc
        self.state = EcosystemState(biome, empty=empty)
        self._adhoc_idx = 1000  # name counter for on-demand minted species
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

    # -- Live control (external apps via websocket) ---------------------------

    def _species_by_name(self, name: str):
        for sp in self.biome.species:
            if sp.name == name:
                return sp
        return None

    def set_species_target(self, name: str, n: int) -> int:
        """Set a species' population target. Spawn loop converges over next ticks.
        Returns the clamped value applied."""
        if name not in self.state.species_targets:
            raise ValueError(f"unknown species: {name}")
        n = max(0, min(64, int(n)))
        self.state.species_targets[name] = n
        return n

    def spawn(self, name: str, count: int = 1) -> int:
        """Spawn agents of a species immediately (bypasses per-tick spawn limit).
        Returns how many were spawned."""
        species = self._species_by_name(name)
        if species is None:
            raise ValueError(f"unknown species: {name}")
        count = max(1, min(16, int(count)))
        for _ in range(count):
            self._spawn_agent(species)
        return count

    def spawn_archetype(self, archetype: str, count: int = 1) -> dict:
        """Spawn agent(s) of an archetype, independent of biome population.
        Reuses an existing species of that archetype if the biome has one;
        otherwise mints a fresh species from the biome's DNA + pitch set.
        Returns {archetype, species, spawned}."""
        if archetype not in ARCHETYPES:
            raise ValueError(f"unknown archetype: {archetype}")
        count = max(1, min(16, int(count)))

        species = next((sp for sp in self.biome.species
                        if sp.archetype == archetype), None)
        if species is None:
            from generation.derive import _derive_single_species
            species = _derive_single_species(
                archetype, self._adhoc_idx, self.biome.dna,
                self.biome.pitch_set, random.Random(),
            )
            self._adhoc_idx += 1
            self.biome.species.append(species)
            self.state.species_targets.setdefault(species.name, 0)

        for _ in range(count):
            self._spawn_agent(species)
        return {"archetype": archetype, "species": species.name, "spawned": count}

    def cull(self, name: str, count: int = 1) -> int:
        """Kill the oldest N agents of a species immediately.
        Returns how many were culled."""
        if self._species_by_name(name) is None:
            raise ValueError(f"unknown species: {name}")
        count = max(1, int(count))
        victims = sorted(
            (a for a in self.agents if a.alive and a.species.name == name),
            key=lambda a: a.age, reverse=True,
        )[:count]
        for a in victims:
            a.die()
        self.agents = [a for a in self.agents if a.alive]
        return len(victims)

    def set_activity(self, value: float) -> float:
        """Set the shared activity level absolutely. Decays each tick.
        Drives flocking (pause compression) and responder firing."""
        self.state.activity = max(0.0, min(50.0, float(value)))
        return self.state.activity

    def bump_activity(self, amount: float = 1.0) -> float:
        """Add to the shared activity level. Returns the new level."""
        return self.set_activity(self.state.activity + float(amount))

    def set_medium_send(self, scale: float) -> float:
        """Scale every agent's send into the medium/reverb path. 1.0 = default,
        >1 wetter, 0 fully dry. Applies live + to future spawns. The dominant
        control for how audible the reverb/resonance/medium is."""
        scale = max(0.0, min(2.0, float(scale)))
        self.state.send_scale = scale
        for a in self.agents:
            if a.alive:
                a.send = min(1.0, a.base_send * scale)
                a.voice.set_send(a.send)
        return scale

    def medium_values(self) -> dict:
        """Current live medium parameter values (for state snapshots)."""
        v = dict(self.medium.live)
        v["send_scale"] = self.state.send_scale
        return v

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
    """Manages biome transitions — crossfading between ecosystems.

    Loudness leveling is handled downstream (OBS). The engine keeps a fixed
    multiband mastering limiter (brickwall safety) but no auto gain control.
    """

    # Fixed limiter makeup gain (dB). No AGC — OBS owns loudness leveling.
    _MAKEUP_DEFAULT = 8.0

    def __init__(self, sc: SCBridge, on_status=None, empty: bool = False):
        self.sc = sc
        self.current: Ecosystem | None = None
        self._run_task: asyncio.Task | None = None
        self._limiter_node: int | None = None
        self._on_status = on_status  # callable(dict) — called during transitions
        self._transitioning: bool = False
        self.empty = empty  # start biomes with no agents (manual spawn only)

    @property
    def transitioning(self) -> bool:
        return self._transitioning

    def _ensure_limiter(self):
        """Create a persistent multi-band mastering chain on bus 0."""
        if self._limiter_node is None:
            from engine.bridge import ADD_TO_TAIL
            self._limiter_group = self.sc.new_group()
            self._limiter_node = self.sc.synth(
                "med_master",
                target_group=self._limiter_group,
                add_action=ADD_TO_TAIL,
                **{"in": 0, "out": 0},
                drive=12,         # slam into the compressors
                lo_boost=6,       # bring up the low end hard (drones)
                hi_boost=3,       # boost highs (insects/birds)
                lo_thresh=-30,    # engage on everything
                mid_thresh=-26,
                hi_thresh=-24,
                lo_ratio=12,      # heavy squash per band
                mid_ratio=10,
                hi_ratio=8,
                lo_attack=0.05,   # slow enough for bass transients
                mid_attack=0.02,
                hi_attack=0.01,   # fast catch on harsh highs
                lo_release=0.6,
                mid_release=0.4,
                hi_release=0.3,
                xover_lo=200,
                xover_hi=3000,
                makeup=self._MAKEUP_DEFAULT,
            )

    async def start_biome(self, biome: BiomeSpec):
        """Start a new biome, transitioning from any current one."""
        self._ensure_limiter()
        if self.current is not None:
            await self._transition_to(biome)
        else:
            self.current = Ecosystem(biome, self.sc, empty=self.empty)
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
        self._transitioning = True

        # Phase 1: Stop spawning old agents + begin fading out old medium
        old.stop_spawning()
        log.info("Transition: fading out old biome (seed=%d)", old.biome.seed)
        fade_out_task = asyncio.create_task(old.medium.fade_out(duration=fade_out_dur))
        self._push_status({"transitioning": True, **old.get_status()})

        # Brief pause before starting new biome (let old start to thin)
        await asyncio.sleep(overlap_delay)

        # Phase 2: Start new ecosystem with silent medium, fade it in
        self.current = Ecosystem(new_biome, self.sc, start_silent=True, empty=self.empty)
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
        self._transitioning = False

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
        self._transitioning = False
        if self._run_task is not None:
            self._run_task.cancel()
            try:
                await self._run_task
            except asyncio.CancelledError:
                pass
        self.current = None
        self._limiter_node = None
        # Start fresh
        self._ensure_limiter()
        self.current = Ecosystem(biome, self.sc, empty=self.empty)
        self._run_task = asyncio.create_task(self.current.run())
        log.info("PANIC recovery complete — new biome seed=%d", biome.seed)

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
