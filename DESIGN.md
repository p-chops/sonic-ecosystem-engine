# Sonic Ecosystem Engine — Design

## Vision

A system for procedurally generating and playing abstract soundscapes modeled as sonic ecosystems. Each "biome" is a self-organizing population of sound-producing agents sharing an acoustic medium. Biomes are generated deterministically from integer seeds and played live through SuperCollider.

The goal is not to simulate nature. It's to abstract the *structure* of natural soundscapes — populations, territories, flocking, spatial depth, ebb and flow — into a purely sonic framework that can produce environments ranging from alien jungles to nonexistent server rooms to places with no physical analog at all.

## Architecture

Python (asyncio) holds all state, logic, and generation. SuperCollider's `scsynth` is a pure audio renderer controlled over OSC. Python tells scsynth what to play; scsynth produces sound. No sclang in the runtime path.

```
seed → Macro DNA → species derivation → agents + medium → scsynth → audio
```

External control via websocket (port 8765) — accepts commands like "next biome", pushes live status and biome data to connected clients (web UI, Squeakbot, etc.).

## Biome Generation

A biome is fully determined by its seed. Same seed = same biome, always.

**Macro DNA** — five dimensions (0.0–1.0) drawn from the seed:

| Dimension | Low | High |
|-----------|-----|------|
| density | sparse, few agents | saturated, many agents |
| spectral_center | dark, low frequencies | bright, high frequencies |
| temporal | static, drones | rhythmic, transients |
| sociality | independent | interactive, flocking |
| room_scale | intimate, dry | vast, wet |

DNA drives everything downstream: species count, archetype weights, source selection, effect probabilities, medium parameters, pitch set strategy.

**Pitch sets** — each biome generates a shared set of frequencies (not constrained to named scales or equal temperament). Four strategies: equal division of an arbitrary interval, stacked ratios, harmonic series subsets, or random log-space distribution. All species draw from this shared pitch material.

## Species and Agents

Each species has a **voice chain** (source → effects → panner) and a **behavioral archetype**. Multiple agents of the same species run concurrently with per-agent variation in depth, pan, and timing.

**Sources**: sine (additive partials), noise (filtered), click (resonant impulse), FM, formant (parallel BPFs), granular, Karplus-Strong string. Each has per-species randomized parameters (e.g., FM ratio/index, formant frequencies, grain density). Four envelope shapes (perc, swell, symmetric, sustained) selected per-species by archetype-weighted randomness.

**Effects**: LPF, HPF, BPF, delay, wavefolder, ring mod, chorus. Each independently included/excluded with archetype-weighted probabilities (e.g., drones favor chorus/delay, clickers favor fold/ring).

**Archetypes**:
- **Caller** — phrases with rest periods, flocking-modulated timing. Size model links pitch register to tempo (low = slow, high = fast/quiet).
- **Clicker** — stochastic single impulses at independent tempos.
- **Drone** — sustained tones with slow spectral drift, pan wander, filter sweep, and reverb send modulation. Fades in/out smoothly.
- **Swarm** — high-density micro-events, density-coupled to activity.
- **Responder** — reactive, fires only when shared activity crosses a threshold.

## Depth Model

Each agent is assigned a depth (0.0 = close, 1.0 = far) at birth. Depth drives amplitude, medium send, LPF cutoff, behavior intensity, and activity weight. Close agents are loud, bright, and complex; far agents are quiet, dark, and simple. Distribution per species: sqrt (most far), uniform, or close (most near).

## Shared Medium

All agents send a portion of their signal to a shared medium bus. The medium applies resonance (formant filter bank), EQ, GVerb reverb (5–200m room, 0.5–30s decay, variable wet/dry), and a noise floor. A single persistent limiter on the main bus normalizes output across biomes.

## Ecosystem Loop

The ecosystem runs a tick-based loop: age agents, cull dead ones, spawn replacements (staggered, max 2 per tick), and decay the shared activity metric. Agents run as concurrent async tasks.

## Transitions

When advancing to a new biome, the system crossfades: old medium fades out over ~10s while agents die naturally, new medium fades in from silence over ~8s with staggered agent spawning. Drones fade in/out independently to avoid hard cuts.

## Conditions (Future)

The architecture supports time-varying modulations via `EcosystemState` — conditions would be additional writers to the same mutable state the ecosystem loop reads each tick. Planned types: gradients (dawn/dusk), events (disruptions), seasons (DNA drift over minutes), feedback rules (emergent macro-structure).
