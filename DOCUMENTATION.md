# Jio FAQ Chatbot — Full Application Documentation

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                  Frontend (React/Vite)               │
│  App.jsx → Auth.jsx → API Calls → fetch()          │
└──────────────────┬──────────────────────────────────┘
                   │ HTTP/REST + WebSocket
                   ▼
┌─────────────────────────────────────────────────────┐
│              Backend (FastAPI + LangGraph)            │
│  server.py (FastAPI) → app.py (LangGraph Workflow)  │
│  ├─ nodes.py (LLM agents)                           │
│  ├─ tools.py (Weather, Location)                    │
│  ├─ file_workflow.py (PDF→Qdrant)                   │
│  ├─ get_audio.py (TTS via Sarvam AI)                │
│  └─ get_transcript.py (STT via Sarvam AI)           │
└───┬────────────┬────────────┬────────────┬──────────┘
    │            │            │            │
    ▼            ▼            ▼            ▼
 Supabase    Neo4j        Qdrant        Sarvam AI
 (Auth +     (FAQ        (User PDF     (STT/TTS)
 Memory)     Vectors)     Vectors)
```

---

## 1. Backend — Python

### `server.py` (FastAPI Server)
- **What it does**: Main HTTP/WebSocket server. Handles all API routes, authentication, chat sessions, image generation, vision analysis, and live video chat via WebSocket.
- **Data sources**:
  - Supabase (auth, user memory, chat sessions) via `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY`
  - LangGraph workflow imported from `app.py` for chatbot logic
  - Sarvam AI (TTS) via `get_audio.generate_speech()`
  - Sarvam AI (STT) via `get_transcript.transcribe_audio_file()`
  - NVIDIA AI (vision LLM) via `ChatNVIDIA` with `NVDIA_API_KEY`
  - Cloudflare Workers AI (image generation) via `CLOUDFARE_ACCOUNT_ID` / `WORKERS_API_KEY`
- **Where it's used**: Entry point for the API. Started via `uvicorn server:server`. Called by frontend (`App.jsx`) and mobile app (`api.ts`).
- **Endpoints**:
  - `POST /api/chat` — Text chat with optional session_id
  - `POST /api/chat/audio` — Audio file chat (STT → LLM → TTS)
  - `GET /api/sessions` — List user's chat sessions
  - `GET /api/sessions/{id}/history` — Get session message history
  - `POST /api/upload` — Upload PDF (processed in background)
  - `POST /api/vision` — Analyze uploaded image
  - `POST /api/generate_image` — Generate image from prompt (Cloudflare Flux)
  - `GET /api/test_memory` — Test Supabase memory operations
  - `WS /api/live/ws` — Live video/audio WebSocket chat

### `app.py` (LangGraph Workflow + Gradio UI)
- **What it does**: Defines the LangGraph `StateGraph` with 3 nodes (`retrieve`, `generate`, `general_generation`). Also provides a Gradio web UI for local testing.
- **Data sources**:
  - `agent_state.GraphState` — shared state dict
  - `nodes.retrieve_node` — FAQ retrieval from Neo4j + Qdrant
  - `nodes.generate_node` — Jio FAQ answer generation
  - `nodes.general_generation_node` — general Q&A generation
  - `get_transcript.listen_for_speech()` — live mic STT
  - `get_audio.generate_speech()` — TTS for responses
- **Where it's used**: Imported by `server.py` as `workflow` object for compilation. Also runnable standalone as Gradio app.

### `nodes.py` (LangGraph Nodes)
- **What it does**: Contains the three LangGraph node functions:
  1. `retrieve_node` — Fuzzy-corrects the question, embeds it, searches Neo4j (vector + fulltext), searches Qdrant for user PDFs, reranks with CrossEncoder, and routes to Jio FAQ (router=2) or general agent (router=1)
  2. `generate_node` — Answers Jio FAQ questions using retrieved context + NVIDIA LLM
  3. `general_generation_node` — General Q&A with tool calling (weather, location, save_user_memory)
- **Data sources**:
  - Neo4j (`bolt://localhost:7687`) — FAQ embeddings and fulltext index
  - `SentenceTransformer('all-MiniLM-L6-v2')` — embedding model
  - `CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')` — reranking
  - `ChatNVIDIA` with `NVDIA_API_KEY` — primary LLM
  - `ChatGroq` with `GROQ_API_KEY` — session title generation
  - Qdrant (via `file_workflow.search_qdrant`) — user PDF chunks
  - `tools.get_weather` / `get_current_location` — tool functions
  - Supabase (for `save_user_memory` tool) — long-term memory storage
- **Where it's used**: Called by the LangGraph workflow defined in `app.py`.

### `agent_state.py` (State Definition)
- **What it does**: Defines the `GraphState` TypedDict with fields: `messages`, `router`, `question`, `context`, `answer`, `long_term_memory`, `user_id`, `token`.
- **Where it's used**: Imported by `app.py` and `nodes.py`.

### `tools.py` (LangChain Tools)
- **What it does**: Two LangChain tools:
  - `get_weather(city)` — Calls OpenWeatherMap API
  - `get_current_location()` — Calls ip-api.com to get user's city
- **Data sources**: `OPEN_WEATHER_API_KEY` from `.env`
- **Where it's used**: Imported and bound by `general_generation_node` in `nodes.py`.

### `file_workflow.py` (PDF Processing Pipeline)
- **What it does**: Full pipeline for uploading PDFs:
  1. `converter_pdf()` — Converts PDF to Markdown using Docling
  2. `create_chunking()` — Splits markdown into overlapping chunks (1000 chars, 200 overlap)
  3. `create_embeddings()` — Embeds chunks via `SentenceTransformer`
  4. `store_in_qdrant()` — Stores chunks + embeddings in Qdrant with user_id/session_id metadata
  5. `search_qdrant()` — Searches Qdrant filtered by user_id + session_id
- **Data sources**:
  - Qdrant cloud instance (`QDRANT_URL` / `QDRANT_API_KEY`)
  - Collection name: `jio_documents`
- **Where it's used**: Called by `server.py` in `process_pdf_background()`. `search_qdrant()` is called by `retrieve_node` in `nodes.py`.

### `get_audio.py` (Text-to-Speech)
- **What it does**: Converts text to speech via Sarvam AI API (`bulbul:v3` model, `shubh` speaker, Hindi). Splits text into sentences, processes in parallel, concatenates WAV outputs.
- **Functions**:
  - `generate_speech()` — Returns `(framerate, numpy_array)` or base64 string
  - `generate_speech_stream()` — Async generator yielding base64 WAV chunks
- **Data sources**: `SARVAM_API_KEY` from `.env`
- **Where it's used**: Called by `app.py` (Gradio), `server.py` (REST API + WebSocket TTS), and `generate_fillers.py` scripts.

### `get_transcript.py` (Speech-to-Text)
- **What it does**: Three STT modes using Sarvam AI (`saaras:v3` model):
  1. `listen_for_speech()` — Real-time microphone capture + Silero VAD for silence detection
  2. `transcribe_audio_file()` — Transcribes uploaded audio files (with ffmpeg conversion)
  3. `transcribe_pcm()` — Transcribes raw PCM audio (wraps with WAV header in-memory)
- **Data sources**: `SARVAM_API_KEY` from `.env`, Silero VAD model loaded locally
- **Where it's used**: `listen_for_speech()` in Gradio (`app.py`), `transcribe_audio_file()` in server REST API, `transcribe_pcm()` in WebSocket live audio.

### `check_sarvam.py` (Utility)
- **What it does**: Quick check of available methods on SarvamAI client classes.
- **Where it's used**: Standalone debugging script.

### `clear_memory.py` (Utility)
- **What it does**: Clears all Supabase `user_memory` rows for testing.
- **Where it's used**: Standalone script.

### `generate_fillers.py` / `generate_longer_fillers.py` / `generate_more_fillers.py` (Utilities)
- **What they do**: Generate pre-recorded TTS audio fillers ("hmm", "let me check...") and write them as base64 into `frontend/src/fillersData.js`. Used to mask LLM latency in the frontend.
- **Data sources**: `get_audio.generate_speech()` + preset phrase lists
- **Where it's used**: Standalone scripts that output to frontend source.

### `test_vision.py` (Test)
- **What it does**: Tests NVIDIA vision LLM by sending a 1x1 pixel base64 image.
- **Where it's used**: Standalone test.

### `test_neo.py` (Test)
- **What it does**: Tests Neo4j fulltext index counts for "JioPlus" vs "Jio Plus".
- **Where it's used**: Standalone test.

### `test_fuzzy.py` (Test)
- **What it does**: Tests the fuzzy matching logic (dictionary-based brand name correction).
- **Where it's used**: Standalone test.

### `test_rewriter.py` (Test)
- **What it does**: Tests Cerebras LLM for query rewriting (brand name correction).
- **Data sources**: `CEREBRAS_API_KEY` from `.env`
- **Where it's used**: Standalone test.

---

## 2. Data Files

### `data/jio_faq_data.json`
- **What it is**: Master FAQ dataset with fields: `topic`, `sub_topic`, `question`, `answer`. Contains ~200+ Jio FAQ entries covering True 5G, Postpaid, International Roaming, Offers, Onboarding, etc.
- **Where it's used**: Imported into Neo4j database (not directly by Python code; Neo4j is populated separately).

### `data/topics.json`
- **What it is**: Hierarchical topic→subtopics mapping. 8 main topics with 200+ subtopics.
- **Where it's used**: Reference for Neo4j graph structure (Topic→Subtopic→FAQ nodes).

### `.env` (Root + `frontend/.env` + `mobile_app/.env`)
- **What it is**: Environment variables for API keys (Sarvam, Groq, NVIDIA, Qdrant, Supabase, OpenWeather, Cloudflare, Cerebras).
- **Where it's used**: Read by all backend Python files via `dotenv.load_dotenv()`, frontend via `import.meta.env`, mobile via `process.env.EXPO_PUBLIC_*`.

---

## 3. Frontend — React + Vite

### `frontend/src/main.jsx`
- **What it does**: Entry point. Renders `<App />` into `#root` DOM element.
- **Where it's used**: Referenced by `frontend/index.html` as module script.

### `frontend/src/App.jsx` (Main Application)
- **What it does**: Full chat application with multiple modes:
  1. **Text chat** — Send text messages to backend `/api/chat`
  2. **Audio chat** — Hold-to-talk recording with VAD auto-detection
  3. **Voice mode** — Continuous voice chat with animated orb UI
  4. **Live video** — WebSocket-based camera + audio streaming
  5. **File upload** — PDF upload with drag-and-drop UI
  6. **Image upload** — Upload image for vision analysis
  7. **Image generation** — Text-to-image via `/api/generate_image`
  8. **Session management** — Sidebar with chat history
- **Data sources**:
  - Backend API at `http://localhost:8000`
  - Supabase for auth (via `supabaseClient.js`)
  - Pre-generated TTS fillers from `fillersData.js`
  - A2UI (Adaptive UI) catalog from `A2UICatalog.tsx` for weather cards
- **Where it's used**: Compiled by Vite and served to browser.

### `frontend/src/Auth.jsx`
- **What it does**: Login/Signup form. Calls `supabase.auth.signInWithPassword()` or `signUp()`.
- **Data sources**: Supabase via `supabaseClient.js`
- **Where it's used**: Shown by `App.jsx` when no session exists.

### `frontend/src/supabaseClient.js`
- **What it does**: Creates and exports a Supabase client with `sessionStorage` for auth persistence.
- **Data sources**: `VITE_SUPABASE_URL` + `VITE_SUPABASE_ANON_KEY` from frontend `.env`
- **Where it's used**: Imported by `App.jsx`, `Auth.jsx`.

### `frontend/src/A2UICatalog.tsx`
- **What it does**: Defines a `WeatherCard` component for the A2UI (Adaptive UI) framework. When the LLM returns a weather JSON, this renders a styled weather card.
- **Where it's used**: Imported by `App.jsx` as `myCatalog`.

### `frontend/src/utils/audioUtils.js`
- **What it does**: Converts `Float32Array` audio samples to WAV format Blob. Caps at 25 seconds to avoid Sarvam AI's 30s limit.
- **Where it's used**: Used by VAD logic in `App.jsx` (not currently imported; was for a previous `vad-web` integration).

### `frontend/src/fillersData.js`
- **What it does**: Array of base64-encoded WAV audio clips (pre-generated filler phrases like "hmm", "let me check...") used to mask LLM latency.
- **Data sources**: Generated by `generate_fillers.py` / `generate_longer_fillers.py` / `generate_more_fillers.py`
- **Where it's used**: Imported by `App.jsx` as `sarvamFillers`.

### `frontend/index.html`
- **What it does**: HTML shell with `<div id="root">` for React mount.

### `frontend/vite.config.js`
- **What it does**: Vite config with React plugin. Excludes `onnxruntime-web` from optimized deps.

---

## 4. Mobile App — React Native + Expo

### `mobile_app/src/app/(app)/chat.tsx` (Chat Screen)
- **What it does**: Main chat screen for the mobile app. Features:
  - Text chat via `sendChatMessage()` API
  - Voice mode with continuous VAD (silence detection via Audio meter)
  - Push-to-talk voice messages
  - PDF upload via `uploadFile()` API
  - Image generation via `/imagine` command
  - Weather card rendering from A2UI data
  - Animated gradient orb for voice UI
- **Data sources**: Backend API at `EXPO_PUBLIC_API_URL` (default `http://10.11.247.132:8000`)
- **Where it's used**: Expo Router route at `(app)/chat`.

### `mobile_app/src/app/(app)/live.tsx` (Live Video Chat Screen)
- **What it does**: Live video + audio chat via WebSocket. Features:
  - Camera preview with `CameraView` (expo-camera)
  - Audio streaming with VAD-based silence detection
  - Frame capture every 2 seconds sent via WebSocket
  - TTS playback queue
  - Full-duplex communication via `/api/live/ws`
- **Data sources**: Backend WebSocket at `ws://<API_URL>/api/live/ws`
- **Where it's used**: Expo Router route at `(app)/live`.

### `mobile_app/src/services/api.ts`
- **What it does**: API service layer with functions:
  - `fetchSessions()` — GET `/api/sessions`
  - `loadSessionHistory()` — GET `/api/sessions/{id}/history`
  - `sendChatMessage()` — POST `/api/chat`
  - `sendAudioMessage()` — POST `/api/chat/audio` (multipart upload via expo-file-system)
  - `uploadFile()` — POST `/api/upload`
  - `generateImage()` — POST `/api/generate_image`
- **Data sources**: Backend API, Supabase for auth tokens
- **Where it's used**: Imported by `chat.tsx`.

### `mobile_app/src/utils/supabaseClient.ts`
- **What it does**: Creates Supabase client with AsyncStorage for auth persistence.
- **Data sources**: `EXPO_PUBLIC_SUPABASE_URL` + `EXPO_PUBLIC_SUPABASE_ANON_KEY`
- **Where it's used**: Imported by `api.ts`, `chat.tsx`, `live.tsx`, `login.tsx`.

### `mobile_app/src/app/(auth)/login.tsx` (Login Screen)
- **What it does**: Login/signup form using Supabase Auth.
- **Where it's used**: Expo Router route at `(auth)/login`.

---

## 5. Data Flow Summary

```
User Question
    │
    ▼
┌──────────────────────────────────────────────────┐
│ 1. SERVER receives question (POST /api/chat)     │
│    • Authenticates via Supabase JWT               │
│    • Fetches long-term memory from Supabase       │
│    • Creates/retrieves LangGraph thread           │
│    • Builds initial state with question + memory  │
└──────────────────┬───────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────┐
│ 2. LANGGRAPH WORKFLOW (app.py → nodes.py)        │
│    │                                              │
│    ├─ RETRIEVE NODE:                              │
│    │   • Fuzzy-correct question (dictionary)      │
│    │   • Embed question (SentenceTransformer)     │
│    │   • Search Neo4j (vector + fulltext)         │
│    │   • Search Qdrant (user PDF chunks)          │
│    │   • Rerank with CrossEncoder                 │
│    │   • Route: FAQ found → generate, else → gen  │
│    │                                              │
│    ├─ GENERATE NODE (Jio FAQ):                    │
│    │   • NVIDIA LLM + retrieved context → answer  │
│    │                                              │
│    └─ GENERAL GENERATION NODE:                    │
│        • NVIDIA LLM + tools (weather, location)   │
│        • Can save user facts to Supabase memory   │
└──────────────────┬───────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────┐
│ 3. POST-PROCESSING (server.py)                    │
│    • Parse A2UI JSON (weather cards)              │
│    • Return text response + session info          │
│    • (Optional) Generate TTS audio via Sarvam     │
└──────────────────┬───────────────────────────────┘
                   ▼
              Response to client
```

---

## 6. External Services

| Service | Usage | Config Key |
|---------|-------|------------|
| **Supabase** | Auth, user_memory, chat_sessions | `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` |
| **Neo4j** | FAQ vector + fulltext storage | Local `bolt://localhost:7687` |
| **Qdrant Cloud** | User PDF chunk vector storage | `QDRANT_URL`, `QDRANT_API_KEY` |
| **Sarvam AI** | STT (saaras:v3) + TTS (bulbul:v3) | `SARVAM_API_KEY` |
| **NVIDIA AI (NIM)** | Primary LLM + Vision LLM | `NVDIA_API_KEY` |
| **Groq** | Chat session title generation | `GROQ_API_KEY` |
| **OpenWeatherMap** | Weather data | `OPEN_WEATHER_API_KEY` |
| **Cloudflare Workers AI** | Image generation (Flux) | `CLOUDFARE_ACCOUNT_ID`, `WORKERS_API_KEY` |

---

## 7. Running the Application

```bash
# 1. Backend
cd jio_faq_chatbot
source venv/bin/activate
uvicorn server:server --host 0.0.0.0 --port 8000

# 2. Frontend
cd frontend
npm run dev          # Vite dev server (default :5173)

# 3. Mobile App
cd mobile_app
npx expo start       # Expo dev server

# 4. Neo4j (required locally)
#   Start Neo4j Desktop or Docker with bolt://localhost:7687
#   Populate with FAQ data from data/jio_faq_data.json

# 5. Gradio (standalone, optional)
python app.py        # Launches on :7860
```
