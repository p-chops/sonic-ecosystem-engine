"""Derivation rules — DNA → species list + medium spec.

This is the primary site for tuning the generator. The derivation functions
encode aesthetic judgment about what combinations tend to sound good.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from engine.voice_chain import ChainSpec
from engine.species import Species
from generation.dna import MacroDNA
from generation.tunings import generate_pitch_set


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * max(0.0, min(1.0, t))


# -- Source weights by DNA ----------------------------------------------------

SOURCE_WEIGHTS = {
    "src_sine":    lambda dna: 1.0 - dna.temporal * 0.5,
    "src_noise":   lambda dna: dna.temporal * 0.5 + 0.2,
    "src_click":   lambda dna: dna.temporal,
    "src_fm":      lambda dna: 0.5,
    "src_formant": lambda dna: 0.3,
    "src_grain":   lambda dna: dna.temporal * dna.density,
    "src_string":  lambda dna: dna.temporal * 0.4,
}

# -- Archetype population ranges (min, max agents) ----------------------------

ARCHETYPE_POP_RANGES = {
    "caller":    (3, 8),
    "clicker":   (4, 10),
    "drone":     (2, 4),
    "swarm":     (3, 8),
    "responder": (1, 3),
}

# -- Archetype age ranges (min_ticks, max_ticks) ------------------------------

ARCHETYPE_AGE_RANGES = {
    "caller":    (15, 40),
    "clicker":   (12, 30),
    "drone":     (25, 60),
    "swarm":     (10, 25),
    "responder": (20, 50),
}

# -- Depth distribution tendencies by archetype --------------------------------

ARCHETYPE_DEPTH_DIST = {
    "caller":    "sqrt",     # mostly background, some foreground
    "clicker":   "sqrt",
    "drone":     "uniform",  # spread evenly
    "swarm":     "sqrt",
    "responder": "close",    # tend foreground
}


# -- Medium spec ---------------------------------------------------------------

@dataclass
class Resonance:
    freq: float
    q: float
    amp: float


@dataclass
class MediumSpec:
    reverb_roomsize: float  # meters
    reverb_time: float      # seconds
    reverb_damping: float
    reverb_mix: float       # 0=dry, 1=fully wet
    resonances: list[Resonance]
    noise_floor_level: float   # dB
    noise_floor_color: float   # 0=white, 1=brown
    limiter_threshold: float   # dB


def _generate_resonances(
    n: int,
    center_hz: float,
    spread_octaves: float,
    rng: random.Random,
) -> list[Resonance]:
    """Generate n resonant frequencies spread around a center."""
    resonances = []
    for i in range(n):
        # Spread in log space
        offset = rng.uniform(-spread_octaves / 2, spread_octaves / 2)
        freq = center_hz * (2 ** offset)
        freq = max(40, min(freq, 3000))  # cap to avoid high-pitched ringing
        q = rng.uniform(5, 20)          # lower max Q to reduce ring duration
        amp = lerp(1.0, 0.2, i / max(n - 1, 1))  # earlier resonances louder
        resonances.append(Resonance(freq=freq, q=q, amp=amp))
    return resonances


def derive_medium(dna: MacroDNA, rng: random.Random) -> MediumSpec:
    """Derive medium parameters from DNA."""
    n_resonances = int(lerp(2, 6, dna.room_scale))
    return MediumSpec(
        reverb_roomsize=lerp(5, 200, dna.room_scale ** 1.5),  # meters — 5m closet to 200m cathedral
        reverb_time=lerp(0.5, 30.0, dna.room_scale ** 1.5),  # seconds — short to very long tail
        reverb_damping=lerp(0.2, 0.8, 1 - dna.spectral_center),
        reverb_mix=lerp(0.4, 0.95, dna.room_scale),  # intimate=mostly dry, vast=almost fully wet
        resonances=_generate_resonances(
            n=n_resonances,
            center_hz=lerp(80, 2000, dna.spectral_center),
            spread_octaves=lerp(0.5, 3.0, dna.room_scale),
            rng=rng,
        ),
        noise_floor_level=lerp(-60, -25, dna.density * 0.4),
        noise_floor_color=lerp(0, 1, 1 - dna.spectral_center),
        limiter_threshold=-6,  # fixed — gain staging handles density, limiter is a safety net
    )


# -- Source selection ----------------------------------------------------------

def _weighted_choice(weights: dict[str, float], rng: random.Random) -> str:
    """Choose a key from a dict of {name: weight}."""
    items = list(weights.items())
    names = [n for n, _ in items]
    wts = [max(w, 0.01) for _, w in items]  # floor to avoid zero weights
    return rng.choices(names, weights=wts, k=1)[0]


def _weighted_sample(weights: dict[str, float], k: int, rng: random.Random) -> list[str]:
    """Sample k items (with replacement) from weighted dict."""
    items = list(weights.items())
    names = [n for n, _ in items]
    wts = [max(w, 0.01) for _, w in items]
    return rng.choices(names, weights=wts, k=k)


# -- Effect chain derivation ---------------------------------------------------

# Archetype-weighted effect probability multipliers.
# >1.0 increases chance, <1.0 decreases. Unlisted effects default to 1.0.
ARCHETYPE_EFFECT_MULTS: dict[str, dict[str, float]] = {
    "caller": {
        "fx_delay": 1.5,    # spatial interest on phrases
        "fx_chorus": 1.3,   # gentle thickening
        "fx_fold": 0.5,     # preserve phrase clarity
    },
    "clicker": {
        "fx_fold": 2.0,     # transient coloring
        "fx_ring": 1.5,     # metallic character
        "fx_bpf": 1.5,      # resonant ping
        "fx_chorus": 0.3,   # doesn't help short impulses
    },
    "drone": {
        "fx_chorus": 2.0,   # thickening
        "fx_delay": 1.5,    # depth and movement
        "fx_fold": 0.3,     # distortion fights sustained tones
        "fx_ring": 0.5,     # same reason
    },
    "swarm": {
        "fx_chorus": 1.5,   # density
    },
    "responder": {
        "fx_delay": 1.5,    # dramatic echo
        "fx_fold": 1.3,     # rare species, should stand out
    },
}


def _derive_effects(dna: MacroDNA, rng: random.Random, archetype: str,
                    source: str = "") -> list[tuple[str, dict]]:
    """Derive an effect chain from DNA, weighted by archetype."""
    effects = []
    mults = ARCHETYPE_EFFECT_MULTS.get(archetype, {})

    if rng.random() < min(0.6 * mults.get("fx_lpf", 1.0), 0.95):
        cutoff_t = max(0, min(1, dna.spectral_center + rng.gauss(0, 0.15)))
        effects.append(("fx_lpf", {
            "cutoff": lerp(200, 8000, cutoff_t),
            "res": rng.uniform(0.0, 0.5),
        }))

    if rng.random() < min(0.3 * mults.get("fx_hpf", 1.0), 0.95):
        effects.append(("fx_hpf", {
            "cutoff": lerp(40, 800, rng.random()),
            "res": rng.uniform(0.0, 0.3),
        }))

    if rng.random() < min(0.15 * mults.get("fx_bpf", 1.0), 0.95):
        effects.append(("fx_bpf", {
            "center": lerp(200, 4000, dna.spectral_center + rng.gauss(0, 0.2)),
            "q": rng.uniform(1, 10),
        }))

    if rng.random() < min(0.25 * mults.get("fx_fold", 1.0), 0.95):
        effects.append(("fx_fold", {
            "drive": lerp(1.1, 4.0, rng.random()),
            "symmetry": rng.uniform(0, 0.5),
        }))

    if rng.random() < min(0.3 * dna.room_scale * mults.get("fx_delay", 1.0), 0.95):
        effects.append(("fx_delay", {
            "delay_time": lerp(0.01, 0.3, rng.random()),
            "feedback": lerp(0.1, 0.7, rng.random()),
            "mix": lerp(0.2, 0.6, rng.random()),
        }))

    if rng.random() < min(0.2 * mults.get("fx_ring", 1.0), 0.95):
        effects.append(("fx_ring", {
            "mod_freq": lerp(20, 800, rng.random()),  # cap to avoid harsh high sidebands
            "mod_depth": rng.uniform(0.3, 0.8),
        }))

    if rng.random() < min(0.2 * mults.get("fx_chorus", 1.0), 0.95):
        effects.append(("fx_chorus", {
            "rate": rng.uniform(0.1, 1.0),
            "depth": rng.uniform(0.001, 0.008),
            "voices": rng.randint(2, 4),
        }))

    # Sine sources must have at least one modulation effect to avoid dullness
    if source == "src_sine" and not any(name in ("fx_chorus", "fx_delay", "fx_ring", "fx_fold")
                                        for name, _ in effects):
        # Guarantee chorus — natural thickening for sine
        effects.append(("fx_chorus", {
            "rate": rng.uniform(0.1, 0.8),
            "depth": rng.uniform(0.002, 0.008),
            "voices": rng.randint(2, 4),
        }))

    return effects


# -- Archetype-specific parameter derivation -----------------------------------

def _derive_caller_params(dna: MacroDNA, rng: random.Random, size: float = 0.5) -> dict:
    """Derive caller behavior params. size: 0=small/high/fast, 1=large/low/slow."""
    return {
        # Small callers: more notes, chattery. Large callers: fewer notes, deliberate.
        "song_length": rng.randint(
            int(lerp(8, 4, size)),
            int(lerp(16, 10, size)),
        ),
        # Small: short notes. Large: long sustained notes.
        "note_dur_range": (
            lerp(0.02, 0.08, size),
            lerp(0.08, 0.5, size),
        ),
        # Small: tight gaps. Large: wide gaps.
        "note_gap": (
            lerp(0.005, 0.02, size),
            lerp(0.02, 0.12, size),
        ),
        # Small: short rests. Large: long rests.
        "base_pause": (
            lerp(0.3, 1.2, size),
            lerp(1.5, 6.0, size),
        ),
        "glide_prob": lerp(0.05, 0.4, rng.random()),
        "transpose_prob": lerp(0.05, 0.3, rng.random()),
        "fatigue_threshold": lerp(3.0, 8.0, 1 - dna.sociality),
        # Pass size through so the agent can use it for amplitude
        "size": size,
    }


def _derive_clicker_params(dna: MacroDNA, rng: random.Random) -> dict:
    return {
        "wait_range": (
            lerp(0.1, 0.5, dna.temporal),
            lerp(1.0, 4.0, 1 - dna.temporal),
        ),
        "rest_prob": lerp(0.05, 0.3, 1 - dna.temporal),
        "chord_prob": lerp(0.02, 0.15, dna.density),
        "chord_size": (2, int(lerp(2, 5, dna.density))),
    }


def _derive_drone_params(dna: MacroDNA, rng: random.Random) -> dict:
    return {
        "drift_rate": (
            lerp(8.0, 15.0, dna.temporal),
            lerp(15.0, 30.0, 1 - dna.temporal),
        ),
        "drift_range": lerp(0.005, 0.03, rng.random()),  # microtonal — barely perceptible
        "inverse_coupling": dna.sociality > 0.3,
        # Pan wander
        "pan_drift_rate": rng.uniform(0.02, 0.15),  # Hz — very slow LFO
        "pan_drift_range": rng.uniform(0.3, 0.9),    # how wide the pan sweeps
        # Medium send wander — drones breathe in and out of the reverb
        "send_drift_rate": rng.uniform(0.01, 0.08),
        "send_lo": rng.uniform(0.3, 0.5),
        "send_hi": rng.uniform(0.7, 1.0),
        # Filter sweep — slow spectral movement
        "filter_drift_rate": rng.uniform(0.01, 0.1),
        "filter_lo": lerp(300, 800, rng.random()),
        "filter_hi": lerp(2000, 8000, rng.random()),
    }


def _derive_swarm_params(dna: MacroDNA, rng: random.Random) -> dict:
    return {
        "density": lerp(5, 40, dna.density * dna.temporal),
        "pitch_scatter": lerp(0.02, 0.2, rng.random()),
        "amp_scatter": lerp(0.1, 0.5, rng.random()),
    }


def _derive_responder_params(dna: MacroDNA, rng: random.Random) -> dict:
    return {
        "trigger_threshold": lerp(1.0, 4.0, 1 - dna.sociality),
        "response_delay": (
            lerp(0.1, 0.3, dna.temporal),
            lerp(0.5, 1.5, 1 - dna.temporal),
        ),
        "cooldown": (
            lerp(2.0, 5.0, dna.temporal),
            lerp(5.0, 12.0, 1 - dna.temporal),
        ),
        "response_song_length": rng.randint(2, int(lerp(3, 7, dna.temporal))),
    }


_ARCHETYPE_PARAM_DERIVERS = {
    "caller": _derive_caller_params,
    "clicker": _derive_clicker_params,
    "drone": _derive_drone_params,
    "swarm": _derive_swarm_params,
    "responder": _derive_responder_params,
}


# -- Source parameter derivation -----------------------------------------------

# Archetype-weighted envelope type selection.
# [perc, swell, symmetric, sustained]
_ARCHETYPE_ENV_WEIGHTS: dict[str, list[float]] = {
    "caller":    [3, 2, 2, 1],   # mix of all, favoring perc
    "clicker":   [5, 0.5, 0.5, 0.5],  # strongly perc
    "drone":     [0.5, 3, 1, 3],  # swell and sustained
    "swarm":     [5, 0.5, 1, 0.5],  # strongly perc
    "responder": [1, 4, 2, 1],   # swell for dramatic entries
}


def _derive_source_params(source: str, dna: MacroDNA, rng: random.Random,
                          archetype: str = "caller") -> dict:
    """Derive source-specific synth parameters. These define the species' timbre."""

    # Envelope type — archetype-weighted
    env_weights = _ARCHETYPE_ENV_WEIGHTS.get(archetype, [1, 1, 1, 1])
    env_type = rng.choices([0, 1, 2, 3], weights=env_weights, k=1)[0]

    if source == "src_sine":
        # Drones: fewer partials, steeper falloff — avoid sustained high-freq tinnitus
        if archetype == "drone":
            n_partials = rng.choice([2, 3, 4])
            falloff = rng.uniform(0.3, 0.6)
        else:
            n_partials = rng.choice([2, 3, 4, 5, 6])
            falloff = rng.uniform(0.3, 0.7)
        return {
            "env_type": env_type,
            "n_partials": n_partials,
            "partial_spread": rng.uniform(0.05, 0.4),
            "partial_falloff": falloff,
        }

    elif source == "src_fm":
        # Ratio defines the harmonic character; integer ratios = harmonic,
        # non-integer = inharmonic/metallic
        ratio_type = rng.choice(["harmonic", "harmonic", "inharmonic"])
        if ratio_type == "harmonic":
            ratio = rng.choice([1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0])
        else:
            ratio = rng.uniform(1.1, 7.0)
        return {
            "env_type": env_type,
            "ratio": ratio,
            "index": rng.uniform(0.5, 12.0),
            "index_env_amount": rng.uniform(0.0, 1.0),
        }

    elif source == "src_noise":
        return {
            "env_type": env_type,
            "noise_type": rng.choice([0, 0, 1, 1, 2, 3]),  # white, pink more common
            "bandwidth": rng.uniform(100, 2000),
        }

    elif source == "src_click":
        return {
            "env_type": env_type,
            "impulse_type": rng.choice([0, 0, 1, 2]),
            "reson_q": rng.uniform(2, 25),  # cap Q to avoid sustained ringing
        }

    elif source == "src_formant":
        # Generate random formant frequencies — vowel-like but alien
        base = rng.uniform(200, 1200)
        return {
            "env_type": env_type,
            "f1": base,
            "f2": base * rng.uniform(1.2, 2.5),
            "f3": base * rng.uniform(2.0, 5.0),
            "f4": base * rng.uniform(3.5, 8.0),
            "f5": base * rng.uniform(5.0, 12.0),
            "q1": rng.uniform(8, 40),
            "q2": rng.uniform(8, 40),
            "q3": rng.uniform(8, 35),
            "q4": rng.uniform(8, 30),
            "q5": rng.uniform(8, 25),
            "a1": 1.0,
            "a2": rng.uniform(0.4, 1.0),
            "a3": rng.uniform(0.2, 0.8),
            "a4": rng.uniform(0.0, 0.5),
            "a5": rng.uniform(0.0, 0.3),
        }

    elif source == "src_grain":
        return {
            "env_type": env_type,
            "grain_dur": rng.uniform(0.005, 0.06),
            "grain_density": rng.uniform(5, 60),
            "pitch_scatter": rng.uniform(0.0, 0.5),
            "waveform": rng.choice([0, 0, 1, 2]),  # sine most common
        }

    elif source == "src_string":
        # src_string uses its own linen envelope, no env_type
        return {
            "brightness": rng.uniform(0.1, 0.9),
            "damping": rng.uniform(0.1, 0.8),
            "noise_mix": rng.uniform(0.0, 0.4),
        }

    return {"env_type": env_type}


# -- Species derivation --------------------------------------------------------

def _derive_single_species(
    archetype: str,
    index: int,
    dna: MacroDNA,
    pitch_set: list[float],
    rng: random.Random,
) -> Species:
    """Derive a single species from DNA and archetype."""
    # Source selection — filter out incompatible sources per archetype
    source_weights = {name: fn(dna) for name, fn in SOURCE_WEIGHTS.items()}
    if archetype == "drone":
        # Click and grain sources make no sense as sustained drones
        source_weights.pop("src_click", None)
        source_weights.pop("src_grain", None)
    source = _weighted_choice(source_weights, rng)

    # Source-specific parameters (the species' timbral identity)
    source_params = _derive_source_params(source, dna, rng, archetype=archetype)

    # Effect chain
    effects = _derive_effects(dna, rng, archetype, source=source)

    # Frequency range — drones are pushed low, capped to avoid tinnitus
    if archetype == "drone":
        freq_lo = lerp(30, 100, 1 - dna.spectral_center) * (1 + rng.gauss(0, 0.1))
        freq_lo = max(20, freq_lo)
        freq_hi = freq_lo * lerp(2, 3, max(0, min(1, dna.spectral_center + rng.random() * 0.2)))
        freq_hi = min(freq_hi, 300)  # hard cap — sustained tones above this are unpleasant
    else:
        freq_lo = lerp(40, 400, 1 - dna.spectral_center) * (1 + rng.gauss(0, 0.2))
        freq_lo = max(20, freq_lo)
        freq_hi = freq_lo * lerp(2, 8, max(0, min(1, dna.spectral_center + rng.random() * 0.3)))

        # High register shift — insects, birds, chirps
        # Callers and swarms have a good chance to be pushed into the upper octaves
        if archetype in ("caller", "swarm") and rng.random() < 0.55:
            octaves_up = rng.choices([2, 3, 4, 5], weights=[1, 2, 2, 1], k=1)[0]
            shift = 2 ** octaves_up
            freq_lo *= shift
            freq_hi *= shift
            freq_hi = min(freq_hi, 12000)  # cap at 12kHz

    # Population
    pop_lo, pop_hi = ARCHETYPE_POP_RANGES[archetype]
    population = max(1, int(lerp(pop_lo, pop_hi, dna.density)))

    # Age range
    age_lo, age_hi = ARCHETYPE_AGE_RANGES[archetype]

    # Size factor from frequency range (log-scaled, 0=small/high, 1=large/low)
    # Full range is ~20Hz to ~3200Hz; map midpoint in log space
    freq_mid = (freq_lo + freq_hi) / 2
    log_min, log_max = math.log2(20), math.log2(3200)
    size = 1.0 - max(0.0, min(1.0,
        (math.log2(max(freq_mid, 20)) - log_min) / (log_max - log_min)
    ))

    # Archetype-specific params
    if archetype == "caller":
        params = _derive_caller_params(dna, rng, size=size)
    else:
        params = _ARCHETYPE_PARAM_DERIVERS[archetype](dna, rng)

    return Species(
        name=f"{archetype}_{index}",
        archetype=archetype,
        chain_spec=ChainSpec(
            source=source,
            effects=effects,
            source_params=source_params,
        ),
        freq_range=(freq_lo, freq_hi),
        pitch_set=pitch_set,
        population=population,
        age_range=(age_lo, age_hi),
        depth_dist=ARCHETYPE_DEPTH_DIST[archetype],
        params=params,
    )


# -- Top-level biome generation ------------------------------------------------

@dataclass
class BiomeSpec:
    """Complete specification for a biome, fully determined by seed."""
    seed: int
    dna: MacroDNA
    pitch_set_strategy: str
    pitch_set: list[float]
    species: list[Species]
    medium: MediumSpec

    def summary(self) -> str:
        lines = [
            f"Biome seed={self.seed}",
            f"  DNA: {self.dna.summary()}",
            f"  Pitch: {self.pitch_set_strategy} ({len(self.pitch_set)} notes)",
            f"  Species ({len(self.species)}):",
        ]
        for sp in self.species:
            # Format key source params concisely
            sp_params = {k: (f"{v:.2f}" if isinstance(v, float) else str(v))
                         for k, v in sp.chain_spec.source_params.items()}
            lines.append(
                f"    {sp.name}: {sp.chain_spec.source}({sp_params}) + "
                f"{[e[0] for e in sp.chain_spec.effects]}  "
                f"pop={sp.population}  freq={sp.freq_range[0]:.0f}-{sp.freq_range[1]:.0f}Hz"
            )
        lines.append(
            f"  Medium: room={self.medium.reverb_roomsize:.0f}m  decay={self.medium.reverb_time:.1f}s  "
            f"mix={self.medium.reverb_mix:.0%}  "
            f"resonances={len(self.medium.resonances)}  "
            f"noise_floor={self.medium.noise_floor_level:.0f}dB"
        )
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Structured representation for the web UI."""
        env_names = {0: "perc", 1: "swell", 2: "symmetric", 3: "sustained"}
        return {
            "seed": self.seed,
            "dna": {
                "density": round(self.dna.density, 3),
                "spectral_center": round(self.dna.spectral_center, 3),
                "temporal": round(self.dna.temporal, 3),
                "sociality": round(self.dna.sociality, 3),
                "room_scale": round(self.dna.room_scale, 3),
            },
            "pitch_set": {
                "strategy": self.pitch_set_strategy,
                "n_notes": len(self.pitch_set),
            },
            "species": [
                {
                    "name": sp.name,
                    "archetype": sp.archetype,
                    "source": sp.chain_spec.source,
                    "env_type": env_names.get(
                        sp.chain_spec.source_params.get("env_type", 0), "perc"
                    ),
                    "source_params": {
                        k: round(v, 3) if isinstance(v, float) else v
                        for k, v in sp.chain_spec.source_params.items()
                        if k != "env_type"
                    },
                    "effects": [name for name, _ in sp.chain_spec.effects],
                    "population": sp.population,
                    "freq_range": [round(sp.freq_range[0]), round(sp.freq_range[1])],
                    "depth_dist": sp.depth_dist,
                }
                for sp in self.species
            ],
            "medium": {
                "reverb_roomsize": round(self.medium.reverb_roomsize, 1),
                "reverb_time": round(self.medium.reverb_time, 1),
                "reverb_damping": round(self.medium.reverb_damping, 2),
                "reverb_mix": round(self.medium.reverb_mix, 2),
                "n_resonances": len(self.medium.resonances),
                "noise_floor_level": round(self.medium.noise_floor_level, 1),
                "noise_floor_color": round(self.medium.noise_floor_color, 2),
            },
        }


# -- Biome energy estimation ---------------------------------------------------

# Expected depth by distribution type (analytical mean of each distribution)
_EXPECTED_DEPTH = {
    "sqrt": 2 / 3,      # E[sqrt(U)] = 2/3
    "uniform": 0.5,
    "close": 1 / 3,      # E[U^2] = 1/3
}

# Approximate duty cycle by archetype (fraction of time producing sound)
_DUTY_CYCLE = {
    "caller":    0.30,
    "clicker":   0.15,
    "drone":     1.00,   # continuous
    "swarm":     0.40,
    "responder": 0.10,   # reactive, infrequent
}

# Mirrors engine.agent._SOURCE_GAIN — duplicated here to avoid circular import
_SOURCE_GAIN_EST = {
    "src_sine":    1.2,
    "src_noise":   0.5,
    "src_click":   0.8,
    "src_fm":      1.0,
    "src_formant": 0.7,
    "src_grain":   0.6,
    "src_string":  1.0,
}


def estimate_biome_energy(biome: BiomeSpec) -> float:
    """Estimate the expected total amplitude energy of a biome at steady state.

    Used by the EcosystemManager to set per-biome limiter makeup gain so that
    output loudness is consistent across biomes with very different densities.
    """
    total = 0.0
    for sp in biome.species:
        expected_depth = _EXPECTED_DEPTH.get(sp.depth_dist, 0.5)
        base_amp = lerp(0.5, 0.12, expected_depth)
        source_gain = _SOURCE_GAIN_EST.get(sp.chain_spec.source, 1.0)
        amp = base_amp * source_gain

        if sp.archetype == "drone":
            amp *= 0.4

        size = sp.params.get("size")
        if size is not None:
            amp *= lerp(0.6, 1.0, size)

        duty = _DUTY_CYCLE.get(sp.archetype, 0.3)
        total += amp * sp.population * duty

    # Reverb accumulates energy in the tail — wetter biomes are louder
    reverb_factor = 1.0 + biome.medium.reverb_mix * 0.5
    total *= reverb_factor

    return total


def generate_biome(seed: int) -> BiomeSpec:
    """Generate a complete biome specification from a seed. Deterministic."""
    rng = random.Random(seed)

    # Macro DNA
    dna = MacroDNA(
        density=rng.random(),
        spectral_center=rng.random(),
        temporal=rng.random(),
        sociality=rng.random(),
        room_scale=rng.random(),
    )

    # Pitch set
    pitch_strategy, pitch_set = generate_pitch_set(dna, rng)

    # Species count and archetype distribution
    n_species = max(3, int(lerp(4, 10, dna.density)))
    archetype_weights = {
        "caller":    max(0.01, dna.sociality * dna.temporal),
        "clicker":   max(0.01, dna.temporal * (1 - dna.sociality * 0.5)),
        "drone":     max(0.01, 1 - dna.temporal),
        "swarm":     max(0.01, dna.density * dna.temporal * 0.5),
        "responder": max(0.01, dna.sociality * 0.3),
    }
    archetypes = _weighted_sample(archetype_weights, n_species, rng)

    # Derive each species
    species = [
        _derive_single_species(arch, i, dna, pitch_set, rng)
        for i, arch in enumerate(archetypes)
    ]

    # Medium
    medium = derive_medium(dna, rng)

    return BiomeSpec(
        seed=seed,
        dna=dna,
        pitch_set_strategy=pitch_strategy,
        pitch_set=pitch_set,
        species=species,
        medium=medium,
    )
