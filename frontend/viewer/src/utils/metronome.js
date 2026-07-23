// A standard lookahead-scheduler Web Audio metronome: a fast setInterval
// polls for beats due in the next SCHEDULE_AHEAD_SEC and schedules their
// clicks against AudioContext.currentTime (not setTimeout directly), which
// is what keeps the beat rock-steady despite JS timer jitter. Runs
// independently of any hardware/backend timing -- it only needs a BPM and
// stays in the browser tab.
const LOOKAHEAD_MS = 25;
const SCHEDULE_AHEAD_SEC = 0.1;
const CLICK_DURATION_SEC = 0.05;

export class Metronome {
  constructor() {
    this.audioCtx = null;
    this.timerId = null;
    this.nextNoteTime = 0;
    this.bpm = 100;
    this.muted = false;
    this.paused = false;
  }

  start(bpm) {
    this.bpm = bpm;
    if (this.audioCtx) return; // already running -- use setBpm to change tempo
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return; // unsupported browser -- metronome silently does nothing
    this.audioCtx = new AudioContextClass();
    this.nextNoteTime = this.audioCtx.currentTime;
    this.timerId = setInterval(() => this._scheduler(), LOOKAHEAD_MS);
  }

  setBpm(bpm) {
    this.bpm = Math.max(20, bpm);
  }

  setMuted(muted) {
    this.muted = muted;
  }

  setPaused(paused) {
    const wasPaused = this.paused;
    this.paused = paused;
    if (wasPaused && !paused && this.audioCtx) {
      // Resuming: start counting from now, not from wherever the beat grid
      // would be if it had kept silently advancing through the pause.
      this.nextNoteTime = this.audioCtx.currentTime;
    }
  }

  reset() {
    if (this.audioCtx) this.nextNoteTime = this.audioCtx.currentTime;
  }

  stop() {
    if (this.timerId) clearInterval(this.timerId);
    this.timerId = null;
    if (this.audioCtx) {
      this.audioCtx.close();
      this.audioCtx = null;
    }
  }

  _scheduler() {
    if (!this.audioCtx || this.paused) return;
    while (this.nextNoteTime < this.audioCtx.currentTime + SCHEDULE_AHEAD_SEC) {
      if (!this.muted) this._playClick(this.nextNoteTime);
      this.nextNoteTime += 60.0 / this.bpm;
    }
  }

  _playClick(time) {
    const osc = this.audioCtx.createOscillator();
    const gain = this.audioCtx.createGain();
    osc.frequency.value = 1000;
    gain.gain.setValueAtTime(0.3, time);
    gain.gain.exponentialRampToValueAtTime(0.001, time + CLICK_DURATION_SEC);
    osc.connect(gain);
    gain.connect(this.audioCtx.destination);
    osc.start(time);
    osc.stop(time + CLICK_DURATION_SEC);
  }
}
