/**
 * LifeOS Synthesized Web Audio & Haptic Feedback Engine.
 * 
 * Generates pure mathematical micro-soundscapes and tactile vibrations
 * using the Web Audio API without requiring any external audio files.
 */

(function () {
  let ctx = null;
  let soundEnabled = true;

  function getAudioContext() {
    if (!ctx && (window.AudioContext || window.webkitAudioContext)) {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      ctx = new AudioCtx();
    }
    if (ctx && ctx.state === "suspended") {
      ctx.resume();
    }
    return ctx;
  }

  function vibrate(pattern) {
    if ("vibrate" in navigator) {
      try {
        navigator.vibrate(pattern);
      } catch (e) {}
    }
  }

  window.LifeOSAudio = {
    toggleSound(enable) {
      soundEnabled = enable;
    },

    // ⚡ Connection & QR Scan Chime
    playConnect() {
      vibrate([40, 60, 40]);
      if (!soundEnabled) return;
      const ac = getAudioContext();
      if (!ac) return;

      const now = ac.currentTime;
      const osc1 = ac.createOscillator();
      const osc2 = ac.createOscillator();
      const gain = ac.createGain();

      osc1.type = "sine";
      osc2.type = "triangle";

      // Harmonic chime 587Hz (D5) -> 880Hz (A5)
      osc1.frequency.setValueAtTime(587.33, now);
      osc1.frequency.exponentialRampToValueAtTime(880.00, now + 0.12);

      osc2.frequency.setValueAtTime(880.00, now);
      osc2.frequency.exponentialRampToValueAtTime(1174.66, now + 0.18);

      gain.gain.setValueAtTime(0.12, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.35);

      osc1.connect(gain);
      osc2.connect(gain);
      gain.connect(ac.destination);

      osc1.start(now);
      osc2.start(now);
      osc1.stop(now + 0.36);
      osc2.stop(now + 0.36);
    },

    // 🏆 Karma & Goal Completed Sound
    playDividend() {
      vibrate([50, 80]);
      if (!soundEnabled) return;
      const ac = getAudioContext();
      if (!ac) return;

      const now = ac.currentTime;
      const notes = [523.25, 659.25, 783.99, 1046.50]; // C5, E5, G5, C6 arpeggio
      notes.forEach((freq, i) => {
        const osc = ac.createOscillator();
        const gain = ac.createGain();
        const start = now + (i * 0.07);
        osc.type = "sine";
        osc.frequency.setValueAtTime(freq, start);
        gain.gain.setValueAtTime(0.08, start);
        gain.gain.exponentialRampToValueAtTime(0.001, start + 0.25);
        osc.connect(gain);
        gain.connect(ac.destination);
        osc.start(start);
        osc.stop(start + 0.26);
      });
    },

    // 🛡️ Focus Shield Activation Hum
    playFocusShield() {
      vibrate([80]);
      if (!soundEnabled) return;
      const ac = getAudioContext();
      if (!ac) return;

      const now = ac.currentTime;
      const osc = ac.createOscillator();
      const gain = ac.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(120, now);
      osc.frequency.exponentialRampToValueAtTime(40, now + 0.4);
      gain.gain.setValueAtTime(0.15, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.45);
      osc.connect(gain);
      gain.connect(ac.destination);
      osc.start(now);
      osc.stop(now + 0.46);
    },

    // 🧘 Mindfulness 528Hz Solfeggio Tone
    playMindfulnessBell() {
      vibrate([100]);
      if (!soundEnabled) return;
      const ac = getAudioContext();
      if (!ac) return;

      const now = ac.currentTime;
      const osc = ac.createOscillator();
      const gain = ac.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(528.0, now); // 528Hz DNA / Transformation frequency
      gain.gain.setValueAtTime(0.2, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 2.5);
      osc.connect(gain);
      gain.connect(ac.destination);
      osc.start(now);
      osc.stop(now + 2.55);
    }
  };
})();
