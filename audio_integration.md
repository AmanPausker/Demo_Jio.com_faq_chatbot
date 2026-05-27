# Audio Integration

The chatbot supports both text and audio input, with spoken responses generated via Text-to-Speech. Audio is handled through Sarvam AI's APIs, integrated asynchronously into the Gradio UI.

## Speech-to-Text (STT)

**File**: `get_transcript.py`

Captures microphone audio in real-time and streams it to Sarvam AI's WebSocket API for transcription.

### Flow

1. **Capture**: `sounddevice.InputStream` captures audio at 16 kHz, mono, in 100 ms chunks (1600 samples).
2. **Queue**: Each chunk is converted to int16, enqueued into an `asyncio.Queue` via a thread-safe callback.
3. **Stream**: A background `sender` task reads from the queue, base64-encodes each chunk, and sends it to Sarvam's WebSocket STT endpoint (`saaras:v3`, `hi-IN`, `codemix` mode).
4. **Receive**: A `receiver` task listens for transcript responses. When the transcript text grows, it updates the latest result and resets a silence timer.
5. **Silence Detection**: A `monitor` task continuously checks if the transcript has remained unchanged for 2 seconds (default). When silence is detected, it signals completion and the final transcript is returned.

### Key Details

- **Model**: `saaras:v3` (Sarvam AI)
- **Language**: `hi-IN` with `codemix` mode (handles Hinglish)
- **Sensitivity**: `high_vad_sensitivity=True` for aggressive voice activity detection
- **Silence Timeout**: Configurable, defaults to 2.0 seconds
- **Integration**: Called from `app.py:process_audio()` — the Gradio button click triggers the async function, and the returned transcript feeds into the same LangGraph pipeline as text input

```
Microphone -> 16kHz int16 chunks -> base64 -> Sarvam WebSocket STT (saaras:v3)
                                                          |
                                                     [transcript]
                                                          |
                                                    silence? (2s)
                                                          |
                                                    return text
```

## Text-to-Speech (TTS)

**File**: `get_audio.py`

Converts the LLM's text response into speech using Sarvam AI's REST API, streaming audio chunks directly to the Gradio audio component.

### Flow

1. **Split**: The answer text is split into sentences using a regex (`(?<=[.!?\n])\s+`).
2. **Parallel Requests**: Each sentence chunk is sent concurrently to Sarvam's TTS REST API via `AsyncSarvamAI`.
3. **WAV Decoding**: Each response contains base64-encoded WAV audio. It is decoded, opened with Python's `wave` module, and converted to `(sample_rate, int16 numpy array)` tuples.
4. **Streaming**: Chunks are yielded in order (results are awaited sequentially despite parallel dispatch) and streamed to Gradio's `gr.Audio` component with `streaming=True`.

### Key Details

- **Model**: `bulbul:v3` (Sarvam AI)
- **Speaker**: `shubh`
- **Language**: `en-IN` (Indian English)
- **Format**: Each chunk is a tuple of `(sample_rate: int, audio_data: np.ndarray[int16])` — Gradio's native streaming format
- **Concurrency**: All sentence chunks are dispatched in parallel, but yielded in original order for coherent playback
- **Error Handling**: Exceptions are caught and printed, with no audio returned on failure

```
LLM Answer Text
    |
[sentence split]
    |
chunk1  chunk2  chunk3  ...  (parallel API calls to Sarvam TTS bulbul:v3)
    |       |       |
   WAV     WAV     WAV
    |       |       |
  np.int16 np.int16 np.int16
    |       |       |
    +-------+-------+
            |
    Gradio streaming audio (sequential yield)
```

## Integration in Gradio (`app.py`)

- **Text input**: `process_text()` runs the LangGraph pipeline, then streams TTS audio via `generate_speech()`.
- **Audio input**: `process_audio()` calls `listen_for_speech()` for transcription, then follows the same path.
- Both functions are async generators that yield `(chatbot_history, audio_chunk)` tuples to Gradio's streaming output.
- The `gr.Audio` component has `autoplay=True` and `streaming=True` for real-time playback.

```
[Text Button]  --> process_text()  --> LangGraph --> TTS stream --> Audio out
[🎤 Button]    --> process_audio() --> STT --> LangGraph --> TTS stream --> Audio out
```
