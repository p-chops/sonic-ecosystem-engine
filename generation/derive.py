"""Derivation rules — DNA → species list + medium spec.

This is the primary site for tuning the generator. The derivation functions
encode aesthetic judgment about what combinations tend to sound good.
"""

from __future__ import annotations

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
    "caller":    (2, 6),
    "clicker":   (3, 8),
    "drone":     (1, 3),
    "swarm":     (2, 6),
    "responder": (1, 2),
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
    reverb_time: float
    reverb_damping: float
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
        freq = max(40, min(freq, 16000))
        q = rng.uniform(5, 40)
        amp = lerp(1.0, 0.2, i / max(n - 1, 1))  # earlier resonances louder
        resonances.append(Resonance(freq=freq, q=q, amp=amp))
    return resonances


def derive_medium(dna: MacroDNA, rng: random.Random) -> MediumSpec:
    """Derive medium parameters from DNA."""
    n_resonances = int(lerp(2, 6, dna.room_scale))
    return MediumSpec(
        reverb_time=lerp(0.3, 0.95, dna.room_scale),  # FreeVerb room param is 0–1
        reverb_damping=lerp(0.2, 0.8, 1 - dna.spectral_center),
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

def _derive_effects(dna: MacroDNA, rng: random.Random) -> list[tuple[str, dict]]:
    """Derive an effect chain from DNA."""
    effects = []

    if rng.random() < 0.6:
        cutoff_t = max(0, min(1, dna.spectral_center + rng.gauss(0, 0.15)))
        effects.append(("fx_lpf", {
            "cutoff": lerp(200, 8000, cutoff_t),
            "res": rng.uniform(0.0, 0.5),
        }))

    if rng.random() < 0.3:
        effects.append(("fx_hpf", {
            "cutoff": lerp(40, 800, rng.random()),
            "res": rng.uniform(0.0, 0.3),
        }))

    if rng.random() < 0.15:
        effects.append(("fx_bpf", {
            "center": lerp(200, 4000, dna.spectral_center + rng.gauss(0, 0.2)),
            "q": rng.uniform(1, 10),
        }))

    if rng.random() < 0.25:
        effects.append(("fx_fold", {
            "drive": lerp(1.1, 4.0, rng.random()),
            "symmetry": rng.uniform(0, 0.5),
        }))

    if rng.random() < 0.3 * dna.room_scale:
        effects.append(("fx_delay", {
            "delay_time": lerp(0.01, 0.3, rng.random()),
            "feedback": lerp(0.1, 0.7, rng.random()),
            "mix": lerp(0.2, 0.6, rng.random()),
        }))

    if rng.random() < 0.2:
        effects.append(("fx_ring", {
            "mod_freq": lerp(20, 2000, rng.random()),
            "mod_depth": rng.uniform(0.3, 1.0),
        }))

    if rng.random() < 0.2:
        effects.append(("fx_chorus", {
            "rate": rng.uniform(0.1, 1.0),
            "depth": rng.uniform(0.001, 0.008),
            "voices": rng.randint(2, 4),
        }))

    return effects


# -- Archetype-specific parameter derivation -----------------------------------

def _derive_caller_params(dna: MacroDNA, rng: random.Random) -> dict:
    return {
        "song_length": rng.randint(3, int(lerp(5, 10, dna.temporal))),
        "note_dur_range": (
            lerp(0.05, 0.15, dna.temporal),
            lerp(0.2, 0.8, 1 - dna.temporal),
        ),
        "note_gap": (0.02, lerp(0.05, 0.2, 1 - dna.temporal)),
        "base_pause": (
            lerp(1.0, 2.0, dna.sociality),
            lerp(3.0, 8.0, 1 - dna.sociality),
        ),
        "glide_prob": lerp(0.05, 0.4, rng.random()),
        "transpose_prob": lerp(0.05, 0.3, rng.random()),
        "fatigue_threshold": lerp(3.0, 8.0, 1 - dna.sociality),
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
            lerp(2.0, 5.0, dna.temporal),
            lerp(5.0, 15.0, 1 - dna.temporal),
        ),
        "drift_range": lerp(0.02, 0.15, rng.random()),
        "inverse_coupling": dna.sociality > 0.3,
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


# -- Species derivation --------------------------------------------------------

def _derive_single_species(
    archetype: str,
    index: int,
    dna: MacroDNA,
    pitch_set: list[float],
    rng: random.Random,
) -> Species:
    """Derive a single species from DNA and archetype."""
    # Source selection
    source_weights = {name: fn(dna) for name, fn in SOURCE_WEIGHTS.items()}
    source = _weighted_choice(source_weights, rng)

    # Effect chain
    effects = _derive_effects(dna, rng)

    # Frequency range — drones are pushed low
    if archetype == "drone":
        freq_lo = lerp(30, 120, 1 - dna.spectral_center) * (1 + rng.gauss(0, 0.1))
        freq_lo = max(20, freq_lo)
        freq_hi = freq_lo * lerp(2, 4, max(0, min(1, dna.spectral_center + rng.random() * 0.2)))
    else:
        freq_lo = lerp(40, 400, 1 - dna.spectral_center) * (1 + rng.gauss(0, 0.2))
        freq_lo = max(20, freq_lo)
        freq_hi = freq_lo * lerp(2, 8, max(0, min(1, dna.spectral_center + rng.random() * 0.3)))

    # Population
    pop_lo, pop_hi = ARCHETYPE_POP_RANGES[archetype]
    population = max(1, int(lerp(pop_lo, pop_hi, dna.density)))

    # Age range
    age_lo, age_hi = ARCHETYPE_AGE_RANGES[archetype]

    # Archetype-specific params
    params = _ARCHETYPE_PARAM_DERIVERS[archetype](dna, rng)

    return Species(
        name=f"{archetype}_{index}",
        archetype=archetype,
        chain_spec=ChainSpec(
            source=source,
            effects=effects,
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
            lines.append(
                f"    {sp.name}: {sp.chain_spec.source} + "
                f"{[e[0] for e in sp.chain_spec.effects]}  "
                f"pop={sp.population}  freq={sp.freq_range[0]:.0f}-{sp.freq_range[1]:.0f}Hz"
            )
        lines.append(
            f"  Medium: reverb={self.medium.reverb_time:.1f}s  "
            f"resonances={len(self.medium.resonances)}  "
            f"noise_floor={self.medium.noise_floor_level:.0f}dB"
        )
        return "\n".join(lines)


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
    n_species = max(2, int(lerp(2, 8, dna.density)))
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
