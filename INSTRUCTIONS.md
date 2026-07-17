# Jio FAQ Chatbot - Setup & Recreation Guide

This guide is designed for anyone (including your future self) to easily recreate, set up, and run this project from scratch. It covers model requirements, environment variables, connecting the Vision and Local LLMs, and building the mobile app.

---

## 1. Prerequisites & Terminals Needed

To fully run the project (Backend, Web Frontend, and Mobile App), you will need to open **4 separate terminal windows**.

Ensure you have installed:
- **Python 3.10+**
- **Node.js 18+**
- **Docker** (for running the Neo4j database)
- **Ollama** (for local LLM inference)

---

## 2. LLM Models Required

This project relies on both backend LLMs and an on-device mobile LLM.

### A. Backend Models (Ollama)
Install Ollama on your machine and download the required models. In your terminal, run:
```bash
# Main generation and routing LLM
ollama pull cow/gemma2_tools:2b

# Vision LLM (for analyzing images and live video chat)
ollama pull qwen-vision
```

### B. Mobile On-Device Model (LiteRT)
The mobile app uses Google's LiteRT for native hardware acceleration. 
- You need the **Gemma 2B LiteRT model** (e.g., `gemma4-E2B-it.litertlm`).
- **Where to put it:** Place this `.litertlm` (or `.task`) file in the `public/` directory of your backend so the mobile app can download it on its first run.
- **Path:** `public/gemma4-E2B-it.litertlm`

---

## 3. Environment Variables (`.env`)

Create a `.env` file in the root directory (`/Users/amanpausker/jio_faq_chatbot/.env`). Here is the template with the necessary API keys you'll need to gather:

```env
# 1. Local LLM Configuration
# If testing mobile on a real device, change localhost to your machine's local IP (e.g. 192.168.1.x)
OLLAMA_BASE_URL="http://localhost:11434"

# 2. Sarvam AI (For Speech-to-Text and Text-to-Speech)
SARVAM_API_KEY="your_sarvam_api_key_here"

# 3. Supabase (For Auth and User Memory)
VITE_SUPABASE_URL="https://your-project-id.supabase.co"
VITE_SUPABASE_ANON_KEY="your_supabase_anon_key_here"
supabase_project_password="your_database_password_here"

# 4. Qdrant (For PDF Ingestion and Retrieval)
QDRANT_URL="https://your-qdrant-cluster-url"
QDRANT_API_KEY="your_qdrant_api_key_here"

# 5. Cloudflare Workers AI (For Image Generation - Flux)
CLOUDFARE_ACCOUNT_ID="your_cloudflare_account_id"
WORKERS_API_KEY="your_cloudflare_workers_api_key"

# 6. OpenWeather (For Weather Tool integration)
OPEN_WEATHER_API_KEY="your_openweather_api_key"
```
*Note: The FastAPI backend will automatically use `OLLAMA_BASE_URL` to connect to both your local text LLM and the Qwen Vision model.*

---

## 4. Step-by-Step Execution Guide

### Terminal 1: Database & Backend
1. **Start Neo4j via Docker**:
   ```bash
   docker run -d --name neo4j -p 7687:7687 -p 7474:7474 \
     -e NEO4J_AUTH=neo4j/password123 \
     -e NEO4J_apoc_export_file_enabled=true \
     -e NEO4J_apoc_import_file_enabled=true \
     -e NEO4J_apoc_import_file_use__neo4j__config=true \
     neo4j:latest
   ```
2. **Setup Python Environment & Install Requirements**:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. **Seed Database (Only on first setup)**:
   ```bash
   python load_to_graph.py
   python embed_faqs.py
   python create_index.py
   ```
4. **Run the Backend Server**:
   ```bash
   uvicorn server:server --host 0.0.0.0 --port 8000
   ```
   *(Running on `0.0.0.0` allows your mobile phone to connect to the backend).*

### Terminal 2: Web Frontend
```bash
cd frontend
npm install
npm run dev
```

### Terminal 3: Mobile App (APK Generation & Running)

Because the mobile app uses a custom Kotlin Native Module for LiteRT, **Expo Go will not work**. You must build a native app (APK for Android).

1. **Install dependencies**:
   ```bash
   cd mobile_app
   npm install
   ```

2. **Generate and Install the APK directly to a connected Android Device / Emulator**:
   ```bash
   npx expo run:android
   ```
   *This command compiles the native Android code (including LiteRT dependencies) and installs the `app-debug.apk` directly onto your connected device.*

3. **Alternative: Build a standalone APK using EAS (Expo Application Services)**:
   If you want an APK file to share with others:
   ```bash
   npm install -g eas-cli
   eas login
   eas build -p android --profile preview
   ```
   *This will generate a download link for the `.apk` file once the cloud build is finished.*

---

## 5. Connecting the Mobile App & Vision Model

- **Vision Model Connectivity**: The backend (`server.py`) natively talks to `qwen-vision` using the `OLLAMA_BASE_URL`. Ensure Ollama is running (`ollama serve`). 
- **Mobile to Backend Connectivity**: When running the mobile app on a physical device, it needs to know your computer's local IP address to connect to the FastAPI server and Ollama. 
  1. Find your machine's local IP (e.g., `192.168.1.5`).
  2. In your mobile app's API client (e.g., `mobile_app/src/services/api.ts`), ensure the backend URL points to `http://192.168.1.5:8000` instead of `localhost`.
  3. Update `.env` `OLLAMA_BASE_URL` to `http://192.168.1.5:11434` if the mobile app queries it directly.
