// Sonic Ecosystem Engine — Effect SynthDefs
// Each effect reads from an input bus, processes, and writes to an output bus.
// Effects are persistent — they run for the lifetime of the agent.
// Standard parameters: in, out.

(

// --- fx_lpf ---
// Resonant low-pass filter.
SynthDef(\fx_lpf, { |in=0, out=0, cutoff=2000, res=0.3|
	var sig = In.ar(in, 1);
	sig = RLPF.ar(sig, cutoff.clip(20, 20000), (1 - res.clip(0, 0.99)));
	Out.ar(out, sig);
}).store;

// --- fx_hpf ---
// Resonant high-pass filter.
SynthDef(\fx_hpf, { |in=0, out=0, cutoff=200, res=0.3|
	var sig = In.ar(in, 1);
	sig = RHPF.ar(sig, cutoff.clip(20, 20000), (1 - res.clip(0, 0.99)));
	Out.ar(out, sig);
}).store;

// --- fx_bpf ---
// Bandpass filter.
SynthDef(\fx_bpf, { |in=0, out=0, center=1000, q=1|
	var sig = In.ar(in, 1);
	sig = BPF.ar(sig, center.clip(20, 20000), (1 / q.max(0.1)).clip(0.001, 2));
	Out.ar(out, sig);
}).store;

// --- fx_delay ---
// Feedback delay / comb delay.
SynthDef(\fx_delay, { |in=0, out=0, delay_time=0.2, feedback=0.4, mix=0.5|
	var sig = In.ar(in, 1);
	var delayed = CombL.ar(sig, 1.0, delay_time.clip(0.001, 1.0), feedback.clip(0, 0.95) * 4);
	sig = (sig * (1 - mix)) + (delayed * mix);
	Out.ar(out, sig);
}).store;

// --- fx_fold ---
// Wavefolder / waveshaper.
// drive: amplitude multiplier before folding (1=clean, higher=more harmonics)
// symmetry: 0=symmetric folding, 1=asymmetric (adds even harmonics)
SynthDef(\fx_fold, { |in=0, out=0, drive=2.0, symmetry=0|
	var sig = In.ar(in, 1);
	sig = sig * drive;
	sig = sig + (symmetry * 0.3);  // DC offset for asymmetry
	sig = sig.fold(-1, 1);
	sig = LeakDC.ar(sig);  // remove DC from asymmetric folding
	sig = sig / drive.max(1).sqrt;  // gentle gain compensation
	Out.ar(out, sig);
}).store;

// --- fx_ring ---
// Ring modulator.
SynthDef(\fx_ring, { |in=0, out=0, mod_freq=200, mod_depth=1.0|
	var sig = In.ar(in, 1);
	var mod = SinOsc.ar(mod_freq);
	sig = sig * ((1 - mod_depth) + (mod * mod_depth));
	Out.ar(out, sig);
}).store;

// --- fx_chorus ---
// Chorus / detune / thicken.
// voices: number of chorus voices (1-4, controls density)
// rate: LFO speed in Hz
// depth: delay modulation depth in seconds
SynthDef(\fx_chorus, { |in=0, out=0, rate=0.3, depth=0.003, voices=3|
	var sig = In.ar(in, 1);
	// All 4 voices always run; voices param gates which are audible
	var chorus = Mix.fill(4, { |i|
		var phase = i / 4;
		var lfo = SinOsc.kr(rate, phase * 2pi) * depth + depth + 0.001;
		DelayL.ar(sig, 0.05, lfo) * (i < voices).lag(0.01);
	});
	sig = (sig + chorus) / (1 + voices.max(1));  // normalize
	Out.ar(out, sig);
}).store;

// --- fx_pan_out ---
// Panner + output to main bus, with send to medium bus.
// send crossfades between dry (main out) and wet (medium bus):
//   send=0 → 100% dry, 0% to medium
//   send=1 → 0% dry, 100% to medium
// pan: -1 (left) to 1 (right)
// send_bus: bus index for the shared medium
// main_out: main output bus (default 0 = hardware out)
SynthDef(\fx_pan_out, { |in=0, main_out=0, pan=0, amp=1,
	send=0.3, send_bus=0|
	var sig = In.ar(in, 1) * amp;
	var panned = Pan2.ar(sig, pan);
	Out.ar(main_out, panned * (1 - send));
	Out.ar(send_bus, sig * send);
}).store;

)
