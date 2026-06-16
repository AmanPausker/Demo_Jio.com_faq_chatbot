# Acoustic Echo Cancellation (AEC) Architecture

One of the most challenging aspects of a real-time, full-duplex voice assistant is preventing the bot's synthesized speech from being picked up by the user's microphone. When the bot's own voice loops back into the microphone, it can trigger the Voice Activity Detection (VAD) and cause the bot to transcribe and respond to its own words, resulting in an infinite feedback loop.

## How We Solved the Echo Problem

To solve this, we migrated our audio pipeline from a raw WebSocket/PCM chunking approach (using `expo-av`) to a **WebRTC-native pipeline** using `react-native-webrtc`.

### 1. Hardware-Level Echo Cancellation
WebRTC inherently ties into the native operating system's audio mixer (both iOS CoreAudio and Android AudioRecord/AudioTrack APIs). When we request the microphone stream, we explicitly enable AEC and Noise Suppression constraints:

```typescript
// mobile_app/src/app/(app)/live.tsx
const stream = await mediaDevices.getUserMedia({ 
  audio: { 
    echoCancellation: true, 
    noiseSuppression: true 
  }, 
  video: false 
});
```

By setting `echoCancellation: true`, the mobile device's DSP (Digital Signal Processor) mathematically subtracts the exact acoustic waveform that is playing out of the speaker from the waveform being recorded by the microphone. 

### 2. Unified WebRTC PeerConnection
Because we are streaming the TTS (Text-to-Speech) audio from `server.py` back down to the React Native app using the **exact same `RTCPeerConnection`** that is transmitting the microphone audio, the WebRTC engine is fully aware of what audio is being played.

- **Previous approach (WebSocket):** The microphone recorded raw PCM audio via `expo-av`, while the WebSocket pushed base64 encoded audio to be played by the speaker independently. The microphone had no awareness of the speaker's output, leading to severe echo.
- **Current approach (WebRTC):** The `TTSAudioTrack` on the Python server sends RTP packets to the mobile app. The WebRTC engine plays these packets out of the speaker *while* simultaneously using them as the reference signal for the microphone's AEC filter.

### 3. Server-Side VAD Resilience
As a secondary layer of defense, our server-side VAD (`silero-vad` or energy-based thresholding in `server.py`) is much less likely to be triggered by faint background noise. Because the WebRTC AEC suppresses the bot's voice by >30dB locally on the phone, any residual "leakage" that makes it back to the server falls well below our Voice Activity Detection threshold.

## Summary

By leveraging WebRTC's native hardware integration rather than manual WebSocket audio chunks, we successfully eliminated the speaker-to-microphone feedback loop with zero additional JavaScript or Python filtering required.
