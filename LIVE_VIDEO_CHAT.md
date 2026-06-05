# Live Video Chat — Implementation & Data Flow

## Overview

The live video chat feature (inspired by Gemini Live) enables a real-time voice + camera conversation with an AI assistant. The user's camera feed and microphone are continuously streamed to the backend, which performs STT, vision analysis, LLM reasoning, and TTS — all over a single persistent WebSocket connection.

---

## Architecture

```
┌──────────────────────┐      ┌─────────────────────────────────────┐
│   Mobile App (Expo)  │      │   Web App (React)                   │
│                      │      │                                     │
│  ┌────────────────┐  │      │  ┌─────────────────┐               │
│  │ expo-camera    │  │      │  │ getUserMedia     │               │
│  │ (CameraView)   │  │      │  │ (WebRTC)         │               │
│  │ 0.5 FPS JPEG   │  │      │  │ ~1 FPS JPEG      │               │
│  └───────┬────────┘  │      │  └──────┬───────────┘               │
│          │           │      │         │                            │
│  ┌───────┴────────┐  │      │  ┌──────┴───────────┐               │
│  │ expo-av        │  │      │  │ ScriptProcessor   │               │
│  │ Recording      │  │      │  │ PCM 16kHz chunks  │               │
│  │ 1.5s WAV files │  │      │  │ ~40ms intervals   │               │
│  └───────┬────────┘  │      │  └──────┬───────────┘               │
│          │           │      │         │                            │
└──────────┼───────────┘      └─────────┼───────────────────────────┘
           │                            │
           │  WebSocket (WSS)           │  WebSocket (WSS)
           │  audio_file_full (WAV)     │  audio_chunk (PCM stream)
           │  video_frame (JPEG)        │  video_frame (JPEG)
           │  interrupt                 │  interrupt
           │                            │
           ▼                            ▼
┌───────────────────────────────────────────────────────────────────┐
│                     FastAPI Backend (server.py)                    │
│                                                                   │
│  WebSocket: /api/live/ws                                          │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │                  Session Manager                              │  │
│  │  (in-memory dict, keyed by session_id)                       │  │
│  │                                                               │  │
│  │  Per Session State (Session class):                          │  │
│  │    frame_buffer: deque[str] (maxlen=5) — base64 JPEG frames  │  │
│  │    audio_buffer: bytearray — rolling PCM bytes               │  │
│  │    vad_iterator: Silero VAD iterator                         │  │
│  │    vad_sample_buffer: list[float] — normalized PCM samples   │  │
│  │    conversation_history: list[dict] — {role, content} pairs  │  │
│  │    world_state: dict — objects, people, text_seen, events    │  │
│  │    cached_visual_desc: str — latest vision analysis          │  │
│  │    cached_visual_hashes: tuple — MD5 region hashes           │  │
│  │    is_processing: bool — guards against concurrent questions │  │
│  │    last_activity_time: float — for TTL cleanup (600s)        │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                               │                                   │
│  ┌────────────────────────────┴──────────────────────────────┐   │
│  │                    Audio Pipeline                          │   │
│  │                                                           │   │
│  │  Mobile: audio_file_full (complete WAV)                   │   │
│  │    → decode base64 → Sarvam REST STT (transcribe_audio)   │   │
│  │                                                           │   │
│  │  Web: audio_chunk (streaming PCM packets)                 │   │
│  │    → accumulate in audio_buffer + vad_sample_buffer        │   │
│  │    → VAD on every chunk (Silero, threshold 0.5)           │   │
│  │    → on speech_end → Sarvam STT (transcribe_pcm)          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                               │                                   │
│  ┌────────────────────────────┴──────────────────────────────┐   │
│  │                    Video Pipeline                          │   │
│  │                                                           │   │
│  │  video_frame → appended to frame_buffer (deque maxlen=5)  │   │
│  │                                                           │   │
│  │  Background vision analysis (analyze_scene_background):   │   │
│  │    Runs when user speaks, min 3s interval                 │   │
│  │    1. Multi-region MD5 hash (top/mid/bottom)              │   │
│  │    2. If scene changed:                                   │   │
│  │       → Send latest frame to ChatNVIDIA Llama 3.2 11B    │   │
│  │       → Update world_state (objects, people, events)      │   │
│  │       → Update cached_visual_desc                         │   │
│  └──────────────────────────────────────────────────────────┘   │
│                               │                                   │
│  ┌────────────────────────────┴──────────────────────────────┐   │
│  │                 Question Handler (handle_user_question)    │   │
│  │                                                           │   │
│  │  1. Build prompt (build_live_prompt):                     │   │
│  │     System prompt + world_state + cached visual desc      │   │
│  │     + recent conversation + user question                 │   │
│  │                                                           │   │
│  │  2. Vision check (needs_visual_context):                  │   │
│  │     If question references visuals ("what is", "look")    │   │
│  │     and cached desc is stale → fresh vision LLM call      │   │
│  │     (sends filler TTS like "Let me look..." during wait)  │   │
│  │                                                           │   │
│  │  3. LLM (primary_llm — Llama 3.1 8B via NVIDIA):         │   │
│  │     → Generate text response                              │   │
│  │                                                           │   │
│  │  4. Output:                                               │   │
│  │     → assistant_response (text) via WebSocket             │   │
│  │     → tts_chunk (streaming WAV) via Sarvam bulbul:v3      │   │
│  └──────────────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────────────┘
```

---

## WebSocket Protocol

### Connection
```
ws://<host>:8000/api/live/ws
```
First message **must** be authentication:
```json
{
  "type": "auth",
  "payload": {
    "token": "<supabase_jwt>",
    "session_id": "<client_generated_uuid>"
  }
}
```
The backend verifies the JWT via `supabase.auth.get_user(token)`.

### Client → Server Events

| Event | Payload | Sent By | Description |
|-------|---------|---------|-------------|
| `auth` | `{ token, session_id }` | Both | Authentication (first message) |
| `audio_chunk` | `string` (base64 PCM) | **Web only** | Continuous PCM 16-bit 16kHz chunks |
| `audio_file` | `string` (base64 WAV) | **Web only** | WAV file decoded via ffmpeg to PCM |
| `audio_file_full` | `string` (base64 WAV) | **Mobile only** | Complete utterance WAV, sent on silence |
| `video_frame` | `string` (base64 JPEG) | Both | Camera frame (mobile: 0.5 FPS, web: 1 FPS) |
| `transcript` | `string` | Both | Text query (skip audio pipeline) |
| `interrupt` | (none) | Both | User started speaking — stop AI playback |

### Server → Client Events

| Event | Payload | Description |
|-------|---------|-------------|
| `transcript` | `string` | User's transcribed speech from STT |
| `assistant_response` | `string` | AI's text answer |
| `tts_chunk` | `string` (base64 WAV) | Chunked TTS audio for streaming playback |
| `interrupt_ack` | (none) | Acknowledged interruption |
| `error` | `string` | Error description |

---

## Mobile Client (`live.tsx`) — Detailed Flow

### Startup
```
Screen mounts (useFocusEffect)
  → Reset messages, create new session_id
  → Get Supabase session → construct WS URL
  → Open WebSocket
  → On open:
      1. Send auth message
      2. Start video loop (setInterval 2000ms):
           cameraRef.takePictureAsync({ base64: true, quality: 0.1 })
           → ws.send({ type: "video_frame", payload: base64 })
      3. Start audio recording:
           Audio.Recording.createAsync(HIGH_QUALITY, onMetering, 100ms)
```

### Voice Activity Detection (VAD)
```
handleMetering(db):
  ├── db > -20 dB (user is speaking):
  │     - Clear silence timer
  │     - If was silent → stop AI TTS playback (barge-in)
  │     - Send { type: "interrupt" }
  │     - Set isSpeakingState = true
  │
  └── db <= -20 dB (silence):
        If was speaking and no timeout running:
          → Start 1500ms timeout
          → On timeout: handleSpeechEnd()
              → stopAndUnloadAsync()
              → read WAV file → readAsStringAsync(uri, base64)
              → ws.send({ type: "audio_file_full", payload: base64 })
              → restart audio recording (startStreamingAudio)
```

### TTS Playback Queue
```
ws.onmessage tts_chunk → push to ttsQueueRef
playNextTTS():
  ├── If already playing or queue empty → return
  ├── Shift first chunk
  ├── Audio.Sound.createAsync({ uri: data:audio/wav;base64,... })
  ├── On didJustFinish → unload → playNextTTS()
```

### Cleanup
```
Screen unmounts:
  → Clear frame interval
  → Close WebSocket
  → Stop + unload recording
  → Unload sound
```

---

## Backend Session (`Session` class) — All Stored Data

### In-Memory (per session)

| Field | Type | Purpose |
|-------|------|---------|
| `session_id` | `str` | Unique session identifier |
| `user_id` | `str` | Supabase user ID |
| `frame_buffer` | `deque[str]` (maxlen=5) | Last 5 JPEG frames (base64), 0.5 FPS = ~10s window |
| `conversation_history` | `list[dict]` | All {role, content} exchanges during session |
| `world_state` | `dict` | Structured understanding of the visual scene: `{objects: {}, people: {}, text_seen: {}, recent_events: []}` |
| `audio_buffer` | `bytearray` | Rolling PCM byte buffer for VAD-based STT |
| `vad_sample_buffer` | `list[float]` | Normalized PCM samples for Silero VAD |
| `vad_iterator` | `VADIterator` | Silero VAD state machine instance |
| `cached_visual_desc` | `str` | Last vision LLM description of the scene |
| `cached_visual_time` | `float` | Timestamp of cached visual desc |
| `cached_visual_hashes` | `tuple` | MD5 region hashes of cached frame |
| `last_region_hashes` | `tuple` | Hashes of most recently analyzed frame |
| `last_analysis_time` | `float` | Last background vision analysis time |
| `is_analyzing_vision` | `bool` | Guard flag (prevents concurrent vision calls) |
| `is_processing` | `bool` | Guard flag (prevents concurrent question handling) |
| `last_activity_time` | `float` | Used for TTL-based stale session cleanup (600s) |

### Supabase (persistent)

| Table | Data Stored | When Written |
|-------|-------------|-------------|
| `chat_sessions` | `id` (UUID), `user_id`, `title`, `created_at` | Created when first text/audio message is sent (not in live WS — live uses server-side session only) |
| `user_memory` | `user_id`, `facts` (jsonb) | Set by memory-related queries |

**Live video chat data is NOT persisted to any database.** The entire session (frames, conversation, world state) exists only in the in-memory `ConnectionManager.sessions` dict. When the WebSocket disconnects, the session remains in memory for 600s (cleanup TTL), then is discarded. Nothing from the live video chat is saved to Supabase, Neo4j, Qdrant, or SQLite.

If the user asks a question that triggers the LangGraph-based FAQ pipeline (via the text chat), those conversations ARE persisted in SQLite (`checkpoints.db`) for checkpointing, and in Supabase (`chat_sessions`).

---

## Key Backend Functions

| Function | File:Line | Purpose |
|----------|-----------|---------|
| `live_chat_websocket()` | server.py:740 | WebSocket endpoint, event dispatcher |
| `Session.__init__()` | server.py:395 | Initialize per-session state |
| `ConnectionManager.get_session()` | server.py:430 | Get or create session |
| `ConnectionManager.start_cleanup()` | server.py:436 | Background task, removes stale sessions every 120s |
| `process_audio_chunk()` | server.py:697 | PCM chunk → VAD → STT on speech end |
| `analyze_scene_background()` | server.py:481 | Background vision: scene change → LLM update |
| `scene_changed()` | server.py:462 | Multi-region MD5 hash comparison |
| `handle_user_question()` | server.py:621 | Process query: build prompt → vision check → LLM → TTS |
| `build_live_prompt()` | server.py:578 | Construct prompt from session state |
| `needs_visual_context()` | server.py:543 | Keyword-based check if question needs live camera analysis |
| `_send_tts_filler()` | server.py:610 | Send filler TTS ("Let me look...") during vision latency |

---

## Data Flow Diagrams

### Audio Flow (Mobile)
```
Microphone → expo-av Recording → WAV file on disk
  → Speech end (VAD) → readAsStringAsync(base64)
  → WebSocket { type: "audio_file_full", payload }
  → Backend: base64 decode → transcribe_audio_file()
    → Sarvam REST STT → transcript text
  → WebSocket { type: "transcript", payload }
  → handle_user_question()
    → Vision check → (optional) vision LLM → LLM → TTS
  → WebSocket { type: "assistant_response" }
  → WebSocket { type: "tts_chunk" } × N
  → Mobile: Audio.Sound queue sequential playback
```

### Audio Flow (Web)
```
Microphone → getUserMedia → AudioContext → ScriptProcessorNode
  → PCM 16kHz chunks every ~40ms
  → WebSocket { type: "audio_chunk", payload: base64 }
  → Backend: accumulate in audio_buffer
    → Silero VAD on each chunk
    → Speech end detected → transcribe_pcm() → Sarvam STT
  → (same as mobile from here)
```

### Video Flow
```
Camera → takePictureAsync() / ImageCapture
  → JPEG base64 (quality 0.1)
  → WebSocket { type: "video_frame", payload } every 2s
  → Backend: append to frame_buffer deque(maxlen=5)
  
  Background (triggered when user speaks):
    → scene_changed() — 3-region MD5 hash
    → If changed → ChatNVIDIA Llama 3.2 11B Vision
    → Update world_state + cached_visual_desc

  On question (if needs visual context):
    → Use cached_visual_desc if fresh (<10s)
    → Or fresh vision LLM call (async with filler TTS)
    → Inject into prompt → LLM response
```

### Interrupt Flow
```
User starts speaking (VAD triggers)
  → Mobile: { type: "interrupt" }
  → Web: { type: "interrupt" }
  → Backend: session.is_processing = false
    → { type: "interrupt_ack" }
  → Backend ignores previous TTS generation
  → Mobile: stops current TTS playback
```

---

## Latency Considerations

| Stage | Target | Implementation |
|-------|--------|---------------|
| VAD detection | Real-time | Volume threshold (-20dB), 100ms polling |
| Audio transmission | Batch ~1.5s | Mobile sends full WAV on speech end; Web streams raw PCM |
| STT | <1s | Sarvam saaras:v3 (REST for files, SDK for streaming) |
| Scene change detection | <50ms | MD5 region hashing (no ML overhead) |
| Vision LLM | 2-4s | Llama 3.2 11B Vision via NVIDIA — runs async, filler TTS masks latency |
| Primary LLM | 1-2s | Llama 3.1 8B via NVIDIA |
| TTS streaming | <500ms first chunk | Sarvam bulbul:v3 async generator, chunked |
| Video capture | 0.5 FPS (mobile) | 2s interval, quality 0.1 to minimize bandwidth |

---

## Files Involved

| File | Role |
|------|------|
| `mobile_app/src/app/(app)/live.tsx` | Mobile live camera screen (351 lines) |
| `mobile_app/src/app/(app)/chat.tsx` | Entry point to live, voice VAD mode (877 lines) |
| `server.py` | WebSocket endpoint, Session, VAD, vision, LLM, TTS (830 lines) |
| `get_transcript.py` | Sarvam STT — `transcribe_pcm()`, `transcribe_audio_file()` |
| `get_audio.py` | Sarvam TTS — `generate_speech_stream()` |
| `frontend/src/App.jsx` | Web live mode with WebRTC audio + camera |
| `video_search.md` | Full architecture specification (1098 lines) |
