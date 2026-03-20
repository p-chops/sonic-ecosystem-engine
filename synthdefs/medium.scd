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
// Spatial diffusion using FreeVerb.
// time: reverb time (mapped to roomsize)
// damping: high-frequency absorption
// mix: dry/wet
SynthDef(\med_reverb, { |in=0, out=0, time=0.7, damping=0.5, mix=0.5|
	var sig = In.ar(in, 1);
	var verb = FreeVerb.ar(sig,
		mix: 1.0,  // internal mix at full wet, we blend ourselves
		room: time.clip(0, 1),
		damp: damping.clip(0, 1)
	);
	sig = (sig * (1 - mix)) + (verb * mix);
	Out.ar(out, Pan2.ar(sig));  // stereo output from mono medium
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
	Out.ar(out, Pan2.ar(sig));
}).store;

// --- med_limiter ---
// Carrying capacity — compresses/limits when too many agents are active.
// threshold: level in dB above which compression kicks in
// ratio: compression ratio (1=none, higher=more limiting)
SynthDef(\med_limiter, { |in=0, out=0, threshold=(-6), ratio=4|
	var sig = In.ar(in, 2);  // stereo at this point
	// Compander as a compressor/limiter
	sig = Compander.ar(sig, sig,
		thresh: threshold.dbamp,
		slopeBelow: 1,
		slopeAbove: (1 / ratio.max(1)),
		clampTime: 0.005,
		relaxTime: 0.1
	);
	// Hard limiter safety net
	sig = Limiter.ar(sig, 0.95, 0.01);
	Out.ar(out, sig);
}).store;

)
