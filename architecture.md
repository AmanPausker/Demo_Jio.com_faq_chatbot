# Architecture — Key Implementations

## 1. Voice Activity Detection (VAD) & Barge-in

**File**: `frontend/src/App.jsx` — `startNativeVAD()` (line 175)

Uses the **Web Audio API** (`AnalyserNode`) to read raw frequency-domain volume levels 60 times a second. No ML model runs in the browser — it is a simple energy-based VAD.

### Architecture

```mermaid
graph TD
    subgraph Browser [React Frontend - Browser]
        MIC["🎤 getUserMedia()"] --> STREAM["MediaStream"]
        STREAM --> AC["AudioContext"]
        AC --> ANALYSER["AnalyserNode<br/>fftSize: 512<br/>smoothingTimeConstant: 0.2"]
        ANALYSER --> LOOP["requestAnimationFrame<br/>~60fps"]
        LOOP --> CHECK{"getByteFrequencyData()<br/>average > 50?"}
        
        CHECK -- Yes --> BARGE_IN{"audioPlayerRef<br/>currently playing?"}
        BARGE_IN -- Yes --> PAUSE["audioPlayerRef.pause()<br/>⏸️ Cut AI off"]
        BARGE_IN -- No --> START_REC["Start MediaRecorder<br/>🎤 Recording..."]
        CHECK -- No --> SILENCE{"was speaking &&<br/>silenceTimer running?"}
        SILENCE -- Yes --> TIMER["setTimeout 1500ms"]
        TIMER --> STOP_REC["Stop MediaRecorder<br/>⬆️ Upload blob"]
        
        PAUSE --> START_REC
        START_REC --> MEDIA_REC["MediaRecorder<br/>ondataavailable"]
        MEDIA_REC --> BLOB["Blob → FormData"]
        BLOB --> FETCH["fetch POST /api/chat/audio"]
    end

    subgraph Server [Python FastAPI - Server]
        FETCH --> API["/api/chat/audio"]
        API --> STT["transcribe_audio_file()"]
        STT --> LANGGRAPH["app.ainvoke()"]
        LANGGRAPH --> TTS["generate_speech()"]
        TTS --> RESPONSE["{ text, audio_base64 }"]
    end

    RESPONSE --> PLAY["playAudio()<br/>src = data:audio/wav;base64,..."]
    PLAY --> AUDIO_TAG["<audio> autoplay"]
    AUDIO_TAG --> IS_PLAYING["setIsPlaying(true)"]
    IS_PLAYING --> UI["Pulsing circle animation"]
```

### VAD State Machine

```mermaid
stateDiagram-v2
    [*] --> Idle
    
    Idle --> Speaking : avgVolume > 50
    Idle --> Idle : avgVolume ≤ 50
    
    Speaking --> BargeIn : AI was playing → pause TTS
    Speaking --> Recording : Start MediaRecorder
    Speaking --> Speaking : avgVolume > 50 (reset silenceTimer)
    Speaking --> WaitingForSilence : avgVolume ≤ 50
    
    WaitingForSilence --> Speaking : avgVolume > 50 (clear silenceTimer)
    WaitingForSilence --> Done : 1500ms elapsed
    
    Done --> [*] : Stop MediaRecorder\nUpload blob
```

### Key Parameters

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `fftSize` | 512 | Frequency resolution for AnalyserNode |
| `smoothingTimeConstant` | 0.2 | Light smoothing — responsive to speech onset |
| `VOLUME_THRESHOLD` | 50 | High threshold to reject background noise |
| `SILENCE_MS_TO_STOP` | 1500ms | Confirm user finished speaking |
| Poll rate | ~60fps (rAF) | Real-time volume checks |

### Barge-in Flow

```
User starts speaking while AI is playing TTS
              │
              ▼
avgVolume > 50 detected
              │
      ┌───────┴───────┐
      ▼               ▼
audioPlayerRef    Start MediaRecorder
.pause()          (capture new query)
      │               │
      ▼               ▼
 AI silenced      User finishes speaking
  mid-word        → 1500ms silence
                      │
                      ▼
                 Upload audio blob
                 → STT → LangGraph → TTS
                 → Play new response
```

---

## 2. Speech-to-Text (STT) Processing

**Files**: `server.py` (line 42) → `get_transcript.py` — `transcribe_audio_file()` (line 106)

### Architecture

```mermaid
sequenceDiagram
    participant Browser
    participant FastAPI as FastAPI (server.py)
    participant STT as get_transcript.py
    participant Sarvam as Sarvam AI API
    participant LangGraph as LangGraph (app.py)

    Browser->>FastAPI: POST /api/chat/audio<br/>FormData { audio: Blob }
    FastAPI->>FastAPI: audio.read() → bytes
    FastAPI->>STT: transcribe_audio_file(audio_bytes)
    
    STT->>STT: Create temp .wav file on disk
    STT->>Sarvam: Upload file → saaras:v3<br/>language_code=hi-IN<br/>mode=codemix
    Sarvam-->>STT: { transcript: "..." }
    STT->>STT: Delete temp file
    STT-->>FastAPI: "transcribed text"
    
    FastAPI->>LangGraph: app.ainvoke({question: text})
    LangGraph-->>FastAPI: { answer: "..." }
    
    FastAPI->>FastAPI: generate_speech(answer, return_base64=True)
    FastAPI-->>Browser: { text, user_message, audio_base64 }
```

### File vs Streaming

| Mode | Function | Use Case | Latency |
|------|----------|----------|---------|
| **Streaming** | `listen_for_speech()` | Real-time mic → WebSocket STT | ~1-2s |
| **File** | `transcribe_audio_file()` | Browser uploads recorded blob → REST STT | ~2-4s |

The file path is used in the React frontend flow because the browser's `MediaRecorder` produces a complete `.wav` blob after recording stops, which maps naturally to a single REST upload.

### Temp File Handling

```mermaid
flowchart LR
    BYTES["audio_bytes (bytes)"] --> IO["io.BytesIO(bytes)<br/>f.name = 'audio.wav'"]
    IO --> SDK["AsyncSarvamAI<br/>.speech_to_text.transcribe(file=f)"]
    SDK --> RESULT["res.transcript"]
```

The Sarvam SDK requires a file-like object. To avoid writing to disk, the code wraps the raw bytes in an `io.BytesIO` with a fake `.name` attribute. Only the standalone Gradio path (`app.py`) uses direct WebSocket streaming.

---

## 3. AI Reasoning & RAG (Retrieval-Augmented Generation)

**Files**: `app.py` (LangGraph workflow) → `nodes.py` (retrieve + generate nodes)

### Architecture

```mermaid
graph TD
    subgraph LangGraph [LangGraph StateMachine]
        START --> RETRIEVE["retrieve_node()"]
        RETRIEVE --> GENERATE["generate_node()"]
        GENERATE --> END
    end

    subgraph Retrieve [Retrieval Pipeline]
        QUESTION["User Question"] --> FUZZY["Fuzzy Normalizer"]
        FUZZY --> BRAND["Brand Mapping"]
        
        BRAND --> VECTOR["all-MiniLM-L6-v2<br/>→ embedding (384d)"]
        BRAND --> KEYWORDS["Stopword removal<br/>→ keyword list"]
        
        VECTOR --> NEO4J_VEC["Neo4j Vector Index<br/>faq_embeddings<br/>Top 10"]
        KEYWORDS --> NEO4J_FT["Neo4j Fulltext Index<br/>faq_text_index<br/>Top 10"]
        
        NEO4J_VEC --> COMBINE["UNION + DISTINCT"]
        NEO4J_FT --> COMBINE
        
        COMBINE --> TRAVERSE["Graph Traversal<br/>(Topic)-[:HAS_SUBTOPIC]-><br/>(Subtopic)-[:CONTAINS_FAQ]->(FAQ)"]
        TRAVERSE --> CANDIDATES["Candidate context strings"]
        CANDIDATES --> RERANK["CrossEncoder<br/>ms-marco-MiniLM-L-6-v2"]
        RERANK --> TOP3["Top 3 contexts"]
    end

    subgraph Generate [Generation]
        TOP3 --> PROMPT["System prompt:<br/>'Answer using ONLY context'"]
        PROMPT --> LLM["Cerebras<br/>Llama 3.1 8B"]
        LLM --> ANSWER["Final answer"]
    end

    RETRIEVE --- Retrieve
    Generate --- GENERATE
```

### Brand Mapping Logic

```mermaid
flowchart LR
    INPUT["jio fiber plans"] --> REGEX["Regex pattern match<br/>(?i)\bjio\s*fiber\b"]
    REGEX --> REPLACE["Replace with JioFiber"]
    REPLACE --> OUTPUT["JioFiber plans"]
    
    INPUT2["my jio app"] --> REGEX2["Match pattern"]
    REGEX2 --> REPLACE2["Replace with MyJio"]
    REPLACE2 --> OUTPUT2["MyJio app"]
```

| Pattern | Replaced With |
|---------|---------------|
| `jio\s*plus` | `JioPlus` |
| `jio\s*cinema` | `JioCinema` |
| `jio\s*saavn` | `JioSaavn` |
| `jio\s*tv` | `JioTV` |
| `jio\s*mart` | `JioMart` |
| `my\s*jio` | `MyJio` |

This prevents the LLM from treating "Jio Fiber" and "JioFiber" as different concepts during vector search.

### Hybrid Search Decision Tree

```mermaid
flowchart TD
    QUERY["User Question"] --> FUZZY_NORM["Fuzzy Normalization<br/>(jellyfish + difflib)"]
    FUZZY_NORM --> NORM["Normalized Question"]
    
    NORM --> VEC_PATH["Vector Search Path"]
    NORM --> FT_PATH["Fulltext Search Path"]
    
    subgraph VEC_PATH [Semantic Search]
        VEC_EMBED["Encode with all-MiniLM-L6-v2"] --> VEC_QUERY["Neo4j vector.queryNodes<br/>limit: 10"]
    end
    
    subgraph FT_PATH [Keyword Search]
        FT_EXTRACT["Extract keywords<br/>(remove stopwords, expand brands)"] --> FT_BUILD["Build OR query"]
        FT_BUILD --> FT_QUERY["Neo4j fulltext.queryNodes<br/>limit: 10"]
    end
    
    VEC_QUERY --> MERGE["UNION results"]
    FT_QUERY --> MERGE
    
    MERGE --> DEDUP["DISTINCT by node"]
    DEDUP --> GRAPH_WALK["MATCH (Topic)→(Subtopic)→(FAQ)"]
    GRAPH_WALK --> SCORE["CrossEncoder Rerank<br/>question vs candidate pairs"]
    SCORE --> TOP_K["Top 3 → LLM context"]
```

---

## 4. Text-to-Speech (TTS) & Playback

**Files**: `get_audio.py` (generation) → `frontend/src/App.jsx` — `playAudio()` (line 38)

### Architecture

```mermaid
sequenceDiagram
    participant LangGraph as LangGraph
    participant TTS as get_audio.py
    participant Sarvam as Sarvam TTS API
    participant Server as server.py
    participant Browser as React Frontend

    LangGraph-->>Server: { answer: "..." }
    
    Server->>TTS: generate_speech(answer, return_base64=True)
    
    TTS->>TTS: Split into sentences<br/>(?<=[.!?\n])\s+
    TTS->>TTS: Group into chunks ≤200 chars
    
    par Parallel TTS Requests
        TTS->>Sarvam: Chunk 1 → bulbul:v3
        TTS->>Sarvam: Chunk 2 → bulbul:v3
        TTS->>Sarvam: Chunk N → bulbul:v3
    end
    
    Sarvam-->>TTS: base64 WAV chunk 1
    Sarvam-->>TTS: base64 WAV chunk 2
    Sarvam-->>TTS: base64 WAV chunk N
    
    TTS->>TTS: Gather, sort by index
    TTS->>TTS: Decode each WAV
    TTS->>TTS: Concatenate numpy arrays
    TTS->>TTS: WAV → base64 string
    
    TTS-->>Server: base64 string
    
    Server-->>Browser: { audio_base64: "..." }
    
    Browser->>Browser: playAudio(data.audio_base64)
    Browser->>Browser: audioPlayerRef.src = 'data:audio/wav;base64,...'
    Browser->>Browser: audioPlayerRef.play()
    Browser->>Browser: setIsPlaying(true)
    Browser->>UI: Start pulsing animation
```

### Sentence Chunking Strategy

```mermaid
flowchart TD
    ANSWER["Full answer text"] --> SPLIT["Split by sentence boundaries<br/>(. ! ? \\n)"]
    SPLIT --> CHUNK1["Sentence 1<br/>'Jio Fiber plans start at...'"]
    SPLIT --> CHUNK2["Sentence 2<br/>'You can also add...'"]
    SPLIT --> CHUNK3["Sentence N"]
    
    CHUNK1 --> GROUP{"Length < 200 chars?"}
    GROUP -- Yes --> COMBINE["Accumulate into current chunk"]
    GROUP -- No --> FINALIZE["Finalize current chunk, start new one"]
    
    COMBINE --> PARALLEL["Dispatch all chunks concurrently"]
    FINALIZE --> PARALLEL
    
    PARALLEL --> TTS1["Sarvam TTS chunk 1"]
    PARALLEL --> TTS2["Sarvam TTS chunk 2"]
    PARALLEL --> TTS3["Sarvam TTS chunk N"]
```

### Audio Playback Chain

```mermaid
flowchart LR
    BASE64["Base64 WAV string"] --> DATA_URL["data:audio/wav;base64,..."]
    DATA_URL --> SRC_SET["audioPlayerRef.current.src = data URL"]
    SRC_SET --> PLAY["audioPlayerRef.current.play()"]
    PLAY --> ON_PLAYING["setIsPlaying(true)"]
    PLAY --> UI_ANIM["CSS: .animate-pulse-ai-slow<br/>.animate-pulse-ai-med<br/>.scale-up-ai"]
    PLAY --> ON_ENDED["onended → setIsPlaying(false)"]
    PLAY --> ON_ERROR["onerror → setIsPlaying(false)"]
```

### TTS Fallback (if present)

The two TTS modes:

| Mode | Function | Latency | Use Case |
|------|----------|---------|----------|
| **Streaming** | `generate_speech()` (generator) | Real-time | Gradio UI — yields `(sample_rate, np.array)` tuples |
| **Base64** | `generate_speech(return_base64=True)` | ~1-3s total | FastAPI — single base64 string for React `<audio>` tag |

---

## End-to-End Flow (Voice Mode)

```mermaid
sequenceDiagram
    actor User
    participant Browser
    participant FastAPI as FastAPI Server
    participant STT as get_transcript.py
    participant RAG as LangGraph + Neo4j
    participant TTS as get_audio.py
    
    Note over Browser: VAD Loop (60fps)
    
    User->>Browser: Starts speaking
    Browser->>Browser: AnalyserNode detects volume > 50
    Browser->>Browser: Pause AI audio if playing (barge-in)
    Browser->>Browser: Start MediaRecorder
    
    User->>Browser: Stops speaking
    Browser->>Browser: 1500ms silence detected
    
    Browser->>FastAPI: POST /api/chat/audio (WAV blob)
    FastAPI->>STT: transcribe_audio_file()
    STT->>STT: Temp WAV → Sarvam STT API
    STT-->>FastAPI: transcribed text
    
    FastAPI->>RAG: app.ainvoke({question})
    RAG->>RAG: Fuzzy normalize → brand map
    RAG->>RAG: Vector search + fulltext search
    RAG->>RAG: Graph traverse → rerank → top 3
    RAG->>RAG: Cerebras Llama 3.1 8B → answer
    RAG-->>FastAPI: { answer }
    
    FastAPI->>TTS: generate_speech(answer)
    TTS->>TTS: Sentence split → parallel Sarvam TTS
    TTS-->>FastAPI: base64 WAV
    
    FastAPI-->>Browser: { text, audio_base64 }
    
    Browser->>Browser: playAudio() → inject into <audio>
    Browser->>User: Plays spoken response
    Note over Browser: VAD still running (ready for next barge-in)
```
