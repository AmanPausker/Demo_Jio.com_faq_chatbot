# Gemini Live Clone — Adapted for Current Stack

Real-time voice + camera chat where the assistant continuously sees through the camera and answers questions about the live feed, with full voice conversation.

---

## Architecture

```
┌──────────────────────────────────┐    ┌────────────────────────────────────┐
│        React Web App             │    │     Expo React Native (Mobile)    │
│  ┌──────────┐  ┌───────────┐    │    │  ┌──────────┐  ┌───────────────┐  │
│  │ Microphone│  │ Camera    │    │    │  │ Microphone│  │ Camera        │  │
│  │ (WebRTC)  │  │(getUser   │    │    │  │ (expo-av) │  │ (expo-camera) │  │
│  │           │  │  Media)   │    │    │  │           │  │               │  │
│  └─────┬─────┘  └─────┬─────┘    │    │  └─────┬─────┘  └───────┬───────┘  │
│        │               │         │    │        │                │          │
└────────┼───────────────┼─────────┘    └────────┼────────────────┼──────────┘
         │               │                       │                │
         │ WebSocket     │ WebSocket              │ HTTP upload    │ WebSocket
         │ (PCM stream)  │ (JPEG frame)           │ (1.5s .wav     │ (JPEG frame)
         ▼               ▼                       │  micro-files)  ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                         FastAPI Backend                                     │
│                                                                            │
│  ┌────────────────────────────────────────────┐                            │
│  │         WebSocket Connection Manager        │                            │
│  │  - /api/live/ws (web : PCM streaming)      │                            │
│  │  - /api/live/upload_audio (mobile : files) │                            │
│  └────────────────┬───────────────────────────┘                            │
│                   │                                                         │
│  ┌────────────────┴──────────────────────────────────────────┐             │
│  │                    Session Manager                         │             │
│  │  Per-user:                                                 │             │
│  │  - frame_buffer: deque(maxlen=10)                          │             │
│  │  - audio_ring_buffer: bytearray (rolling PCM, ~5s max)    │             │
│  │  - conversation_history: list                              │             │
│  │  - visual_summary: str                                     │             │
│  │  - last_vad_time: float                                    │             │
│  └────────────────┬───────────────────────────────────────────┘             │
│                   │                                                         │
│  ┌────────────────┴──────────┐  ┌─────────────────────────┐               │
│  │    STT Pipeline           │  │   Frame Buffer          │               │
│  │                           │  │   (deque, maxlen=10,    │               │
│  │  Ring buffer → VAD        │  │    640x360 JPEG)        │               │
│  │  (Silero / energy-based)  │  │                         │               │
│  │       ↓                   │  │  Scene change detection │               │
│  │  On silence: send to      │  │  (hash compare)         │               │
│  │  Sarvam STT (saaras:v3)   │  │                         │               │
│  └────────────────┬──────────┘  └────────────┬────────────┘               │
│                   │                          │                             │
│                   ▼                          ▼                             │
│  ┌─────────────────────────────────────────────────────────────────┐      │
│  │              Multimodal Prompt Builder                           │      │
│  │  - Latest transcript (from STT)                                 │      │
│  │  - Visual summary (periodic, every 5-10s)                       │      │
│  │  - Recent frames (included only when question needs vision)     │      │
│  │  - Conversation history (last 4-6 exchanges)                    │      │
│  └──────────────────────────┬──────────────────────────────────────┘      │
│                             │                                             │
│  ┌──────────────────────────┴──────────┐                                  │
│  │  Vision LLM (Cloudflare Kimi K2.6)  │   Only when question needs it    │
│  └──────────────────────────┬──────────┘                                  │
│                             │                                             │
│  ┌──────────────────────────┴──────────┐                                  │
│  │  LLM Response (Cerebras/Groq)       │                                  │
│  └──────────────────────────┬──────────┘                                  │
│                             │                                             │
│  ┌──────────────────────────┴──────────┐                                  │
│  │  TTS (Sarvam bulbul:v3)             │   Stream chunks                  │
│  └──────────────────────────┬──────────┘                                  │
│                             │                                             │
└─────────────────────────────┼──────────────────────────────────────────────┘
                              │
               ┌──────────────┴──────────────┐
               │ WebSocket (TTS audio chunks) │
               │ OR HTTP response             │
               ▼                              ▼
     ┌──────────────┐            ┌──────────────────┐
     │ React Client │            │ Expo Mobile App  │
     │ Audio player │            │ expo-av playback │
     └──────────────┘            └──────────────────┘
```

---

## 1. WebSocket Protocol

A single persistent WebSocket connection handles bidirectional streaming.

### Events (Client → Server)

| Event | Payload | Frequency | Client |
|-------|---------|-----------|--------|
| `audio_chunk` | PCM 16-bit 16kHz bytes (base64) | ~40ms intervals | Web (WebRTC) |
| `audio_file` | Base64 WAV bytes (~1.5s) | Every ~1.5s | Mobile (Expo) |
| `video_frame` | Base64 JPEG (640x360, 60-70% quality) | Every 500-1000ms | Both |
| `transcript` | String text | When STT produces result | Both |
| `interrupt` | None | User starts speaking | Both |

### Events (Server → Client)

| Event | Payload | Description |
|-------|---------|-------------|
| `assistant_response` | Text string | Streamed tokens |
| `tts_chunk` | Base64 WAV bytes | Streamed audio |
| `visual_summary` | Text string | Periodic scene description |
| `error` | String | Error message |

---

## 2. WebSocket Manager (`server.py`)

### Connection Handler

```python
import asyncio
import json
import base64
import uuid
from collections import deque
from fastapi import WebSocket, WebSocketDisconnect, Depends

class Session:
    def __init__(self, session_id: str, user_id: str):
        self.session_id = session_id
        self.user_id = user_id
        self.frame_buffer: deque = deque(maxlen=10)
        self.audio_ring_buffer = AudioRingBuffer(max_duration_seconds=5.0)
        self.transcript_buffer: list = []
        self.conversation_history: list = []
        self.visual_summary: str = ""
        self.last_frame_hash: str = ""
        self.is_processing: bool = False

class AudioRingBuffer:
    """Rolling PCM buffer that accumulates audio chunks from both
    WebSocket streaming (web) and HTTP file uploads (mobile),
    and triggers STT when voice activity stops."""

    def __init__(self, max_duration_seconds: float = 5.0,
                 sample_rate: int = 16000,
                 silence_timeout_ms: int = 800):
        self.max_samples = int(max_duration_seconds * sample_rate)
        self.sample_rate = sample_rate
        self.silence_timeout_ms = silence_timeout_ms
        self.buffer = bytearray()
        self.last_voice_time = 0.0
        self.is_speaking = False
        self._lock = asyncio.Lock()

    async def append_pcm(self, pcm_bytes: bytes):
        async with self._lock:
            # Trim to max_samples if overflowing
            if len(self.buffer) + len(pcm_bytes) > self.max_samples * 2:
                excess = len(self.buffer) + len(pcm_bytes) - self.max_samples * 2
                self.buffer = self.buffer[excess:]
            self.buffer.extend(pcm_bytes)
            self.last_voice_time = asyncio.get_event_loop().time()
            self.is_speaking = True

    async def check_silence(self) -> Optional[bytes]:
        """If silence detected since last voice, return accumulated PCM and reset."""
        async with self._lock:
            if not self.is_speaking:
                return None
            now = asyncio.get_event_loop().time()
            elapsed = (now - self.last_voice_time) * 1000
            if elapsed > self.silence_timeout_ms and len(self.buffer) > 0:
                snapshot = bytes(self.buffer)
                self.buffer.clear()
                self.is_speaking = False
                return snapshot
        return None

class ConnectionManager:
    def __init__(self):
        self.sessions: dict[str, Session] = {}

    def get_session(self, session_id: str, user_id: str) -> Session:
        if session_id not in self.sessions:
            self.sessions[session_id] = Session(session_id, user_id)
        return self.sessions[session_id]

manager = ConnectionManager()
```

### WebSocket Endpoint

```python
from pydantic import BaseModel

@server.websocket("/api/live/ws")
async def live_chat_websocket(websocket: WebSocket):
    await websocket.accept()

    # Auth via first message
    auth_data = await websocket.receive_json()
    token = auth_data.get("token", "")
    session_id = auth_data.get("session_id", str(uuid.uuid4()))
    user_id = auth_data.get("user_id", "")

    # Verify token
    try:
        user_response = supabase.auth.get_user(token)
        user_id = user_response.user.id
    except Exception:
        await websocket.send_json({"type": "error", "payload": "Authentication failed"})
        await websocket.close()
        return

    session = manager.get_session(session_id, user_id)

    # Start background tasks
    asyncio.create_task(periodic_visual_summary(session, websocket))
    asyncio.create_task(silence_detection_loop(session, websocket))

    try:
        while True:
            data = await websocket.receive_json()
            event_type = data.get("type")
            payload = data.get("payload")

            if event_type == "audio_chunk":
                # Web: raw PCM streamed over WebSocket
                pcm_bytes = base64.b64decode(payload) if isinstance(payload, str) else payload
                await session.audio_ring_buffer.append_pcm(pcm_bytes)
                # Check for silence in the background loop
                transcript = await session.audio_ring_buffer.check_silence()
                if transcript is not None:
                    asyncio.create_task(process_audio_segment(session, transcript, websocket))

            elif event_type == "audio_file":
                # Mobile: pre-encoded WAV file (~1.5s), decode to PCM
                wav_bytes = base64.b64decode(payload) if isinstance(payload, str) else payload
                pcm_bytes = decode_wav_to_pcm(wav_bytes)
                await session.audio_ring_buffer.append_pcm(pcm_bytes)
                transcript = await session.audio_ring_buffer.check_silence()
                if transcript is not None:
                    asyncio.create_task(process_audio_segment(session, transcript, websocket))

            elif event_type == "video_frame":
                # Store frame
                session.frame_buffer.append(payload)
                # Optional: scene change detection
                # current_hash = hash(payload[:1000])
                # if current_hash != session.last_frame_hash:
                #     session.frame_buffer.append(payload)
                #     session.last_frame_hash = current_hash

            elif event_type == "transcript":
                # User sent a text question (or STT produced final transcript)
                await handle_user_question(session, payload, websocket)

            elif event_type == "interrupt":
                # User interrupted the assistant
                session.is_processing = False
                await websocket.send_json({"type": "interrupt_ack"})

    except WebSocketDisconnect:
        # Cleanup (session persists in memory for reconnect)
        pass
```

### Silence Detection Background Loop

```python
async def silence_detection_loop(session: Session, websocket: WebSocket):
    """Periodically check if the user stopped speaking."""
    while True:
        await asyncio.sleep(0.3)  # Check every 300ms
        pcm = await session.audio_ring_buffer.check_silence()
        if pcm is not None:
            asyncio.create_task(process_audio_segment(session, pcm, websocket))
```

### Mobile HTTP Endpoint: `POST /api/live/upload_audio`

For the mobile client, the WebSocket stays open for frames + events, but audio arrives as HTTP file uploads. This endpoint receives a 1.5s WAV file and injects it into the same session's ring buffer.

```python
@server.post("/api/live/upload_audio")
async def upload_live_audio(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    user_id: str = Depends(get_current_user)
):
    wav_bytes = await file.read()
    pcm_bytes = decode_wav_to_pcm(wav_bytes)

    session = manager.get_session(session_id, user_id)
    await session.audio_ring_buffer.append_pcm(pcm_bytes)

    # Trigger silence check immediately
    pcm = await session.audio_ring_buffer.check_silence()
    if pcm is not None:
        # Must get transcript back to the mobile client
        # Option: STT here synchronously and return transcript
        from get_transcript import transcribe_pcm
        try:
            transcript = await transcribe_pcm(pcm)
            if transcript and transcript.strip():
                return {"transcript": transcript}
        except Exception as e:
            return {"error": str(e)}

    return {"status": "buffered"}
```

However, this approach has a problem — the mobile client needs to receive the assistant's answer back. Two approaches:

**Option A: WebSocket answer channel** (recommended)
- Keep the WebSocket open for receiving events
- Mobile sends audio via HTTP POST (multipart/form-data)
- Backend processes it, and sends `assistant_response` + `tts_chunk` events back through the WebSocket
- The mobile client's WebSocket `onmessage` handler plays TTS and shows text

**Option B: Long-polling answer**
- After upload, mobile polls `GET /api/live/poll?session_id=X`
- Returns pending answers

**Option A is preferred** since the WebSocket is already open for video frames + events.

### `get_transcript.py`: Add `transcribe_pcm()`

```python
async def transcribe_pcm(pcm_bytes: bytes, sample_rate: int = 16000) -> str:
    """Transcribe raw PCM 16-bit mono audio using Sarvam AI REST API.

    Unlike listen_for_speech() which uses WebSocket streaming,
    this sends a complete audio segment at once — suitable for
    both web (VAD-triggered) and mobile (micro-file) pipelines.
    """
    import aiohttp
    import os
    import base64

    api_key = os.getenv("SARVAM_API_KEY")
    url = "https://api.sarvam.ai/speech-to-text"

    # Encode as base64 WAV
    import wave
    import io
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm_bytes)
    wav_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')

    payload = {
        "audio": {"content": wav_b64},
        "model": "saaras:v3",
        "language_code": "hi-IN",
        "with_timestamps": False,
        "with_diarization": False,
        "num_speakers": 1
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload,
                                headers={"api-subscription-key": api_key}) as resp:
            data = await resp.json()
            transcript = data.get("transcript", "").strip()
            return transcript
```

### Decode WAV to PCM (Mobile Files)

```python
import wave
import io

def decode_wav_to_pcm(wav_bytes: bytes) -> bytes:
    """Extract raw PCM 16-bit 16kHz mono from a WAV byte buffer."""
    with wave.open(io.BytesIO(wav_bytes), 'rb') as wav:
        assert wav.getnchannels() == 1, "Expected mono"
        assert wav.getsampwidth() == 2, "Expected 16-bit"
        # Resample if needed (simplified — assume 16kHz from mobile)
        return wav.readframes(wav.getnframes())
```

### Process Audio Segment → STT

When silence is detected (by `AudioRingBuffer`), the accumulated PCM is sent to Sarvam STT.

```python
async def process_audio_segment(session: Session, pcm_bytes: bytes, websocket: WebSocket):
    """Send accumulated PCM to Sarvam STT and handle the transcript."""
    from get_transcript import transcribe_pcm

    if len(pcm_bytes) < 1600:  # <100ms of audio = noise
        return

    try:
        transcript = await transcribe_pcm(pcm_bytes)
        if transcript and transcript.strip():
            await handle_user_question(session, transcript.strip(), websocket)
    except Exception as e:
        print(f"STT failed: {e}")
```

---

## 3. Visual Processing

### Frame Buffer

```python
# In session:
self.frame_buffer: deque = deque(maxlen=10)
```

- Stores last 10 frames as base64 JPEG
- Max 10 seconds of visual context at 1 FPS
- Never stores full video

### Scene Change Detection (Cost Optimization)

```python
import hashlib

def scene_changed(frame_b64: str, last_hash: str, threshold: int = 5000) -> tuple[bool, str]:
    """Compare frame hash to detect significant scene changes."""
    # Use first N bytes as a quick perceptual hash
    current_hash = hashlib.md5(frame_b64[:threshold].encode()).hexdigest()
    changed = current_hash != last_hash
    return changed, current_hash
```

Only call Vision LLM when scene actually changes or user asks a question.

### Periodic Visual Summary

Every 5-10 seconds, describe what the camera sees (used to avoid sending frames with every question).

```python
async def periodic_visual_summary(session: Session, websocket: WebSocket):
    """Every 5s, generate a brief visual summary from recent frames."""
    while True:
        await asyncio.sleep(5)
        if not session.frame_buffer or session.is_processing:
            continue

        # Only update if scene changed
        # (omitted: scene change detection logic)

        # Send latest frame to Vision LLM for summary
        latest_frame = session.frame_buffer[-1]

        summary = await generate_visual_summary(latest_frame)

        if summary and summary != session.visual_summary:
            session.visual_summary = summary
            await websocket.send_json({
                "type": "visual_summary",
                "payload": summary
            })
```

### Vision LLM Call

Uses existing Cloudflare Kimi K2.6:

```python
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

kimi_vision_llm = ChatOpenAI(
    api_key=WORKERS_API_KEY,
    base_url=f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFARE_ID}/ai/v1",
    model="@cf/moonshotai/kimi-k2.6",
    max_tokens=500
)

async def generate_visual_summary(frame_b64: str) -> str:
    """Describe the current scene concisely."""
    message = HumanMessage(content=[
        {
            "type": "text",
            "text": "Describe this scene in 1-2 sentences. Include key objects, people, text, and the setting."
        },
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{frame_b64}",
                "detail": "low"
            }
        }
    ])
    try:
        response = await kimi_vision_llm.ainvoke([message])
        return response.content.strip()
    except Exception as e:
        print(f"Visual summary failed: {e}")
        return ""
```

---

## 4. Conversation Flow

### Handling a User Question

When the user asks something (either via text or transcribed speech):

```python
async def handle_user_question(session: Session, question: str, websocket: WebSocket):
    session.is_processing = True
    session.conversation_history.append({"role": "user", "content": question})

    # 1. Check if question needs the camera
    needs_vision = needs_visual_context(question)

    # 2. Build prompt
    prompt = build_live_prompt(session, question, needs_vision)

    # 3. Generate response
    if needs_vision and session.frame_buffer:
        # Include frames in the LLM call
        response = await generate_with_vision(session, prompt, question)
    else:
        # Use existing LangGraph general generation (Cerebras/Groq)
        response = await generate_text_only(session, prompt)

    session.conversation_history.append({"role": "assistant", "content": response})

    # 4. Stream response text
    await websocket.send_json({
        "type": "assistant_response",
        "payload": response
    })

    # 5. Stream TTS audio
    await stream_tts(response, websocket)

    session.is_processing = False
```

### Needs Visual Context?

```python
def needs_visual_context(question: str) -> bool:
    """Determine if the question requires looking at the camera feed."""
    visual_keywords = [
        "what is", "what's", "what are", "what does",
        "what do", "can you see", "look at", "this",
        "that", "these", "those", "read", "tell me about",
        "describe", "what color", "how many", "what kind",
        "what type", "is there", "are there", "do you see",
        "what does it", "what does this", "what's that",
        "who is", "whose"
    ]
    q = question.lower().strip()
    return any(keyword in q for keyword in visual_keywords)
```

### Build Multimodal Prompt

```python
def build_live_prompt(session: Session, question: str, needs_vision: bool) -> str:
    parts = []

    # System preamble
    parts.append(
        "You are a live visual assistant. You can see through the user's camera. "
        "Answer naturally and conversationally. Be concise."
    )

    # Visual summary (always included to reduce frame calls)
    if session.visual_summary:
        parts.append(f"Current visual context: {session.visual_summary}")

    # Recent conversation (last 4 exchanges)
    recent = session.conversation_history[-8:]  # 4 turns = 8 messages
    if recent:
        parts.append("Recent conversation:")
        for msg in recent:
            prefix = "User" if msg["role"] == "user" else "Assistant"
            parts.append(f"{prefix}: {msg['content']}")

    # Current question
    parts.append(f"Current question: {question}")

    return "\n\n".join(parts)
```

### Generate With Vision

```python
from langchain_cerebras import ChatCerebras
from langchain_groq import ChatGroq

llm = ChatCerebras(model="gpt-oss-120b", api_key=os.getenv("CEREBRAS_API_KEY"))

async def generate_with_vision(session: Session, prompt: str, question: str) -> str:
    """Send latest frames + question to Vision LLM, then refine with text LLM."""
    # Step 1: Get visual description from Vision LLM (cheaper than sending all frames to big LLM)
    latest_frame = session.frame_buffer[-1]
    visual_desc = await query_vision_llm(question, latest_frame)

    # Step 2: Build final prompt for text LLM
    final_prompt = f"""{prompt}

Visual analysis of camera feed:
{visual_desc}

Answer the user's question naturally based on what you see."""
    messages = [
        {"role": "system", "content": "You are a helpful live visual assistant. Answer concisely."},
        {"role": "user", "content": final_prompt}
    ]
    try:
        response = await llm.ainvoke(messages)
        return response.content
    except Exception as e:
        # Fallback to Groq
        groq = ChatGroq(model="llama-3.1-8b-instant", api_key=os.getenv("GROQ_API_KEY"))
        response = await groq.ainvoke(messages)
        return response.content

async def query_vision_llm(question: str, frame_b64: str) -> str:
    """Ask Kimi K2.6 about the frame."""
    message = HumanMessage(content=[
        {"type": "text", "text": f"The user is asking: '{question}'. Answer based on what you see in the image. Be specific and concise."},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{frame_b64}", "detail": "high"}}
    ])
    try:
        response = await kimi_vision_llm.ainvoke([message])
        return response.content.strip()
    except Exception as e:
        return f"[Vision unavailable: {e}]"
```

### Generate Text-Only (No Vision Needed)

For follow-ups like "how often should I water it?" — no frames needed.

```python
async def generate_text_only(session: Session, prompt: str) -> str:
    """Use Cerebras/Groq with conversation history and visual summary."""
    messages = [
        {"role": "system", "content": prompt},
    ]
    # Add conversation history
    for msg in session.conversation_history[-6:]:
        role = "user" if msg["role"] == "user" else "assistant"
        messages.append({"role": role, "content": msg["content"]})

    try:
        response = await llm.ainvoke(messages)
        return response.content
    except Exception:
        groq = ChatGroq(model="llama-3.1-8b-instant", api_key=os.getenv("GROQ_API_KEY"))
        response = await groq.ainvoke(messages)
        return response.content
```

---

## 5. Text-to-Speech Streaming

Reuse `get_audio.py` but stream chunks via WebSocket.

```python
async def stream_tts(text: str, websocket: WebSocket):
    """Stream TTS audio chunks to the client."""
    from get_audio import generate_speech_stream

    async for audio_chunk_b64 in generate_speech_stream(text):
        await websocket.send_json({
            "type": "tts_chunk",
            "payload": audio_chunk_b64
        })
```

### Modified TTS for Streaming

In `get_audio.py`, add a streaming variant:

```python
async def generate_speech_stream(text: str):
    """Generate TTS and yield base64 WAV chunks as they arrive."""
    import aiohttp
    import os

    api_key = os.getenv("SARVAM_API_KEY")
    url = "https://api.sarvam.ai/text-to-speech"

    # Split into sentences for parallel requests
    import re
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks = []
    for sentence in sentences:
        if len(sentence) > 200:
            # Further split
            words = sentence.split()
            for i in range(0, len(words), 30):
                chunks.append(" ".join(words[i:i+30]))
        else:
            chunks.append(sentence)

    # Send requests in parallel
    async def fetch_chunk(chunk_text):
        payload = {
            "inputs": [chunk_text],
            "target_language_code": "hi-IN",
            "speaker": "shubh",
            "pitch": 0,
            "pace": 1.0,
            "model": "bulbul:v3"
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers={"api-subscription-key": api_key}) as resp:
                data = await resp.json()
                if "audios" in data and data["audios"]:
                    return data["audios"][0]  # base64 WAV
        return None

    tasks = [fetch_chunk(chunk) for chunk in chunks]
    for coro in asyncio.as_completed(tasks):
        result = await coro
        if result:
            yield result
```

---

## 6. Frontend: Live Mode (`App.jsx`)

### New State

```jsx
const [liveMode, setLiveMode] = useState(false);
const [ws, setWs] = useState(null);
const [cameraStream, setCameraStream] = useState(null);
const videoRef = useRef(null);
const canvasRef = useRef(null);
const mediaRecorderRef = useRef(null);
const audioContextRef = useRef(null);
```

### Toggle Live Mode

```jsx
const startLiveMode = async () => {
  // 1. Start camera
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: 'environment', width: 640, height: 360 }
  });
  setCameraStream(stream);
  if (videoRef.current) videoRef.current.srcObject = stream;

  // 2. Open WebSocket
  const socket = new WebSocket('ws://localhost:8000/api/live/ws');
  socket.onopen = () => {
    socket.send(JSON.stringify({
      type: "auth",
      payload: { token: session.access_token, session_id: activeSessionId }
    }));
  };
  socket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    handleServerEvent(data);
  };
  setWs(socket);

  // 3. Start audio capture (WebRTC, stream mic PCM)
  startAudioCapture(socket);

  // 4. Start frame capture interval (1 FPS)
  startFrameCapture(socket);

  setLiveMode(true);
  setMode('live');
};

const stopLiveMode = () => {
  if (ws) ws.close();
  if (cameraStream) cameraStream.getTracks().forEach(t => t.stop());
  if (mediaRecorderRef.current) mediaRecorderRef.current.stop();
  if (audioContextRef.current) audioContextRef.current.close();
  setLiveMode(false);
  setWs(null);
  setCameraStream(null);
  if (videoRef.current) videoRef.current.srcObject = null;
  setMode('text');
};
```

### Audio Capture

#### Web Client (WebRTC → PCM → WebSocket)

```jsx
const startAudioCapture = (socket) => {
  navigator.mediaDevices.getUserMedia({ audio: true })
    .then(stream => {
      const audioContext = new AudioContext({ sampleRate: 16000 });
      audioContextRef.current = audioContext;
      const source = audioContext.createMediaStreamSource(stream);
      const processor = audioContext.createScriptProcessor(4096, 1, 1);

      processor.onaudioprocess = (event) => {
        if (socket.readyState !== WebSocket.OPEN) return;
        const input = event.inputBuffer.getChannelData(0);
        // Convert Float32 to PCM 16-bit
        const pcmData = new Int16Array(input.length);
        for (let i = 0; i < input.length; i++) {
          pcmData[i] = Math.max(-32768, Math.min(32767, input[i] * 32768));
        }
        // Send as base64 chunk
        const chunk = arrayBufferToBase64(pcmData.buffer);
        socket.send(JSON.stringify({ type: "audio_chunk", payload: chunk }));
      };
      source.connect(processor);
      processor.connect(audioContext.destination);
    });
};
```

#### Mobile Client (Expo: Micro-files → HTTP upload)

Expo Go cannot stream raw PCM over WebSocket. Instead:

1. Record 1.5-second WAV files using `expo-av` (`Audio.Recording`)
2. Upload each file immediately via `fetch()` to `POST /api/live/upload_audio`
3. The server decodes the WAV and injects PCM into the session's ring buffer
4. Responses arrive through the existing WebSocket (kept open for frames + events)

```tsx
// mobile_app/src/services/liveAudio.ts
import { Audio } from 'expo-av';
import * as FileSystem from 'expo-file-system';

const CHUNK_DURATION_MS = 1500;
let recording: Audio.Recording | null = null;
let isLive = false;

export async function startLiveAudioMic(
  uploadUrl: string,
  sessionId: string,
  token: string
) {
  isLive = true;
  await Audio.setAudioModeAsync({
    allowsRecordingIOS: true,
    playsInSilentModeIOS: true,
    staysActiveInBackground: true,
  });

  const recordAndUpload = async () => {
    if (!isLive) return;

    // Start recording
    recording = new Audio.Recording();
    await recording.prepareToRecordAsync({
      isMeteringEnabled: false,
      android: {
        extension: '.wav',
        outputFormat: Audio.AndroidOutputFormat.PCM_16BIT,
        audioEncoder: Audio.AndroidAudioEncoder.PCM_16BIT,
        sampleRate: 16000,
        numberOfChannels: 1,
        bitRate: 256000,
      },
      ios: {
        extension: '.wav',
        outputFormat: Audio.IOSOutputFormat.LINEARPCM,
        audioQuality: Audio.IOSAudioQuality.HIGH,
        sampleRate: 16000,
        numberOfChannels: 1,
        bitRate: 256000,
        linearPCMBitDepth: 16,
        linearPCMIsBigEndian: false,
        linearPCMIsFloat: false,
      },
    });

    // Record for 1.5s, then stop and upload
    setTimeout(async () => {
      if (!recording || !isLive) return;
      await recording.stopAndUnloadAsync();
      const uri = recording.getURI();
      recording = null;

      if (uri) {
        // Upload micro-file
        try {
          const formData = new FormData();
          formData.append('file', {
            uri,
            type: 'audio/wav',
            name: `chunk_${Date.now()}.wav`,
          } as any);
          formData.append('session_id', sessionId);

          await fetch(`${uploadUrl}/api/live/upload_audio`, {
            method: 'POST',
            headers: {
              Authorization: `Bearer ${token}`,
            },
            body: formData,
          });
        } catch (err) {
          console.warn('Audio upload failed, continuing...', err);
        }
      }

      // Schedule next chunk immediately
      recordAndUpload();
    }, CHUNK_DURATION_MS);
  };

  recordAndUpload();
}

export function stopLiveAudioMic() {
  isLive = false;
  if (recording) {
    recording.stopAndUnloadAsync();
    recording = null;
  }
}
```

The **video frames still go through WebSocket** (fits within Expo Go's WebSocket limits since frames are small base64 strings). Audio is the only path that uses HTTP uploads.

The **WebSocket receive path stays the same** — the WebSocket connection is kept alive solely for:
- Sending `video_frame` events
- Receiving `assistant_response`, `tts_chunk`, `visual_summary` events from the server

### Frame Capture (1 FPS)

```jsx
let frameInterval;
const startFrameCapture = (socket) => {
  frameInterval = setInterval(() => {
    if (!videoRef.current || socket.readyState !== WebSocket.OPEN) return;
    const canvas = canvasRef.current;
    canvas.width = 640;
    canvas.height = 360;
    canvas.getContext('2d').drawImage(videoRef.current, 0, 0);
    const jpeg = canvas.toDataURL('image/jpeg', 0.6).split(',')[1]; // base64 only
    socket.send(JSON.stringify({ type: "video_frame", payload: jpeg }));
  }, 1000);
};
```

### Handle Server Events

```jsx
const handleServerEvent = (data) => {
  switch (data.type) {
    case "assistant_response":
      setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'bot', text: data.payload }]);
      break;
    case "tts_chunk":
      // Append to audio buffer and play
      appendAndPlayTTSChunk(data.payload);
      break;
    case "visual_summary":
      // Optionally show what the AI sees
      console.log("AI sees:", data.payload);
      break;
    case "error":
      console.error("Live error:", data.payload);
      break;
  }
};
```

---

## 7. Frontend: Live Camera UI

```jsx
{mode === 'live' ? (
  <div className="live-view">
    <div className="live-header">
      <button className="back-button" onClick={stopLiveMode}>
        <ArrowLeftIcon />
      </button>
      <span className="live-title">Live Camera</span>
      <span className="live-dot" />
    </div>

    <div className="live-video-container">
      <video ref={videoRef} autoPlay playsInline muted className="live-video" />
      <canvas ref={canvasRef} style={{ display: 'none' }} />
    </div>

    <div className="live-conversation">
      {messages.slice(-3).map(m => (
        <div key={m.id} className={`live-msg ${m.role}`}>
          <span className="live-msg-label">
            {m.role === 'user' ? 'You' : 'AI'}
          </span>
          <span className="live-msg-text">{m.text}</span>
        </div>
      ))}
    </div>
  </div>
) : null}
```

---

## 8. Full-Session State (Persistent Visual Memory)

Gemini remembers what it has seen. Implement this in the `Session` class:

```python
class Session:
    def __init__(self, session_id: str, user_id: str):
        self.session_id = session_id
        self.user_id = user_id
        self.frame_buffer: deque = deque(maxlen=10)
        self.transcript_buffer: list = []
        self.conversation_history: list = []
        self.visual_summary: str = ""
        self.previous_objects: dict = {}
        self.current_scene: str = ""
        self.last_frame_hash: str = ""
        self.is_processing: bool = False

    def update_visual_context(self, summary: str):
        """Store what we've seen for follow-up questions."""
        # Extract key objects from summary
        # e.g., "basil plant", "kitchen counter", "coffee mug"
        self.visual_summary = summary

    def add_interaction(self, role: str, content: str):
        self.conversation_history.append({"role": role, "content": content})
        # Keep last 20 messages
        if len(self.conversation_history) > 20:
            self.conversation_history = self.conversation_history[-20:]
```

This means follow-up questions like "how do I care for it?" work without resending frames, because the system already knows `it = basil plant` from the visual summary.

---

## 9. Latency Budget

### Web Client (WebRTC streaming)

| Step | Target | Current Stack |
|------|--------|---------------|
| STT (Sarvam saaras:v3) | 100-300ms | ~200-500ms (streaming to Sarvam WS) |
| Vision LLM (Kimi K2.6) | 500-1000ms | ~1000-2000ms |
| LLM Response (Cerebras gpt-oss-120b) | 300-800ms | ~500-1500ms |
| TTS first chunk (Sarvam bulbul:v3) | 100-200ms | ~300-500ms |
| **Total** | **< 2s** | **~2-4s** |

### Mobile Client (Micro-file upload)

| Step | Target | Current Stack |
|------|--------|---------------|
| Record 1.5s WAV | 1500ms (fixed) | 1500ms |
| HTTP upload + decode | 100-300ms | ~200-500ms (file size ~48KB) |
| VAD silence detection | 0-800ms | Up to 800ms (after last voice) |
| STT (Sarvam saaras:v3) | 200-500ms | ~200-500ms |
| Vision LLM (Kimi K2.6) | 500-1000ms | ~1000-2000ms |
| LLM Response (Cerebras) | 300-800ms | ~500-1500ms |
| TTS first chunk | 100-200ms | ~300-500ms |
| **Total (perceived)** | **< 3s** | **~3-6s** |

The 1.5s chunk duration is the dominant latency — the user must finish speaking before the last chunk containing their utterance is uploaded. This is acceptable because:
- Most spoken utterances are 1-3 seconds
- The overlapping upload schedule means the previous chunk is processing while the next is being recorded
- The perceived latency is: `(last_chunk_upload + STT + LLM + TTS) — overlap`

### Optimizations

1. **Skip Vision LLM when scene unchanged** — save $ and latency
2. **Skip Vision LLM for follow-up questions** — use visual summary + conversation history
3. **Pre-generate TTS filler** ("Let me look...") while Vision LLM processes
4. **Parallel Vision + STT** — process frames while user is still speaking
5. **Reduce chunk size** — 1.5s works well; smaller = more overhead, larger = more latency

---

## 10. File Changes Summary

| File | Change |
|------|--------|
| `server.py` | Add WebSocket endpoint `/api/live/ws`, `Session` + `AudioRingBuffer`, STT/vision/LLM/TTS pipeline, HTTP `POST /api/live/upload_audio` for mobile |
| `get_audio.py` | Add `generate_speech_stream()` async generator for chunked TTS |
| `get_transcript.py` | Add `transcribe_pcm(pcm_bytes)` function (accept raw PCM, not just files). See §2.4 below |
| `nodes.py` | No changes (not used in live mode — live has its own simplified pipeline) |
| `frontend/src/App.jsx` | Add live mode: camera, audio capture (WebRTC PCM), WebSocket, events, UI |
| `frontend/src/index.css` | Add `.live-view`, `.live-video-container`, `.live-conversation` styles |
| **`mobile_app/src/services/liveAudio.ts`** | **New** — Micro-file recording + HTTP upload loop |
| **`mobile_app/src/services/api.ts`** | Add `uploadLiveAudio()` and `startLiveSession()` functions |
| `requirements.txt` | No new dependencies |
| `.env` | No new keys |
