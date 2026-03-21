# Sonic Ecosystem Engine

Procedural soundscape generation modeled as sonic ecosystems. Each biome is a self-organizing population of sound-producing agents sharing an acoustic medium. Biomes are generated deterministically from seeds, played live through SuperCollider, and cycled automatically with crossfade transitions.

## Requirements

- Python 3.11+
- [SuperCollider](https://supercollider.github.io/) (scsynth must be running)

## Setup

```bash
pip install -e .
```

### Boot SuperCollider

Open the SuperCollider IDE and run:

```supercollider
s.options.memSize = 65536;  // 64MB RT memory (needed for large reverbs)
s.boot;
```

Compiled SynthDefs are included in `synthdefs/compiled/`. If you need to recompile them (after editing `.scd` files), evaluate each file in the SC IDE:

- `synthdefs/sources.scd`
- `synthdefs/effects.scd`
- `synthdefs/medium.scd`

Then copy the results: `cp ~/Library/Application\ Support/SuperCollider/synthdefs/*.scsyndef synthdefs/compiled/`

## Usage

With scsynth running:

```bash
python main.py                    # 10 min per biome, random start
python main.py --seed 42          # start with a specific seed
python main.py --duration 300     # 5 min per biome
python main.py --ws-port 9000     # custom websocket port
```

Type `n` + Enter to skip to the next biome. Ctrl+C to shut down.

### Web Interface

Open `web/index.html` in a browser while the engine is running. The UI connects to the websocket server and shows:

- Current seed and macro DNA as visual bars
- Species breakdown — archetype, source, envelope type, effects, frequency range
- Medium parameters — room size, decay, wet mix, resonances
- Next/skip controls and seed input
- History of past biomes (click to replay)

No web server needed — it's a single HTML file that connects directly to the engine's websocket.

### Websocket API

A websocket server runs on port 8765 (configurable with `--ws-port`). Send JSON commands:

```json
{"cmd": "next"}              // skip to next random biome
{"cmd": "next", "seed": 42}  // skip to a specific seed
{"cmd": "info"}              // get current biome info
```

Biome changes are pushed to all connected clients as structured JSON with DNA, species, medium, and pitch set data.

## Architecture

Python holds all state, logic, and generation. scsynth is a pure audio renderer controlled over OSC. A biome is fully determined by its seed — same seed, same biome.

```
seed → Macro DNA → species derivation → agents + medium → scsynth
```

Each biome has:
- **Species** with distinct voice chains (source + source params → effects → panner)
- **Agents** with behavioral archetypes (caller, clicker, drone, swarm, responder)
- **A shared medium** (GVerb reverb, resonance, EQ, noise floor)
- **A depth model** controlling amplitude, spatial send, filter brightness, and behavior per agent
- **A size model** linking pitch register to tempo and amplitude (low = large/slow/loud, high = small/fast/quiet)

See [DESIGN.md](DESIGN.md) for the full design document.
