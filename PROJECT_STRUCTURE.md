# Project Structure

```
jio_faq_chatbot/
│
├── .env                              # API keys (Cerebras, Sarvam, Groq, OpenWeather)
├── .gitignore
├── README.md
├── audio_integration.md              # STT/TTS integration docs
│
├── agent_state.py                    # LangGraph state TypedDict
├── app.py                            # Gradio UI + LangGraph workflow orchestration
├── get_audio.py                      # TTS via Sarvam AI (async chunked)
├── get_transcript.py                 # STT via Sarvam AI streaming (WebSocket)
├── nodes.py                          # LangGraph nodes (retrieve, generate, general)
├── server.py                         # FastAPI REST server (for React frontend)
├── tools.py                          # LangChain tools (get_weather, get_current_location)
│
├── data/
│   ├── jio_faq_data.json             # Scraped FAQ data from Jio support pages
│   └── topics.json                   # Topic -> sub-topic hierarchy mapping
│
├── venv/                             # Python virtual environment
├── __pycache__/
│
└── frontend/
    ├── index.html                    # Vite entry HTML
    ├── package.json                  # React dependencies
    ├── package-lock.json
    ├── vite.config.js                # Vite configuration
    ├── eslint.config.js
    ├── public/
    │   ├── favicon.svg
    │   └── icons.svg
    ├── dist/                         # Production build output
    └── src/
        ├── main.jsx                  # React entry point
        ├── App.jsx                   # Main chat UI (text + voice mode, VAD, barge-in)
        ├── App.css                   # Legacy styles
        ├── index.css                 # All styles (dark theme, glassmorphism)
        ├── A2UICatalog.tsx           # A2UI component catalog (WeatherCard)
        └── utils/
            └── audioUtils.js         # Float32Array -> WAV Blob conversion
```
