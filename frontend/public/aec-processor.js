/**
 * AEC AudioWorkletProcessor
 *
 * Implements a Normalised Least Mean Squares (NLMS) adaptive filter.
 * The processor receives two inputs:
 *   input[0] — microphone signal (what we want to clean)
 *   input[1] — reference signal  (the TTS/speaker playback, i.e. the echo source)
 *
 * It continuously adapts the filter weights so that the estimated echo
 * (reference convolved with weights) is subtracted from the mic signal,
 * leaving only the user's voice.
 *
 * Port messages:
 *   { type: 'set-enabled', value: boolean } — bypass the filter when false
 */

const FILTER_LENGTH = 512;   // Adaptive filter taps — longer = better but more CPU
const MU           = 0.01;   // Step size (learning rate). Lower = stable but slower adapt.
const DELTA        = 1e-6;   // Regularisation — prevents division by zero

class AECProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._weights   = new Float32Array(FILTER_LENGTH); // adaptive filter coefficients
    this._refBuffer = new Float32Array(FILTER_LENGTH); // circular buffer of reference samples
    this._writeIdx  = 0;
    this._enabled   = true;

    this.port.onmessage = (e) => {
      if (e.data.type === 'set-enabled') {
        this._enabled = e.data.value;
        if (!e.data.value) {
          // Reset on disable so we don't carry stale weights into next session
          this._weights.fill(0);
          this._refBuffer.fill(0);
        }
      }
    };
  }

  /**
   * Read one sample from the circular reference buffer at offset `lag`
   * samples behind the current write pointer.
   */
  _readRef(lag) {
    const idx = (this._writeIdx - lag - 1 + FILTER_LENGTH) % FILTER_LENGTH;
    return this._refBuffer[idx];
  }

  process(inputs, outputs) {
    const micInput  = inputs[0];
    const refInput  = inputs[1];
    const output    = outputs[0];

    // If either channel is missing, pass mic through unchanged
    if (!micInput || !micInput[0] || !refInput || !refInput[0]) {
      if (output && output[0] && micInput && micInput[0]) {
        output[0].set(micInput[0]);
      }
      return true;
    }

    const mic = micInput[0];
    const ref = refInput[0];
    const out = output[0];

    for (let n = 0; n < mic.length; n++) {
      const refSample = ref[n];

      // Write current reference sample into circular buffer
      this._refBuffer[this._writeIdx] = refSample;
      this._writeIdx = (this._writeIdx + 1) % FILTER_LENGTH;

      if (!this._enabled) {
        out[n] = mic[n];
        continue;
      }

      // Compute estimated echo: y = w^T * x
      let echo = 0;
      for (let k = 0; k < FILTER_LENGTH; k++) {
        echo += this._weights[k] * this._readRef(k);
      }

      // Error signal: what remains after echo removal
      const error = mic[n] - echo;

      // Compute reference signal power for normalisation
      let power = DELTA;
      for (let k = 0; k < FILTER_LENGTH; k++) {
        const s = this._readRef(k);
        power += s * s;
      }

      // NLMS weight update: w += mu * error * x / power
      const stepNorm = MU / power;
      for (let k = 0; k < FILTER_LENGTH; k++) {
        this._weights[k] += stepNorm * error * this._readRef(k);
      }

      out[n] = error;
    }

    return true; // keep processor alive
  }
}

registerProcessor('aec-processor', AECProcessor);
