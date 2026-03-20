# Sonic Ecosystem Engine — Implementation Plan

## Phase 1: Foundation — SC Bridge + SynthDefs ✓

- Implement `SCBridge` in `engine/bridge.py` (OSC client, node/bus allocation)
- Write and compile the SynthDef bank (`synthdefs/sources.scd`, `synthdefs/effects.scd`, `synthdefs/medium.scd`)
- Build `VoiceChain` in `engine/voice_chain.py`
- **Milestone**: manually fire notes through a voice chain from a Python REPL

## Phase 2: Agents + Archetypes ✓

- `Agent` base class + the 5 archetype behaviors (Caller, Clicker, Drone, Swarm, Responder)
- Shared activity metric + flocking logic
- Depth model (amp, send, LPF, behavior scaling)
- **Milestone**: spawn a handful of agents with hardcoded species, hear them interact

## Phase 3: Biome Generation ✓

- Macro DNA + seed-based RNG in `generation/dna.py`
- Species derivation rules in `generation/derive.py` (archetype selection, voice chain topology, param ranges)
- Pitch set generation (4 strategies) in `generation/tunings.py`
- Medium derivation
- **Milestone**: `generate_biome(seed)` returns a full `BiomeSpec`, reproducible from seed

## Phase 4: Ecosystem Loop + Medium ✓

- `EcosystemState` + `Ecosystem` main loop (age/cull/spawn/decay)
- `Medium` class — shared bus with reverb, resonance, EQ, noise floor, limiter
- Biome transitions (fade-out, overlap, staggered entry)
- **Milestone**: run a full biome end-to-end from a seed

## Phase 5: Continuous Runner

- `main.py` entry point — connect to scsynth, load synthdefs, run biomes continuously
- Auto-advance: configurable timer (e.g. 10–20 min per biome), generates a new random seed and transitions
- "Next biome" command: stdin listener or simple mechanism to skip to the next biome on demand
- Print seed + DNA summary on each biome change (so interesting seeds can be noted for later)
- **Milestone**: run for hours unattended, advancing through biomes; skip any biome with a single command

## Deferred

- **Curation database**: SQLite store for seeds, ratings, tags — not needed until there's a workflow for revisiting saved biomes
- **Squeakbot integration**: wire "next biome" (and future curation commands) to Twitch chat / channel points
- **Conditions layer**: time-varying modulations (gradients, events, seasons) per DESIGN.md

## Notes

- **Conditions layer**: architecture supports it via `EcosystemState` indirection, but not part of initial build.
- **Squeakbot path**: the "next biome" command is the same action whether triggered from stdin, a Twitch chat command, or a channel point redemption — just a different input source calling `manager.start_biome()`.
