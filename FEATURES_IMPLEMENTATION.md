# Feature Implementation

## A2UI (Audio to UI)

A protocol that lets the LLM embed rich UI cards (e.g., weather widgets) in its text response.

**Flow:**
1. LLM in `nodes.py:general_generation_node` (line ~46) is prompted to output `WeatherCard` JSON when answering weather queries
2. `server.py:process_a2ui_messages()` (line 23) parses JSON from the answer and builds A2UI protocol messages:
   - `createSurface` — creates a named surface with a catalog URL
   - `updateComponents` — places component instances on that surface
3. Frontend `MessageProcessor` (`@a2ui/web_core`) processes these messages
4. `<A2uiSurface>` renders the registered `WeatherCard` component
5. Component registration in `frontend/src/A2UICatalog.tsx` using `createComponentImplementation` + Zod schema
6. (A Zod schema is a way to define and validate the shape of data in JavaScript or TypeScript using the library Zod.
Think of it as a blueprint for your data—it describes what your data should look like and automatically checks that it matches.)

**Files:** `nodes.py`, `server.py`, `frontend/src/App.jsx`, `frontend/src/A2UICatalog.tsx`

---

## RAG (Retrieval Augmented Generation)

Hybrid search pipeline in `nodes.py:retrieve_node()`:

1. **Fuzzy Query Normalization** (line 98): Corrects ASR typos using `jellyfish.metaphone()` phonetic matching and `difflib.get_close_matches()` string similarity (e.g., "siggy" → "Swiggy", "fibre" → "Fiber")
2. **Brand Normalizer** (line 127): Collapses multi-word brands into single tokens (e.g., "Jio Plus" → "JioPlus")
3. **Vector Search** (line 141): Embeds question with `all-MiniLM-L6-v2`, queries Neo4j vector index (`faq_embeddings`, top 10)
4. **Keyword Search** (line 143): Extracts keywords minus stopwords, builds Lucene query, searches Neo4j fulltext index (`faq_text_index`, top 10)
5. **Graph Traversal** (line 152): Cypher query walks `(Topic)-[:HAS_SUBTOPIC]->(Subtopic)-[:CONTAINS_FAQ]->(FAQ)` to build context
6. **CrossEncoder Reranking** (line 184): `cross-encoder/ms-marco-MiniLM-L-6-v2` scores candidates, sorts descending
7. **Semantic Routing** (line 196): If `best_score < 0.0`, routes to general agent (router: "1"); otherwise uses top 3 contexts for Jio FAQ agent (router: "2")
8. **Generation** (`generate_node`, line 208): `ChatCerebras("gpt-oss-120b")` answers using only provided context

**Files:** `nodes.py`, `agent_state.py`, `app.py`

---

## Data Retrieval

Neo4j graph database with schema:
- Node types: `Topic`, `Subtopic`, `FAQ`
- Relationships: `(Topic)-[:HAS_SUBTOPIC]->(Subtopic)-[:CONTAINS_FAQ]->(FAQ)`
- Indexes: `faq_embeddings` (vector), `faq_text_index` (Lucene fulltext)

Source data: `data/jio_faq_data.json` (scraped FAQ entries) and `data/topics.json` (hierarchy).

**Cypher query** (`nodes.py:152-170`): Combines vector + fulltext results, deduplicates, traverses graph, returns `"Topic: X | Subtopic: Y | Question: Z | Answer: W"` strings.

**Files:** `nodes.py`, `data/jio_faq_data.json`, `data/topics.json`

---

## Voice Search

Two independent paths:

**Server-side (Gradio)** — `get_transcript.py`:
- `sounddevice.InputStream` at 16kHz mono (100ms blocks)
- Streams to Sarvam WebSocket STT (`saaras:v3`, `hi-IN`, `codemix`)
- Silero VAD for silence detection (0.5s timeout)
- Transcript fed into LangGraph pipeline
- Triggered by `app.py:process_audio()`

**Client-side (React)** — `frontend/src/App.jsx`:
- `MediaRecorder` API for audio capture
- Client-side VAD via `AnalyserNode` frequency data (threshold 50, silence 1.5s)
- Audio blob → `POST /api/chat/audio` → backend transcribes via `transcribe_audio_file()` (Sarvam REST API)
- Response includes `audio_base64` for playback

**Files:** `get_transcript.py`, `server.py`, `frontend/src/App.jsx`, `frontend/src/utils/audioUtils.js`

---

## Barge-in Functionality

User can interrupt AI speech playback with their own voice.

**Implementation** in `frontend/src/App.jsx`:
- Inside VAD `checkVolume` callback (line ~223): when `averageVolume > 50`, immediately pauses any playing audio (`audioPlayerRef.current.pause()`) and starts recording
- `playAudio()` function (line ~47): also pauses current playback before starting new audio

Effect: AI stops speaking as soon as user starts talking, enabling natural conversational flow.

---

## General Agent (Fallback)

When no relevant FAQ is found (CrossEncoder score < 0.0), `nodes.py:general_generation_node()` handles queries:
- Uses `ChatGroq("llama-3.1-8b-instant")` with `get_weather` and `get_current_location` tools
- Supports weather queries with A2UI WeatherCard output
- Answers general knowledge questions outside Jio FAQ scope

**Files:** `nodes.py`, `tools.py`

---

## Latency Optimization

- Parallel TTS chunk requests (`get_audio.py`)
- Parallel vector + fulltext search (`nodes.py`)
- CrossEncoder reranks all candidates but only passes top 3 to LLM
- Async generators for streaming Gradio output
