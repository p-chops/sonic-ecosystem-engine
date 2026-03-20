// Sonic Ecosystem Engine — Source SynthDefs
// Each source writes to an output bus, applies its own envelope
// with doneAction: 2 (self-freeing), and accepts standard params:
// out, freq, amp, decay.
//
// Evaluate this file in SuperCollider to compile all sources.
// SynthDefs are written to SynthDef.synthDefDir (Platform.userAppSupportDir +/+ "synthdefs").

(

// --- src_sine ---
// Pure sine with optional additive partials.
// n_partials=1 is a pure sine. Higher values add harmonics.
// partial_spread controls inharmonicity (0=harmonic, higher=stretched).
// partial_falloff controls amplitude rolloff per partial.
SynthDef(\src_sine, { |out=0, freq=440, amp=0.1, decay=1,
	n_partials=1, partial_spread=0, partial_falloff=0.7|
	var env = EnvGen.kr(Env.perc(0.005, decay), doneAction: 2);
	// All 8 partials always run; n_partials gates which are audible
	var sig = Mix.fill(8, { |i|
		var partial_freq = freq * (i + 1) * (1 + (partial_spread * i * i * 0.01));
		var partial_amp = (partial_falloff ** i) * (i < n_partials).lag(0.005);
		SinOsc.ar(partial_freq, 0, partial_amp);
	});
	sig = sig * env * amp;
	Out.ar(out, sig);
}).store;

// --- src_noise ---
// Filtered noise with variable bandwidth.
// noise_type: 0=white, 1=pink, 2=crackle, 3=dust
SynthDef(\src_noise, { |out=0, freq=1000, amp=0.1, decay=1,
	center_freq=1000, bandwidth=400, noise_type=0|
	var env = EnvGen.kr(Env.perc(0.01, decay), doneAction: 2);
	var noise = Select.ar(noise_type.round, [
		WhiteNoise.ar,
		PinkNoise.ar,
		Crackle.ar(1.5),
		Dust2.ar(freq.max(1)),
	]);
	var sig = BPF.ar(noise, center_freq.clip(20, 20000), (bandwidth / center_freq.max(1)).clip(0.01, 2));
	sig = sig * env * amp;
	Out.ar(out, sig);
}).store;

// --- src_click ---
// Short impulse through a resonant filter.
// impulse_type: 0=single impulse, 1=short burst, 2=dust
SynthDef(\src_click, { |out=0, freq=440, amp=0.1, decay=0.3,
	reson_freq=800, reson_q=10, impulse_type=0|
	var env = EnvGen.kr(Env.perc(0.001, decay), doneAction: 2);
	var impulse = Select.ar(impulse_type.round, [
		Impulse.ar(0),  // single impulse at synth start
		Impulse.ar(0) * WhiteNoise.ar,  // noise burst
		Dust2.ar(100),  // sparse dust
	]);
	var sig = Ringz.ar(impulse, reson_freq.clip(20, 20000), decay, amp);
	sig = sig * env;
	Out.ar(out, sig);
}).store;

// --- src_fm ---
// Two-operator FM synthesis.
// ratio: modulator/carrier frequency ratio
// index: modulation depth
// index_env_amount: how much the index decays with the envelope (0=static, 1=full decay)
SynthDef(\src_fm, { |out=0, freq=440, amp=0.1, decay=1,
	ratio=1.5, index=3, index_env_amount=0.5|
	var env = EnvGen.kr(Env.perc(0.005, decay), doneAction: 2);
	var index_env = index * (1 - (index_env_amount * (1 - env)));
	var mod_freq = freq * ratio;
	var mod = SinOsc.ar(mod_freq) * mod_freq * index_env;
	var sig = SinOsc.ar(freq + mod) * env * amp;
	Out.ar(out, sig);
}).store;

// --- src_formant ---
// Parallel bandpass filters excited by an impulse, for vowel/resonant body sounds.
// Up to 5 formants. Unused formants have amp=0.
SynthDef(\src_formant, { |out=0, freq=440, amp=0.1, decay=1,
	f1=800,  f2=1200, f3=2500, f4=3500, f5=5000,
	q1=20,   q2=20,   q3=20,   q4=20,   q5=20,
	a1=1.0,  a2=0.7,  a3=0.5,  a4=0.3,  a5=0.0|
	var env = EnvGen.kr(Env.perc(0.005, decay), doneAction: 2);
	var exciter = Impulse.ar(0) + (WhiteNoise.ar * EnvGen.kr(Env.perc(0.001, 0.005)));
	var sig = Mix([
		BPF.ar(exciter, f1.clip(20, 20000), (1/q1.max(1)).clip(0.001, 1)) * a1,
		BPF.ar(exciter, f2.clip(20, 20000), (1/q2.max(1)).clip(0.001, 1)) * a2,
		BPF.ar(exciter, f3.clip(20, 20000), (1/q3.max(1)).clip(0.001, 1)) * a3,
		BPF.ar(exciter, f4.clip(20, 20000), (1/q4.max(1)).clip(0.001, 1)) * a4,
		BPF.ar(exciter, f5.clip(20, 20000), (1/q5.max(1)).clip(0.001, 1)) * a5,
	]);
	sig = sig * env * amp;
	Out.ar(out, sig);
}).store;

// --- src_grain ---
// Micro-waveform granular synthesis.
// waveform: 0=sine, 1=saw, 2=noise
// grain_dur: duration of each grain in seconds
// grain_density: grains per second
// pitch_scatter: random pitch deviation per grain (0=none, 1=±octave)
SynthDef(\src_grain, { |out=0, freq=440, amp=0.1, decay=1,
	grain_dur=0.02, grain_density=20, pitch_scatter=0.1, waveform=0|
	var env = EnvGen.kr(Env.perc(0.01, decay), doneAction: 2);
	var trig = Impulse.ar(grain_density);
	var scatter = TRand.ar(-1 * pitch_scatter, pitch_scatter, trig);
	var grain_freq = freq * (2 ** scatter);
	var grain_env = EnvGen.ar(Env.sine(grain_dur), trig);
	var source = Select.ar(waveform.round, [
		SinOsc.ar(grain_freq),
		LFSaw.ar(grain_freq),
		WhiteNoise.ar,
	]);
	var sig = source * grain_env * env * amp;
	Out.ar(out, sig);
}).store;

// --- src_string ---
// Karplus-Strong plucked string.
// brightness: controls the noise/tone mix of the exciter (0=dark, 1=bright)
// damping: high-frequency damping in the delay line (0=none/sustain, 1=heavy)
// noise_mix: blend between pitched and noise components
SynthDef(\src_string, { |out=0, freq=440, amp=0.1, decay=1,
	brightness=0.5, damping=0.5, noise_mix=0.0|
	var env = EnvGen.kr(Env.linen(0.001, decay, 0.01), doneAction: 2);
	var exciter = WhiteNoise.ar * EnvGen.kr(Env.perc(0.001, 0.005));
	var delay_time = (1 / freq.max(20)).min(0.05);  // cap at 20 Hz
	var coef = damping.linlin(0, 1, -0.1, -0.9);
	var pluck, noise, sig;
	// LPF on exciter controls brightness
	exciter = LPF.ar(exciter, LinExp.kr(brightness, 0, 1, 400, 12000));
	pluck = Pluck.ar(exciter, Impulse.ar(0), 0.05, delay_time, decay * 2, coef);
	noise = exciter * EnvGen.kr(Env.perc(0.001, decay * 0.3));
	sig = ((pluck * (1 - noise_mix)) + (noise * noise_mix)) * env * amp;
	Out.ar(out, sig);
}).store;

)
