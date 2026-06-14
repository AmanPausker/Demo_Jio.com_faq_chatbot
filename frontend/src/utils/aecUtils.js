/**
 * aecUtils.js
 *
 * Provides a shared AudioContext + AEC worklet pipeline.
 *
 * Architecture:
 *
 *   [Mic MediaStream] ──► MediaStreamSource ──► AECNode (input[0])
 *                                                    │  ▲
 *   [TTS b64 WAV]  ──► AudioBufferSourceNode ─────► AECNode (input[1]) (reference)
 *                         (also plays to destination for the user to hear)
 *                                                    │
 *                                         cleaned mic output
 *                                                    │
 *                                    ┌───────────────┴────────────────┐
 *                                    ▼                                ▼
 *                           ScriptProcessor                      Analyser
 *                         (live mode WebSocket)             (VAD volume check)
 *
 * Usage:
 *   import { getAECContext, connectMicToAEC, playTTSThroughAEC, disconnectAEC } from './aecUtils';
 */

let _ctx = null;
let _workletLoaded = false;
let _aecNode = null;
let _refGain = null;       // GainNode that all TTS sources connect to → input[1] of AEC
let _micSource = null;

/**
 * Lazily create and return the shared AudioContext, loading the worklet module once.
 * @returns {Promise<AudioContext>}
 */
export async function getAECContext() {
  if (!_ctx || _ctx.state === 'closed') {
    _ctx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
    _workletLoaded = false;
    _aecNode = null;
    _refGain = null;
    _micSource = null;
  }
  if (_ctx.state === 'suspended') {
    await _ctx.resume();
  }
  if (!_workletLoaded) {
    await _ctx.audioWorklet.addModule('/aec-processor.js');
    _workletLoaded = true;
  }
  return _ctx;
}

/**
 * Build (or reuse) the AEC worklet node and the reference gain node.
 * @param {AudioContext} ctx
 * @returns {{ aecNode: AudioWorkletNode, refGain: GainNode }}
 */
function ensureAECNodes(ctx) {
  if (!_aecNode) {
    _aecNode = new AudioWorkletNode(ctx, 'aec-processor', {
      numberOfInputs: 2,   // input[0]=mic, input[1]=reference
      numberOfOutputs: 1,
      outputChannelCount: [1],
      channelCount: 1,
      channelCountMode: 'explicit',
    });
  }
  if (!_refGain) {
    _refGain = ctx.createGain();
    _refGain.gain.value = 1.0;
    // Wire reference gain → AEC input[1]
    _refGain.connect(_aecNode, 0, 1);
  }
  return { aecNode: _aecNode, refGain: _refGain };
}

/**
 * Connect a microphone MediaStream through the AEC worklet.
 *
 * @param {MediaStream} micStream  — raw microphone MediaStream
 * @param {AudioContext} ctx       — from getAECContext()
 * @returns {AudioWorkletNode}     — the cleaned output node; connect this to downstream nodes
 */
export function connectMicToAEC(micStream, ctx) {
  const { aecNode } = ensureAECNodes(ctx);

  // Disconnect any previous mic source
  if (_micSource) {
    try { _micSource.disconnect(); } catch (_) {}
  }

  _micSource = ctx.createMediaStreamSource(micStream);
  _micSource.connect(aecNode, 0, 0); // mic → input[0]

  return aecNode; // callers connect this to analyser / scriptprocessor etc.
}

/**
 * Decode a base64 WAV string and play it through the AudioContext so the
 * AEC worklet has a reference signal.
 *
 * This replaces the plain <audio> `src = data:audio/wav;base64,...` approach
 * for TTS playback in contexts where AEC is active.
 *
 * @param {string}       b64        — base64-encoded WAV audio
 * @param {AudioContext} ctx        — from getAECContext()
 * @param {function}     onEnded    — called when playback finishes
 * @returns {AudioBufferSourceNode} — so callers can cancel early (barge-in)
 */
export async function playTTSThroughAEC(b64, ctx, onEnded) {
  const { refGain } = ensureAECNodes(ctx);

  // Decode base64 → ArrayBuffer
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);

  let audioBuffer;
  try {
    audioBuffer = await ctx.decodeAudioData(bytes.buffer);
  } catch (err) {
    console.error('[AEC] decodeAudioData failed:', err);
    onEnded?.();
    return null;
  }

  const source = ctx.createBufferSource();
  source.buffer = audioBuffer;

  // Route to both:
  //  1. ctx.destination  → user hears the TTS
  //  2. refGain          → AEC worklet gets the reference signal
  source.connect(ctx.destination);
  source.connect(refGain);

  source.onended = () => onEnded?.();
  source.start();
  return source;
}

/**
 * Enable or disable the NLMS filter inside the worklet.
 * When disabled, mic passes through unchanged (useful for text-only mode).
 */
export function setAECEnabled(enabled) {
  if (_aecNode) {
    _aecNode.port.postMessage({ type: 'set-enabled', value: enabled });
  }
}

/**
 * Fully tear down the AEC pipeline (call when leaving live/audio mode).
 */
export function disconnectAEC() {
  try { if (_micSource) _micSource.disconnect(); } catch (_) {}
  try { if (_refGain)   _refGain.disconnect();   } catch (_) {}
  try { if (_aecNode)   _aecNode.disconnect();   } catch (_) {}
  _micSource = null;
  _refGain   = null;
  _aecNode   = null;

  if (_ctx && _ctx.state !== 'closed') {
    _ctx.close();
    _ctx = null;
    _workletLoaded = false;
  }
}
