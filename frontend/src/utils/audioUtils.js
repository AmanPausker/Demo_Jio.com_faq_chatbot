/**
 * Converts a Float32Array (raw audio samples from VAD) to a WAV format Blob
 * suitable for sending via HTTP POST to the backend API.
 * 
 * @param {Float32Array} audioData - The raw audio data
 * @param {number} sampleRate - The sample rate of the audio (default 16000 for vad-web)
 * @returns {Blob} - The encoded WAV file Blob
 */
export const floatToWavBlob = (audioData, sampleRate = 16000) => {
  // Handle case where vad-web passes an object { audio: Float32Array } instead of the array directly
  let data = audioData;
  if (data.audio && data.audio instanceof Float32Array) {
    data = data.audio;
  }
  
  // Cap at 25 seconds to prevent Sarvam AI 30s limit errors (25 * 16000 = 400,000 samples)
  const MAX_SAMPLES = 25 * 16000;
  if (data.length > MAX_SAMPLES) {
    data = data.slice(0, MAX_SAMPLES);
  }

  const numFrames = data.length;
  const numChannels = 1;
  const bytesPerSample = 2; // 16-bit
  const blockAlign = numChannels * bytesPerSample;
  const byteRate = sampleRate * blockAlign;
  const dataSize = numFrames * blockAlign;
  
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);
  
  const writeString = (view, offset, string) => {
    for (let i = 0; i < string.length; i++) {
      view.setUint8(offset + i, string.charCodeAt(i));
    }
  };

  // WAV header
  // "RIFF" chunk descriptor
  writeString(view, 0, 'RIFF');
  view.setUint32(4, 36 + dataSize, true);
  writeString(view, 8, 'WAVE');
  
  // "fmt " sub-chunk
  writeString(view, 12, 'fmt ');
  view.setUint32(16, 16, true); // fmt chunk size
  view.setUint16(20, 1, true); // audio format (PCM)
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, bytesPerSample * 8, true); // bits per sample
  
  // "data" sub-chunk
  writeString(view, 36, 'data');
  view.setUint32(40, dataSize, true);
  
  // Write audio data
  let offset = 44;
  for (let i = 0; i < data.length; i++, offset += 2) {
    const s = Math.max(-1, Math.min(1, data[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
  }
  
  return new Blob([buffer], { type: 'audio/wav' });
};
