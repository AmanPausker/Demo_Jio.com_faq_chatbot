# Mobile App Architecture & Workflow

## Overview

The mobile app is built with **Expo (SDK 54) / React Native** using **expo-router** for file-based routing, **Supabase** for auth + session storage, and a **FastAPI** backend for all AI/chat services.

```
┌──────────────────────────────────────────────────────────┐
│                  Expo React Native App                    │
│                                                          │
│  ┌───────────┐    ┌───────────┐    ┌──────────────────┐ │
│  │ (auth)/   │    │ (app)/    │    │ (app)/           │ │
│  │ login.tsx │    │ chat.tsx  │    │ live.tsx         │ │
│  │           │    │           │    │                  │ │
│  │ Email/pwd │    │ Text msg  │    │ Camera viewport  │ │
│  │ Supabase  │    │ Voice VAD │    │ VAD audio stream │ │
│  │ sign in   │    │ File upl. │    │ WebSocket to     │ │
│  │ sign up   │    │ Image gen │    │ backend          │ │
│  └─────┬─────┘    └─────┬─────┘    └────────┬─────────┘ │
│        │                │                    │           │
│        ▼                ▼                    ▼           │
│  ┌──────────────────────────────────────────────────┐   │
│  │              Services Layer (api.ts)              │   │
│  │  REST (axios) + File upload (expo-file-system)   │   │
│  │  + WebSocket (raw)                               │   │
│  └──────────────────────┬───────────────────────────┘   │
│                         │                                │
│  ┌──────────────────────┴───────────────────────────┐   │
│  │            Supabase Client (supabaseClient.ts)    │   │
│  │            Auth, Session persistence              │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────┬────────────────────────────┘
                              │
                              │ HTTPS / WSS
                              ▼
              ┌──────────────────────────────┐
              │      FastAPI Backend          │
              │      server.py (port 8000)    │
              │      - /api/chat              │
              │      - /api/chat/audio        │
              │      - /api/sessions          │
              │      - /api/live/ws           │
              │      - /api/generate_image    │
              │      - /api/upload            │
              └──────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | Expo SDK 54 / React Native 0.81.5 |
| Language | TypeScript |
| Routing | expo-router (file-based) |
| Auth | Supabase (email/password, JWT) |
| HTTP | axios + expo-file-system (uploads) |
| Real-time | Raw WebSocket |
| Camera | expo-camera (CameraView) |
| Audio recording | expo-av |
| Audio playback | expo-av (Audio.Sound) |
| Animations | react-native-reanimated |
| Navigation Drawer | @react-navigation/drawer |
| Async Storage | @react-native-async-storage/async-storage |

---

## File Structure

```
mobile_app/
├── app.json                     # Expo config (plugins, icons, splash)
├── package.json                 # Dependencies
├── tsconfig.json                # TypeScript config
├── src/
│   ├── app/
│   │   ├── _layout.tsx          # Root layout — auth gating
│   │   ├── (auth)/
│   │   │   ├── _layout.tsx      # Auth stack layout
│   │   │   └── login.tsx        # Login/Signup screen
│   │   └── (app)/
│   │       ├── _layout.tsx      # Drawer layout (session sidebar)
│   │       ├── chat.tsx         # Main chat screen (text/voice/live entry)
│   │       └── live.tsx         # Live camera chat screen
│   ├── components/              # Shared UI components
│   ├── constants/               # Theme constants
│   ├── hooks/                   # Custom hooks
│   ├── services/
│   │   └── api.ts               # API client (all server calls)
│   └── utils/
│       └── supabaseClient.ts    # Supabase client init
```

---

## Routing & Navigation

### Root Layout (`_layout.tsx`)
- Checks `supabase.auth.getSession()` on mount
- Subscribes to `onAuthStateChange` for real-time session updates
- If **no session** and not in `(auth)` group → redirect to `/(auth)/login`
- If **has session** and in `(auth)` group → redirect to `/(app)/chat`

### Auth Group (`(auth)/`)
- Simple stack with `login.tsx`
- Login: `supabase.auth.signInWithPassword({ email, password })`
- Signup: `supabase.auth.signUp({ email, password })` — checks for email verification

### App Group (`(app)/`)
- Uses `expo-router/drawer` with a **custom drawer content** that shows:
  - **Chat History sidebar** — fetches sessions via `fetchSessions()` from API
  - **New Chat** button — navigates with a unique `newChat` timestamp param to force remount
  - Session list — tapping loads that session's history via `loadSessionHistory()`
- Contains two screens:
  - `chat.tsx` — the main chat interface
  - `live.tsx` — live video camera chat

---

## Main Chat Screen (`chat.tsx`) — Workflow

### Screen States
1. **Text mode** — default, shows message list + input bar
2. **Voice message mode** — tap mic icon, record, send/cancel
3. **Voice mode (VAD)** — continuous hands-free voice conversation with animated orb UI
4. **Live camera mode** — accessed via video icon, navigates to `live.tsx`

### Text Chat Flow
```
User types message → handleSendText()
  ├── /imagine <prompt> → Cloudflare Flux.1 Schnell image generation
  │                        → display image in chat
  └── normal text → POST /api/chat { message, session_id }
                     → response includes:
                        - text: AI answer
                        - audio_base64: TTS audio (played automatically)
                        - a2ui_messages: optional weather cards
                        - session_id: persisted for subsequent messages
```

### Voice Mode (VAD) Flow
```
User taps equalizer icon → setIsVoiceMode(true)
  → startVAD():
       Audio.Recording.createAsync(..., onMetering callback, 100ms interval)
  
  handleMetering(db):
    ├── db > -20 dB (user speaking):
    │     - Clear silence timer
    │     - Stop any AI TTS playback (barge-in)
    │     - Set isSpeakingState = true
    │
    └── db <= -20 dB (silence):
          - Start 1.5s silence timeout
          - On timeout: handleSpeechEnd()
              → stopAndUnloadAsync()
              → read WAV file, POST to /api/chat/audio
              → restart VAD loop
          
  Response: TTS audio played back, displayed as text
```

### File Upload Flow
```
Tap + → Upload Document → DocumentPicker (PDF only)
  → POST /api/upload (multipart) → Qdrant vector storage
  → confirmation message in chat
```

---

## Services Layer (`api.ts`)

All API calls go through this module. It:

1. Reads Supabase session to get JWT token
2. Attaches `Authorization: Bearer <token>` header
3. Makes the appropriate HTTP call

### API Endpoints

| Function | Method | Endpoint | Purpose |
|----------|--------|----------|---------|
| `fetchSessions()` | GET | `/api/sessions` | List all user sessions for sidebar |
| `loadSessionHistory(id)` | GET | `/api/sessions/{id}/history` | Load message history |
| `sendChatMessage(text, sid)` | POST | `/api/chat` | Send text, get AI response |
| `sendAudioMessage(uri, sid)` | POST | `/api/chat/audio` | Upload WAV, get STT→AI→TTS |
| `uploadFile(uri, name, sid)` | POST | `/api/upload` | Upload PDF for Qdrant indexing |
| `generateImage(prompt)` | POST | `/api/generate_image` | Generate image via Flux.1 |

---

## State Management

The app uses **React hooks only** (no Redux/Zustand):

| State | Location | Purpose |
|-------|----------|---------|
| `messages[]` | chat.tsx | Chat message list |
| `activeSessionId` | chat.tsx | Current conversation session UUID |
| `isVoiceMode` | chat.tsx | Toggle between text and voice VAD UI |
| `isRecording` | chat.tsx | VAD detected speech in progress |
| `isPlaying` | chat.tsx | TTS playback active |
| `session` | _layout.tsx | Supabase auth session (global via root layout) |
| `messages[]` | live.tsx | Live chat transcript overlay |
| `sessions[]` | (app)/_layout.tsx | Sidebar session list |

---

## Authentication Flow

```
App launches
  → _layout.tsx: supabase.auth.getSession()
  ├── No session → redirect to (auth)/login
  │     → User enters email/password
  │     → signInWithPassword or signUp
  │     → onAuthStateChange fires
  │     → session detected → redirect to (app)/chat
  └── Has session → show (app)/chat
        → Logout button calls supabase.auth.signOut()
        → onAuthStateChange fires with null session
        → redirect to (auth)/login
```

All API calls are authorized via JWT from `supabase.auth.getSession()`. The backend verifies the token on each endpoint using `supabase.auth.get_user(token)`.

---

## Lifecycle & Cleanup

Each screen cleans up on unmount:
- **chat.tsx**: stops recording, unloads audio, clears timers
- **live.tsx**: closes WebSocket, clears frame interval, stops recording, unloads sound
