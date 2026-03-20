# Sonic Ecosystem Engine

Procedural soundscape generation modeled as sonic ecosystems. Each biome is a self-organizing population of sound-producing agents sharing an acoustic medium. Biomes are generated deterministically from seeds, played live through SuperCollider, and cycled automatically with crossfade transitions.

## Requirements

- Python 3.11+
- [SuperCollider](https://supercollider.github.io/) (scsynth must be running)

## Setup

```bash
pip install -e .
```

### Compile SynthDefs

Open SuperCollider IDE, boot the server (`s.boot`), then evaluate each file:

- `synthdefs/sources.scd`
- `synthdefs/effects.scd`
- `synthdefs/medium.scd`

This compiles the SynthDefs and stores them via `.store`.

## Usage

With scsynth running:

```bash
python main.py                    # 10 min per biome, random start
python main.py --seed 42          # start with a specific seed
python main.py --duration 300     # 5 min per biome
```

Type `n` + Enter to skip to the next biome. Ctrl+C to shut down.

### Websocket Control

A websocket server runs on port 8765 (configurable with `--ws-port`). Send JSON commands:

```json
{"cmd": "next"}              // skip to next random biome
{"cmd": "next", "seed": 42}  // skip to a specific seed
{"cmd": "info"}              // get current biome info
```

Biome changes are pushed to all connected clients as `{"event": "biome_change", "seed": ..., "summary": ...}`.

## Architecture

Python holds all state, logic, and generation. scsynth is a pure audio renderer controlled over OSC. A biome is fully determined by its seed — same seed, same biome.

```
seed → Macro DNA → species derivation → agents + medium → scsynth
```

Each biome has:
- **Species** with distinct voice chains (source → effects → panner)
- **Agents** with behavioral archetypes (caller, clicker, drone, swarm, responder)
- **A shared medium** (reverb, resonance, EQ, noise floor, limiter)
- **A depth model** controlling amplitude, spatial send, and brightness per agent

See [DESIGN.md](DESIGN.md) for the full design document.
