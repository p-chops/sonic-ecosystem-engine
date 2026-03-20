"""Pitch set generation — procedural tuning systems for biomes."""

from __future__ import annotations

import math
import random

from generation.dna import MacroDNA


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * max(0.0, min(1.0, t))


def generate_pitch_set(dna: MacroDNA, rng: random.Random) -> tuple[str, list[float]]:
    """Generate a pitch set from DNA. Returns (strategy_name, frequencies_hz)."""
    base_freq = lerp(60, 400, dna.spectral_center) * (1 + rng.gauss(0, 0.1))
    base_freq = max(20, base_freq)  # safety floor

    strategy = rng.choice(["equal_division", "ratio_stack", "harmonic", "random_log"])

    if strategy == "equal_division":
        freqs = _equal_division(base_freq, rng)
    elif strategy == "ratio_stack":
        freqs = _ratio_stack(base_freq, rng)
    elif strategy == "harmonic":
        freqs = _harmonic(base_freq, rng)
    else:
        freqs = _random_log(base_freq, rng)

    return strategy, freqs


def _equal_division(base_freq: float, rng: random.Random) -> list[float]:
    """Divide an interval into N equal steps. Interval can be anything —
    octave, tritave, fifth, etc."""
    n_divisions = rng.randint(5, 31)
    interval_ratio = lerp(1.5, 3.0, rng.random())  # 2.0 = octave
    return [
        base_freq * (interval_ratio ** (i / n_divisions))
        for i in range(n_divisions)
    ]


def _ratio_stack(base_freq: float, rng: random.Random) -> list[float]:
    """Stack arbitrary intervals. Each step is a ratio drawn from a range."""
    n_notes = rng.randint(5, 19)
    freqs = [base_freq]
    for _ in range(n_notes - 1):
        ratio = lerp(1.02, 1.15, rng.random())  # microtonal to ~minor 2nd
        freqs.append(freqs[-1] * ratio)
    return freqs


def _harmonic(base_freq: float, rng: random.Random) -> list[float]:
    """Select partials from the harmonic series with optional drift."""
    n_partials = rng.randint(6, 16)
    partials = sorted(rng.sample(range(1, 25), n_partials))
    drift = rng.gauss(0, 0.01)  # slight inharmonicity
    return [
        base_freq * p * (1 + drift * rng.gauss(0, 1))
        for p in partials
    ]


def _random_log(base_freq: float, rng: random.Random) -> list[float]:
    """Frequencies spaced randomly in log space (perceptually random pitch)."""
    n_notes = rng.randint(5, 20)
    log_lo = math.log2(base_freq)
    log_hi = math.log2(base_freq * lerp(2, 4, rng.random()))
    log_freqs = sorted(rng.uniform(log_lo, log_hi) for _ in range(n_notes))
    return [2 ** lf for lf in log_freqs]
