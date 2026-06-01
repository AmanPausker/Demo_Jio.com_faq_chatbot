# File Functionality

## Backend (Python)

| File | Purpose |
|---|---|
| `agent_state.py` | Defines `GraphState` TypedDict for LangGraph with fields: `messages`, `router`, `question`, `context`, `answer` |
| `app.py` | Main entry point. Builds LangGraph workflow, defines Gradio UI (`gr.Blocks`) with text & audio chat, wires async generators for processing |
| `nodes.py` | Core logic: `retrieve_node` (hybrid search + reranking), `generate_node` (Jio FAQ answer via Cerebras), `general_generation_node` (fallback via Groq + tools) |
| `get_transcript.py` | Real-time STT via Sarvam AI WebSocket. Captures mic via `sounddevice`, Silero VAD for silence detection, returns transcript |
| `get_audio.py` | TTS via Sarvam AI REST API. Splits text into chunks, parallel async requests, concatenates audio |
| `server.py` | FastAPI server for React frontend. Endpoints: `POST /api/chat` (text), `POST /api/chat/audio` (audio file). Processes A2UI messages |
| `tools.py` | LangChain tools: `get_weather` (OpenWeatherMap API), `get_current_location` (IP geolocation) |

## Data

| File | Purpose |
|---|---|
| `data/jio_faq_data.json` | Scraped FAQ data array with `topic`, `sub_topic`, `question`, `answer` fields |
| `data/topics.json` | Topic hierarchy mapping each topic to its sub-topics |

## Frontend (React + Vite)

| File | Purpose |
|---|---|
| `frontend/index.html` | Vite HTML entry point |
| `frontend/package.json` | Dependencies: `react`, `@a2ui/react`, `@a2ui/web_core`, `vad-web`, `zod` |
| `frontend/vite.config.js` | React plugin, excludes `onnxruntime-web` from optimization |
| `frontend/src/main.jsx` | Mounts `<App />` in `#root` |
| `frontend/src/App.jsx` | Main chat UI: text mode, voice mode, client-side VAD via `AnalyserNode`, barge-in, A2UI surface rendering |
| `frontend/src/A2UICatalog.tsx` | A2UI component catalog defining `WeatherCard` with Zod schema validation |
| `frontend/src/index.css` | All styles: dark theme, glassmorphism, animations for circles/thinking/speaking |
| `frontend/src/utils/audioUtils.js` | Converts `Float32Array` to WAV Blob for HTTP upload |
