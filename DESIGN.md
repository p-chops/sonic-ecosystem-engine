# Sonic Ecosystem Engine — Design Document

## Vision

A system for procedurally generating, playing, and curating abstract soundscapes modeled as sonic ecosystems. Each "biome" is a self-organizing population of sound-producing agents sharing an acoustic medium. The system generates biomes from seeds, plays them live through SuperCollider, and supports rapid curation — including "next biome" commands from Twitch chat via Squeakbot.

The goal is not to simulate nature. It's to abstract the *structure* of natural soundscapes — populations, territories, flocking, spatial depth, ebb and flow — into a purely sonic framework that can produce environments ranging from alien jungles to nonexistent server rooms to places with no physical analog at all.

## Architecture Overview

```
┌─────────────────────────────────────────────────┐
│  Python (brain)                                  │
│                                                  │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │  Biome   │  │  Agent   │  │  Curation     │  │
│  │Generator │→ │ Manager  │  │  Database     │  │
│  └──────────┘  └────┬─────┘  └───────────────┘  │
│                     │ OSC                        │
│  ┌──────────────────┼──────────────────────────┐ │
│  │  SC Bridge       │                          │ │
│  │  (python-osc)    │                          │ │
│  └──────────────────┼──────────────────────────┘ │
└─────────────────────┼───────────────────────────-┘
                      │ UDP :57110
┌─────────────────────┼───────────────────────────-┐
│  scsynth (ears)     │                            │
│                     ▼                            │
│  ┌──────────────────────────────────────────┐    │
│  │  SynthDef Bank (precompiled)             │    │
│  │  Sources: tone, noise, click, fm, ...    │    │
│  │  Effects: lpf, delay, fold, ring, ...    │    │
│  │  Room:    reverb, resonance, eq, ...     │    │
│  └──────────────────────────────────────────┘    │
│                                                  │
│  ┌──────────────────────────────────────────┐    │
│  │  Runtime node graph                      │    │
│  │  Groups → voice chains → shared medium   │    │
│  └──────────────────────────────────────────┘    │
│                        │                         │
│                        ▼ audio out               │
└──────────────────────────────────────────────────┘
                         │
                         ▼
                    OBS (capture)
```

Python holds all state, logic, and generation. scsynth is a pure audio renderer controlled over OSC. sclang is a development tool for authoring SynthDefs but is not in the runtime path.

## The SynthDef Bank

A small set of precompiled SynthDefs, divided into sources (signal generators) and effects (signal processors). Each is simple and focused. Timbral variety comes from parameterization and stacking, not from generating new SynthDefs.

### Sources

Each source writes to an output bus, applies its own envelope with `doneAction: 2` (self-freeing), and accepts standard parameters: `out`, `freq`, `amp`, `decay`.

| Name | Description | Key Parameters |
|------|-------------|----------------|
| `src_sine` | Pure sine, optional harmonics via additive partials | `n_partials`, `partial_spread` (inharmonicity), `partial_falloff` |
| `src_noise` | Filtered noise with variable bandwidth | `center_freq`, `bandwidth`, `noise_type` (white/pink/crackle/dust) |
| `src_click` | Short impulse through a resonant filter | `reson_freq`, `reson_q`, `impulse_type` (single/burst/dust) |
| `src_fm` | Two-operator FM | `ratio`, `index`, `index_env_amount` (how much index decays with envelope) |
| `src_formant` | Parallel bandpass filters for vowel/resonant body sounds | `formant_freqs` (array), `formant_qs`, `formant_amps` |
| `src_grain` | Micro-waveform granular | `grain_dur`, `grain_density`, `pitch_scatter`, `waveform` (sine/saw/noise) |
| `src_string` | Karplus-Strong plucked string | `brightness`, `damping`, `noise_mix` |

### Effects

Each effect reads from an input bus, processes the signal, and writes to an output bus. Effects are persistent — they run for the lifetime of the agent, not per-note. Standard parameters: `in`, `out`.

| Name | Description | Key Parameters |
|------|-------------|----------------|
| `fx_lpf` | Resonant low-pass filter | `cutoff`, `res` |
| `fx_hpf` | Resonant high-pass filter | `cutoff`, `res` |
| `fx_bpf` | Bandpass filter | `center`, `q` |
| `fx_delay` | Comb delay / feedback delay | `delay_time`, `feedback`, `mix` |
| `fx_fold` | Wavefolder / waveshaper | `drive`, `symmetry` |
| `fx_ring` | Ring modulator | `mod_freq`, `mod_depth` |
| `fx_chorus` | Chorus / detune / thicken | `rate`, `depth`, `voices` |
| `fx_pan_out` | Panner + output to main bus | `pan` |

### Voice Chains

A species voice is a source followed by zero or more effects, wired through audio buses. The chain is constructed at agent birth and persists for the agent's lifetime. Per-note vocalizations fire source synths into the head of the chain; effects process whatever arrives.

```
Agent Group
  ├─ [source synths fire here, self-free after envelope]
  ├─ fx_lpf (reads bus A, writes bus B)
  ├─ fx_fold (reads bus B, writes bus C)
  └─ fx_pan_out (reads bus C, writes main out / medium bus)
```

Stacking effects gives combinatorial timbral variety. With 7 sources and 8 effects (each optionally included), the topology space is `7 × 2^8 = 1,792` distinct signal chains, each with its own continuous parameter space.

### Shared Medium

The medium is an effect chain on a shared bus. All agents send some portion of their output to this bus (controlled by a per-agent `send` level). The medium processes the combined signal and outputs to the main bus.

A medium definition is a list of effect modules:

| Module | Role | Key Parameters |
|--------|------|----------------|
| `med_resonance` | Formant filter bank — the room's resonant character | `freqs`, `qs`, `amps` (array per resonance) |
| `med_reverb` | Spatial diffusion | `time`, `damping`, `mix` |
| `med_eq` | Spectral weather — slow-moving frequency response | `bands` (array of freq/gain/q), modulated over time |
| `med_noise_floor` | Ambient noise texture of the space itself | `level`, `color` (white→brown spectrum), `filter` |
| `med_limiter` | Carrying capacity — compresses when too many agents are active | `threshold`, `ratio` |

## Agent Archetypes

Behavioral templates that define *when and how* an agent vocalizes, independent of *what it sounds like* (which is determined by the voice chain). Each archetype is a Python class implementing a common interface.

### Archetype Definitions

**Caller** — Sings structured phrases with rest periods. Has a fixed "song" (note sequence) generated at birth, repeated with occasional transposition. Rest duration is subject to flocking dynamics. This is the generalized version of `~birdVoice` from the existing ecosystem patch.

- Parameters: `song_length`, `note_dur_range`, `note_gap`, `base_pause`, `glide_prob`, `transpose_prob`
- Social: flocking (rest compression when others are active)

**Clicker** — Emits single impulses at stochastic intervals. Independent, no social behavior. Each agent has its own tempo drawn at birth. This is the generalized `~creepVoice`.

- Parameters: `wait_range`, `rest_prob`, `chord_prob`, `chord_size`
- Social: none (polymetric texture from divergent clocks)

**Drone** — Sustains continuously with slow spectral drift. Does not use the standard percussive envelope; instead spawns a persistent source synth that evolves over time via `/n_set` parameter updates.

- Parameters: `drift_rate`, `drift_range`, `brightness_range`
- Social: optional inverse coupling (recedes when callers are active, emerges in silence)

**Swarm** — Many near-identical micro-events at high density. Functionally a clicker with very short wait times and very high population, but tuned for collective texture rather than individual events.

- Parameters: `density` (events/sec), `pitch_scatter`, `amp_scatter`
- Social: density-coupled (swarm thickens when activity is high, thins when low)

**Responder** — Only vocalizes in response to detected activity from other agents. Waits silently, monitoring `activity` level, and fires when it crosses a threshold. Like a predator call after commotion, or an echo/reply behavior.

- Parameters: `trigger_threshold`, `response_delay`, `cooldown`, `response_song_length`
- Social: reactive (listens to shared activity, never contributes to it)

### Common Agent Interface

```python
class Agent:
    def __init__(self, species, sc_bridge, medium_bus):
        self.alive = True
        self.age = 0
        self.max_age = random in species.age_range
        self.pos = random(-1.0, 1.0)  # pan position
        self.voice = VoiceChain(species.chain_spec, sc_bridge)
        self.behavior = species.archetype.create_behavior(self, species)

    async def run(self):
        """Main loop — delegates to archetype behavior."""
        await self.behavior.run()

    def die(self):
        self.alive = False
        self.voice.teardown()  # frees SC group + buses
```

## Biome Generation

A biome is fully determined by a seed. The generator uses hierarchical constrained randomness: macro DNA → species derivation → per-agent variation.

### Macro DNA

Five high-level dimensions, each a float from 0.0 to 1.0, drawn from the seed RNG:

| Dimension | 0.0 | 1.0 |
|-----------|-----|-----|
| `density` | sparse, few agents | saturated, many agents |
| `spectral_center` | dark, low-frequency dominated | bright, high-frequency dominated |
| `temporal` | static, drones and sustains | rhythmic, transients and pulses |
| `sociality` | independent, no interaction | highly interactive, strong flocking |
| `room_scale` | intimate, dry, close | vast, wet, distant |

### Derivation Rules

The macro DNA drives species composition through derivation functions. These encode aesthetic judgment — what combinations tend to sound good — and are the primary site for tuning the generator.

**Species count and archetype distribution:**

```python
def derive_species(dna, rng):
    n_species = int(lerp(2, 8, dna.density))

    # Archetype weights shift with DNA
    weights = {
        'caller':    dna.sociality * dna.temporal,
        'clicker':   dna.temporal * (1 - dna.sociality * 0.5),
        'drone':     (1 - dna.temporal),
        'swarm':     dna.density * dna.temporal * 0.5,
        'responder': dna.sociality * 0.3,
    }

    archetypes = weighted_sample(weights, n_species, rng)
    return [derive_single_species(arch, dna, rng) for arch in archetypes]
```

**Per-species derivation** assigns a voice chain and archetype parameters constrained by the DNA:

```python
def derive_single_species(archetype, dna, rng):
    # Pick a source — weighted by DNA
    source = rng.choice(SOURCES, weights={
        'src_sine':    1.0 - dna.temporal * 0.5,
        'src_noise':   dna.temporal * 0.5 + 0.2,
        'src_click':   dna.temporal,
        'src_fm':      0.5,
        'src_formant': 0.3,
        'src_grain':   dna.temporal * dna.density,
        'src_string':  dna.temporal * 0.4,
    })

    # Pick effects — each independently included/excluded
    effects = []
    if rng.random() < 0.6:
        effects.append(('fx_lpf', {
            'cutoff': lerp(200, 8000, dna.spectral_center + rng.gauss(0, 0.15))
        }))
    if rng.random() < 0.25:
        effects.append(('fx_fold', {
            'drive': lerp(1.1, 4.0, rng.random())
        }))
    if rng.random() < 0.3 * dna.room_scale:
        effects.append(('fx_delay', {
            'delay_time': lerp(0.01, 0.3, rng.random()),
            'feedback': lerp(0.1, 0.7, rng.random()),
        }))
    if rng.random() < 0.2:
        effects.append(('fx_ring', {
            'mod_freq': lerp(20, 2000, rng.random()),
        }))
    # ... etc for each effect

    # Frequency range — constrained by spectral_center
    freq_lo = lerp(40, 400, 1 - dna.spectral_center) * (1 + rng.gauss(0, 0.2))
    freq_hi = freq_lo * lerp(2, 8, dna.spectral_center + rng.random() * 0.3)

    # Population — constrained by density and archetype
    pop_base = ARCHETYPE_POP_RANGES[archetype]
    population = int(lerp(pop_base[0], pop_base[1], dna.density))

    return Species(
        archetype=archetype,
        source=source,
        effects=effects,
        freq_range=(freq_lo, freq_hi),
        population=population,
        # ... archetype-specific params derived similarly
    )
```

### Depth Model

Carried over from the existing ecosystem patch and generalized. Each agent within a species is assigned a depth value at birth (0.0 = close, 1.0 = far), drawn with a configurable distribution. Depth drives:

- **Amplitude**: close agents are louder (linear interpolation)
- **Medium send**: far agents send more signal to the shared medium bus (more reverb/diffusion)
- **LPF cutoff**: far agents are darker (exponential interpolation for perceptual linearity)
- **Behavior intensity**: far agents have shorter/simpler vocalizations, closer agents have more complex phrases
- **Activity weight**: far agents contribute less to shared activity metrics, preventing background density from overwhelming flocking dynamics

The depth distribution is a species-level parameter. A species with `depth_dist = 'sqrt'` (the current behavior) skews most agents far. A species with `depth_dist = 'uniform'` spreads them evenly. A species with `depth_dist = 'close'` clusters them in the foreground.

### Medium Generation

The medium is derived from `room_scale` and `spectral_center` in the DNA:

```python
def derive_medium(dna, rng):
    return MediumSpec(
        reverb_time=lerp(0.3, 12.0, dna.room_scale),
        reverb_damping=lerp(0.2, 0.8, 1 - dna.spectral_center),

        # Resonant frequencies — the "voice" of the room
        resonances=generate_resonances(
            n=int(lerp(2, 8, dna.room_scale)),
            center_hz=lerp(80, 2000, dna.spectral_center),
            spread_octaves=lerp(0.5, 3.0, dna.room_scale),
            rng=rng,
        ),

        noise_floor_level=lerp(-60, -25, dna.density * 0.4),
        noise_floor_color=lerp(0, 1, 1 - dna.spectral_center),  # 0=white, 1=brown

        # Carrying capacity
        limiter_threshold=lerp(-12, -3, 1 - dna.density),
    )
```

### Pitch Set Generation

A biome's pitch material is a **pitch set** — a plain list of frequencies in Hz. There is no constraint to named scales or equal temperaments. The generator produces pitch sets procedurally, and all species in the biome draw their note frequencies from this shared set (mapped into their own frequency range via octave transposition).

The generator selects a pitch set strategy and parameterizes it from the seed:

```python
def generate_pitch_set(dna, rng):
    """Returns a list of frequencies in Hz spanning one octave above a base frequency."""
    base_freq = lerp(60, 400, dna.spectral_center) * (1 + rng.gauss(0, 0.1))
    strategy = rng.choice(['equal_division', 'ratio_stack', 'harmonic', 'random_log'])

    if strategy == 'equal_division':
        # Divide an interval into N equal steps. The interval doesn't
        # have to be an octave — could be a tritave, a fifth, anything.
        n_divisions = rng.randint(5, 31)
        interval_ratio = lerp(1.5, 3.0, rng.random())  # 2.0 = octave
        return [base_freq * (interval_ratio ** (i / n_divisions))
                for i in range(n_divisions)]

    elif strategy == 'ratio_stack':
        # Stack arbitrary intervals. Each step is a ratio drawn from a range.
        n_notes = rng.randint(5, 19)
        freqs = [base_freq]
        for _ in range(n_notes - 1):
            ratio = lerp(1.02, 1.15, rng.random())  # microtonal to ~minor 2nd
            freqs.append(freqs[-1] * ratio)
        return freqs

    elif strategy == 'harmonic':
        # Select partials from the harmonic series with optional drift.
        n_partials = rng.randint(6, 16)
        partials = sorted(rng.sample(range(1, 25), n_partials))
        drift = rng.gauss(0, 0.01)  # slight inharmonicity
        return [base_freq * p * (1 + drift * rng.gauss(0, 1))
                for p in partials]

    elif strategy == 'random_log':
        # Frequencies spaced randomly in log space (perceptually random pitch).
        n_notes = rng.randint(5, 20)
        log_lo = math.log2(base_freq)
        log_hi = math.log2(base_freq * lerp(2, 4, rng.random()))
        log_freqs = sorted([rng.uniform(log_lo, log_hi) for _ in range(n_notes)])
        return [2 ** lf for lf in log_freqs]
```

Species map into the pitch set by filtering it to their frequency range and optionally transposing by octaves. Two species in the same biome share the same intervallic relationships but may occupy completely different registers.

Two biomes with identical macro DNA but different pitch sets sound like completely different worlds — this is one of the most powerful differentiators in the generator.

## Population Management

A direct port of the `~startEcosystem` pattern from the existing SC patch, generalized to handle multiple species simultaneously.

### Mutable Ecosystem State

All live parameters are held in an `EcosystemState` object that the ecosystem loop reads each tick. This indirection is what makes future conditions possible — anything that can write to `EcosystemState` can modulate the ecosystem. For now, the generator writes the initial state and nothing else changes it. Later, conditions become additional writers.

```python
class EcosystemState:
    """Mutable runtime state. The single source of truth for all live parameters.
    The biome generator writes initial values. Conditions (future) can modify them.
    The ecosystem loop reads them each tick."""

    def __init__(self, biome_spec):
        # Per-species targets (mutable — conditions can adjust these)
        self.species_targets = {
            sp: sp.population for sp in biome_spec.species
        }
        # Medium parameters (mutable — conditions can modulate these)
        self.medium_params = dict(biome_spec.medium_spec)
        # Shared activity metric
        self.activity = 0.0
        # Global modifiers
        self.activity_decay = 0.6  # lose 40% per tick
        self.tick_interval = 3.0

    def get_population_target(self, species):
        return self.species_targets[species]
```

### Ecosystem Loop

```python
class Ecosystem:
    def __init__(self, biome_spec, sc_bridge):
        self.state = EcosystemState(biome_spec)
        self.species = biome_spec.species
        self.medium = Medium(biome_spec.medium_spec, sc_bridge)
        self.agents = []
        self.sc = sc_bridge
        self.alive = True

    async def run(self):
        while self.alive:
            self.age_and_cull()
            self.spawn_to_targets()
            self.decay_activity()
            self.medium.sync_params(self.state.medium_params)
            await asyncio.sleep(self.state.tick_interval)

    def age_and_cull(self):
        for agent in self.agents:
            agent.age += 1
            if agent.age >= agent.max_age:
                agent.die()
        self.agents = [a for a in self.agents if a.alive]

    def spawn_to_targets(self):
        for species in self.species:
            target = self.state.get_population_target(species)
            current = sum(1 for a in self.agents if a.species == species)
            while current < target:
                agent = Agent(species, self.sc, self.medium.bus)
                self.agents.append(agent)
                asyncio.create_task(agent.run())
                current += 1

    def decay_activity(self):
        self.state.activity *= self.state.activity_decay
```

### Flocking

The flocking/fatigue system from the existing patch is preserved as a behavior modifier available to any archetype. The shared `activity` value accumulates as agents vocalize (weighted by depth) and decays each tick. Archetypes that opt into flocking compress their rest pauses when activity is moderate and extend them when activity exceeds the fatigue threshold. Background agents (high depth, zero activity weight) are immune — they maintain a steady rhythm independent of foreground dynamics.

## Conditions Layer (Deferred)

Conditions are time-varying modulations applied to the ecosystem — gradients, events, seasons, feedback rules. They are **not part of the initial build** but the architecture is designed to support them cleanly when the time comes.

### Why Conditions Can Be Deferred

Conditions operate *on top of* the ecosystem, not inside it. They modulate parameters that the ecosystem already exposes: species population targets, medium filter cutoffs, activity thresholds, vocalization rates. They are consumers of the same interface the biome generator uses to configure the ecosystem at creation time.

The only architectural requirement for future conditions support is that **ecosystem parameters must be mutable at runtime** — conditions need to be able to adjust population targets, medium settings, and archetype behavior while the ecosystem is running. This is handled by the `EcosystemState` object (see Population Management), which stores all live parameters in a mutable structure that the ecosystem loop reads each tick. As long as this indirection exists, conditions are just another writer to that state, and can be grafted on without refactoring the core.

### Planned Condition Types (for future reference)

**Gradient** — Slow ramp of parameters over a duration. "Dawn" wakes species in sequence, brightens the medium, increases vocalization rates. "Dusk" is the reverse.

**Event** — Discrete disruption. Sudden silence, spectral flood in a band, "predator" call after peak activity.

**Season** — Long arc (minutes) that shifts the biome's macro DNA, causing newly born agents to differ from older ones while existing agents keep their birth parameters.

**Feedback Rule** — Responds to ecosystem state. "If total energy exceeds X for Y seconds, trigger a culling event." Creates emergent macro-structure.

**Condition Sequencing** — An ordered list of conditions with timing, functioning as a loose score for a set. Can also be omitted for static biomes, or triggered manually / from Twitch chat.

## Curation System

### Seed-Based Generation

Every biome is deterministic from its seed. The seed controls:
1. Macro DNA values
2. Pitch set generation (strategy + parameters)
3. Species count and archetype selection
4. Per-species voice chain topology and parameters
5. Per-species behavioral parameters
6. Medium parameters

Same seed = same biome, always. This enables replay, sharing, and database storage.

### Curation Database

A SQLite database (or JSON file) storing:

```
biome_seeds
  - seed (integer, primary key)
  - dna_density (float)
  - dna_spectral_center (float)
  - dna_temporal (float)
  - dna_sociality (float)
  - dna_room_scale (float)
  - pitch_set_strategy (string)  -- equal_division, ratio_stack, harmonic, random_log
  - n_species (integer)
  - rating (integer, nullable)  -- user rating 1-5
  - tags (text, nullable)       -- user tags, comma-separated
  - notes (text, nullable)      -- free-form user notes
  - created_at (timestamp)
  - listen_duration_sec (float) -- how long it played before skip/rate
```

### Curation Workflow

The primary curation mode is live: biomes generate and play in sequence. The user (or Twitch chat) can:

- **Next**: stop current biome, generate and start a new one from a fresh seed
- **Rate**: assign a 1-5 rating to the current biome (also saves to DB)
- **Tag**: add tags ("dark", "rhythmic", "favorite", "set-worthy")
- **Hold**: prevent auto-advance, keep current biome running
- **Replay**: regenerate a biome from a saved seed

These commands integrate with Squeakbot as Twitch channel point redemptions or chat commands, making the audience part of the curation process.

### Biome Transitions

When advancing to a new biome ("next"), the transition is not a hard cut. The system:

1. Begins fading out the current medium (reverb tail extends, noise floor rises)
2. Stops spawning new agents for all current species (population naturally declines as agents die)
3. After a brief overlap, tears down remaining current agents
4. Constructs the new medium
5. Begins spawning new biome's agents with staggered entry

This produces a natural-feeling dissolve where the old ecosystem fades and the new one emerges, rather than an abrupt switch.

## Python ↔ SuperCollider Bridge

### OSC Communication

Python communicates with scsynth over UDP on port 57110 using `python-osc`. A thin wrapper provides ergonomic methods:

```python
class SCBridge:
    def __init__(self, host="127.0.0.1", port=57110):
        self.client = SimpleUDPClient(host, port)
        self.next_node_id = 2000
        self.next_bus_id = 16  # buses 0-15 reserved

    def synth(self, name, target_group=None, add_action=0, **params):
        node_id = self._alloc_node_id()
        args = []
        for k, v in params.items():
            args.extend([k, float(v)])
        target = target_group or 1  # default group
        self.client.send_message("/s_new",
            [name, node_id, add_action, target] + args)
        return node_id

    def set(self, node_id, **params):
        args = [node_id]
        for k, v in params.items():
            args.extend([k, float(v)])
        self.client.send_message("/n_set", args)

    def free(self, node_id):
        self.client.send_message("/n_free", [node_id])

    def new_group(self, target=1, add_action=0):
        group_id = self._alloc_node_id()
        self.client.send_message("/g_new", [group_id, add_action, target])
        return group_id

    def alloc_bus(self, channels=1):
        bus_id = self.next_bus_id
        self.next_bus_id += channels
        return bus_id

    def free_bus(self, bus_id):
        pass  # bus IDs can be recycled with a pool allocator
```

### Voice Chain Construction

```python
class VoiceChain:
    def __init__(self, chain_spec, sc, medium_bus):
        self.sc = sc
        self.group = sc.new_group()
        self.buses = []
        self.effect_nodes = []

        # Allocate buses for the chain
        prev_bus = sc.alloc_bus()
        self.input_bus = prev_bus
        self.buses.append(prev_bus)

        for fx_name, fx_params in chain_spec['effects']:
            next_bus = sc.alloc_bus()
            self.buses.append(next_bus)
            node = sc.synth(fx_name, target_group=self.group,
                            add_action=1,  # add to tail
                            **{'in': prev_bus, 'out': next_bus},
                            **fx_params)
            self.effect_nodes.append(node)
            prev_bus = next_bus

        # Final output — pan and send to main + medium bus
        self.output_node = sc.synth('fx_pan_out',
            target_group=self.group, add_action=1,
            **{'in': prev_bus}, pan=chain_spec.get('pan', 0))

    def vocalize(self, source_def, **note_params):
        """Fire a note into the chain. Source self-frees via doneAction: 2."""
        self.sc.synth(source_def, target_group=self.group,
                      add_action=0,  # add to head (before effects)
                      out=self.input_bus, **note_params)

    def teardown(self):
        self.sc.free(self.group)  # frees all synths in group
        for bus in self.buses:
            self.sc.free_bus(bus)
```

### Timing

Python's `asyncio.sleep()` is adequate for ecosystem-level timing (agent rest pauses, population management ticks) where jitter of ±10ms is inaudible. For note-level timing within songs (gaps of 5–20ms between notes in a caller's phrase), the system pre-computes the full song as an OSC bundle with server-side timestamps and sends it in one packet. scsynth executes the notes with sample-accurate timing.

```python
from pythonosc.osc_bundle_builder import OscBundleBuilder, IMMEDIATELY
from pythonosc.osc_message_builder import OscMessageBuilder
import time

def send_song_bundle(sc, voice_chain, song, transpose=1.0):
    bundle = OscBundleBuilder(IMMEDIATELY)
    t = time.time()

    for note in song:
        msg = OscMessageBuilder(address="/s_new")
        msg.add_arg(voice_chain.source_def)
        msg.add_arg(sc._alloc_node_id())
        msg.add_arg(0)  # add to head
        msg.add_arg(voice_chain.group)
        msg.add_arg("out"); msg.add_arg(float(voice_chain.input_bus))
        msg.add_arg("freq"); msg.add_arg(float(note['freq'] * transpose))
        msg.add_arg("decay"); msg.add_arg(float(note['dur']))
        msg.add_arg("amp"); msg.add_arg(float(note['amp']))
        # ... other params

        sub_bundle = OscBundleBuilder(t)
        sub_bundle.add_content(msg.build())
        bundle.add_content(sub_bundle.build())

        t += note['dur'] + note['gap']

    sc.client.send(bundle.build())
```

## Squeakbot Integration

The ecosystem engine runs as an async service within Squeakbot (or as a standalone process that Squeakbot communicates with). Twitch chat commands and channel point redemptions map to ecosystem actions:

| Command / Redemption | Action |
|---------------------|--------|
| `!nextbiome` | Stop current biome, generate and start new one |
| `!rate <1-5>` | Rate current biome, save to curation DB |
| `!tag <tags>` | Tag current biome |
| `!hold` | Prevent auto-advance |
| `!replay <seed>` | Regenerate a specific biome by seed |
| `!biomeinfo` | Post current biome's seed + macro DNA summary to chat |
| `!event <type>` | Trigger a condition event (storm, silence, etc.) |

Auto-advance is optional: the system can be configured to automatically generate a new biome after a set duration (e.g., every 10–20 minutes) unless held.

## File Structure

```
sonic-ecosystem-engine/
├── DESIGN.md                   # this document
├── engine/
│   ├── __init__.py
│   ├── bridge.py               # SCBridge — OSC communication layer
│   ├── voice_chain.py          # VoiceChain — per-agent signal chain management
│   ├── agent.py                # Agent base class
│   ├── archetypes/
│   │   ├── __init__.py
│   │   ├── caller.py
│   │   ├── clicker.py
│   │   ├── drone.py
│   │   ├── swarm.py
│   │   └── responder.py
│   ├── medium.py               # Medium — shared acoustic environment
│   ├── ecosystem.py            # Ecosystem — population manager + main loop
│   └── conditions.py           # Condition types (gradient, event, season, feedback)
├── generation/
│   ├── __init__.py
│   ├── dna.py                  # Macro DNA definition + random drawing
│   ├── derive.py               # Derivation rules (DNA → species + medium)
│   ├── tunings.py              # Tuning system library
│   └── species.py              # Species dataclass
├── curation/
│   ├── __init__.py
│   ├── database.py             # SQLite curation store
│   └── commands.py             # Curation command handlers
├── synthdefs/
│   ├── sources.scd             # Source SynthDef definitions (compile with sclang)
│   ├── effects.scd             # Effect SynthDef definitions
│   ├── medium.scd              # Medium SynthDef definitions
│   └── compiled/               # .scsyndef binaries (loaded by scsynth at boot)
├── config/
│   └── defaults.yaml           # Default parameter ranges, derivation weights
└── main.py                     # Entry point — boots scsynth, starts ecosystem loop
```
