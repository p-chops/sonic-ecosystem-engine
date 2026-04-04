// Sonic Ecosystem Engine — Medium (shared acoustic environment) SynthDefs
// The medium is an effect chain on a shared bus. All agents send some portion
// of their output to this bus. The medium processes the combined signal and
// outputs to the main bus.

(

// --- med_resonance ---
// Formant filter bank — the room's resonant character.
// Up to 6 resonant frequencies. Unused resonances have amp=0.
// Each resonance is a bandpass filter ringing at its frequency.
SynthDef(\med_resonance, { |in=0, out=0,
	f1=200,  f2=500,  f3=1200, f4=2500, f5=4000, f6=6000,
	q1=20,   q2=20,   q3=20,   q4=20,   q5=20,   q6=20,
	a1=1.0,  a2=0.8,  a3=0.6,  a4=0.4,  a5=0.2,  a6=0.0,
	mix=0.3|
	var sig = In.ar(in, 1);
	var resonated = Mix([
		BPF.ar(sig, f1.clip(20, 20000), (1/q1.max(1)).clip(0.001, 1)) * a1,
		BPF.ar(sig, f2.clip(20, 20000), (1/q2.max(1)).clip(0.001, 1)) * a2,
		BPF.ar(sig, f3.clip(20, 20000), (1/q3.max(1)).clip(0.001, 1)) * a3,
		BPF.ar(sig, f4.clip(20, 20000), (1/q4.max(1)).clip(0.001, 1)) * a4,
		BPF.ar(sig, f5.clip(20, 20000), (1/q5.max(1)).clip(0.001, 1)) * a5,
		BPF.ar(sig, f6.clip(20, 20000), (1/q6.max(1)).clip(0.001, 1)) * a6,
	]);
	sig = (sig * (1 - mix)) + (resonated * mix);
	Out.ar(out, sig);
}).store;

// --- med_reverb ---
// Spatial diffusion using GVerb (mono in → decorrelated stereo out).
// roomsize: room size in meters (0.1–300)
// revtime: reverb decay time in seconds (0.1–100)
// damping: high-frequency absorption (0–1)
// mix: dry/wet
SynthDef(\med_reverb, { |in=0, out=0, roomsize=20, revtime=3, damping=0.5,
	drylevel=0, mix=0.85|
	var sig = In.ar(in, 1);
	var verb = GVerb.ar(sig,
		roomsize: roomsize.clip(0.1, 300),
		revtime: revtime.clip(0.1, 100),
		damping: damping.clip(0, 1),
		inputbw: (1 - damping).clip(0.1, 1),  // darker rooms absorb more input HF too
		drylevel: drylevel,  // we handle dry/wet ourselves
		earlyreflevel: 0.5,
		taillevel: 0.4
	);
	var dry = Pan2.ar(sig);
	var out_sig = (dry * (1 - mix)) + (verb * mix);
	Out.ar(out, out_sig);
}).store;

// --- med_eq ---
// 3-band parametric EQ for spectral shaping.
// Parameters are modulatable at runtime for "spectral weather".
SynthDef(\med_eq, { |in=0, out=0,
	lo_freq=200,  lo_gain=0, lo_q=1,
	mid_freq=1000, mid_gain=0, mid_q=1,
	hi_freq=5000, hi_gain=0, hi_q=1|
	var sig = In.ar(in, 1);
	sig = BPeakEQ.ar(sig,
		lo_freq.clip(20, 20000),
		(1/lo_q.max(0.1)).clip(0.01, 10),
		lo_gain.clip(-24, 24));
	sig = BPeakEQ.ar(sig,
		mid_freq.clip(20, 20000),
		(1/mid_q.max(0.1)).clip(0.01, 10),
		mid_gain.clip(-24, 24));
	sig = BPeakEQ.ar(sig,
		hi_freq.clip(20, 20000),
		(1/hi_q.max(0.1)).clip(0.01, 10),
		hi_gain.clip(-24, 24));
	Out.ar(out, sig);
}).store;

// --- med_noise_floor ---
// Ambient noise texture of the space itself.
// Feeds into the medium bus (mono) so it picks up resonance + reverb.
// level: amplitude in dB (e.g. -40)
// color: 0=white, 1=brown (interpolates via LPF cutoff)
// filter: additional LPF cutoff on the noise
SynthDef(\med_noise_floor, { |out=0, level=(-40), color=0.5, filter=8000|
	var noise = WhiteNoise.ar;
	var brown = LPF.ar(LPF.ar(noise, 200), 200);
	var colored = (noise * (1 - color)) + (brown * color * 10);  // compensate brown level
	var sig;
	// Color: crossfade between white and brown (heavily filtered) noise
	colored = LPF.ar(colored, filter.clip(20, 20000));
	sig = colored * level.dbamp;
	Out.ar(out, sig);  // mono — reverb decorrelates to stereo
}).store;

// --- med_limiter ---
// Kept for compatibility — simple single-band compressor/limiter.
SynthDef(\med_limiter, { |in=0, out=0, threshold=(-18), ratio=8, makeup=6,
	attack=0.1, release=1.0|
	var sig = In.ar(in, 2);
	sig = Compander.ar(sig, sig,
		thresh: threshold.dbamp,
		slopeBelow: 1,
		slopeAbove: (1 / ratio.max(1)),
		clampTime: attack.clip(0.001, 1),
		relaxTime: release.clip(0.01, 10)
	);
	sig = sig * makeup.dbamp;
	sig = Limiter.ar(sig, 0.95, 0.01);
	Out.ar(out, sig);
}).store;

// --- med_master ---
// Multi-band mastering chain. Replaces med_limiter for streaming use.
// Splits into 3 bands (low/mid/high), compresses each independently,
// recombines with makeup gain, then brick-wall limits.
//
// makeup: broadband post-compression gain in dB
// lo_boost / hi_boost: per-band trim in dB (pre-compression)
// drive: input gain in dB (push into the compressors harder)
SynthDef(\med_master, { |in=0, out=0,
	makeup=18, drive=12,
	lo_boost=6, hi_boost=3,
	lo_thresh=(-30), mid_thresh=(-26), hi_thresh=(-24),
	lo_ratio=12, mid_ratio=10, hi_ratio=8,
	lo_attack=0.05, mid_attack=0.02, hi_attack=0.01,
	lo_release=0.6, mid_release=0.4, hi_release=0.3,
	xover_lo=200, xover_hi=3000|

	var sig = In.ar(in, 2);
	var lo, mid, hi;

	// Input drive — push signal into the compressors
	sig = sig * drive.dbamp;

	// --- Band split (Linkwitz-Riley style: cascaded LPF/HPF) ---
	lo = LPF.ar(LPF.ar(sig, xover_lo), xover_lo);
	hi = HPF.ar(HPF.ar(sig, xover_hi), xover_hi);
	mid = sig - lo - hi;  // residual = mid band

	// Per-band trim
	lo = lo * lo_boost.dbamp;
	hi = hi * hi_boost.dbamp;

	// --- Per-band compression ---
	// Low: slow attack lets transients through, long release for smooth bass
	lo = Compander.ar(lo, lo,
		thresh: lo_thresh.dbamp,
		slopeBelow: 1,
		slopeAbove: (1 / lo_ratio.max(1)),
		clampTime: lo_attack.clip(0.001, 1),
		relaxTime: lo_release.clip(0.01, 10)
	);

	// Mid: moderate — this is where most musical content lives
	mid = Compander.ar(mid, mid,
		thresh: mid_thresh.dbamp,
		slopeBelow: 1,
		slopeAbove: (1 / mid_ratio.max(1)),
		clampTime: mid_attack.clip(0.001, 1),
		relaxTime: mid_release.clip(0.01, 10)
	);

	// High: fast attack to catch harsh transients, short release
	hi = Compander.ar(hi, hi,
		thresh: hi_thresh.dbamp,
		slopeBelow: 1,
		slopeAbove: (1 / hi_ratio.max(1)),
		clampTime: hi_attack.clip(0.001, 1),
		relaxTime: hi_release.clip(0.01, 10)
	);

	// --- Recombine ---
	sig = lo + mid + hi;

	// Broadband makeup gain
	sig = sig * makeup.dbamp;

	// Brick-wall limiter — nothing gets past 0.95
	sig = Limiter.ar(sig, 0.95, 0.01);

	Out.ar(out, sig);
}).store;

)
