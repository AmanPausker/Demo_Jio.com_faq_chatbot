from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, Depends, HTTPException, Header, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
from typing import Optional, List, Dict, Any
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from get_audio import generate_speech
from get_transcript import transcribe_audio_file
import base64
import os
server = FastAPI(title="Jio FAQ Bot API")
from app import workflow

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from dotenv import load_dotenv
from supabase import create_client, Client, ClientOptions
import os
load_dotenv(override=True)

SUPABASE_URL = os.getenv("VITE_SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("VITE_SUPABASE_ANON_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

def get_token(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    return authorization.split(" ")[1]

def get_current_user(token: str = Depends(get_token)):
    try:
        user_response = supabase.auth.get_user(token)
        return user_response.user.id
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

server.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
import os
import shutil
import uuid
from file_workflow import converter_pdf, create_chunking, create_embeddings, store_in_qdrant

import re
import json

def process_pdf_background(temp_file_path: str, filename: str, user_id: str, session_id: str):
    try:
        document_id = str(uuid.uuid4())
        markdown_text = converter_pdf(temp_file_path)
        chunks = create_chunking(markdown_text, document_id, user_id, session_id)
        embeddings = create_embeddings(chunks)
        store_in_qdrant(chunks, embeddings)
        print(f"Background processing finished for {filename}!")
    except Exception as e:
        print(f"Background processing failed for {filename}: {e}")
    finally:
        #Cleaning up the temporary file.
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)


@server.get("/api/test_memory")
async def test_memory(user_id: str = Depends(get_current_user), token: str = Depends(get_token)):
    try:
        user_supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY, options=ClientOptions(headers={"Authorization": f"Bearer {token}"}))
        # Test select
        res = user_supabase.table("user_memory").select("facts").eq("user_id", user_id).execute()
        existing = res.data[0].get("facts", []) if res.data else []
        
        # Test insert/update
        if res.data:
            up_res = user_supabase.table("user_memory").update({"facts": existing + ["Test fact"]}).eq("user_id", user_id).execute()
            return {"status": "update_success", "data": up_res.data}
        else:
            in_res = user_supabase.table("user_memory").insert({"user_id": user_id, "facts": ["Test fact"]}).execute()
            return {"status": "insert_success", "data": in_res.data}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@server.get("/api/memory")
async def get_memory(user_id: str = Depends(get_current_user), token: str = Depends(get_token)):
    try:
        user_supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY, options=ClientOptions(headers={"Authorization": f"Bearer {token}"}))
        res = user_supabase.table("user_memory").select("facts").eq("user_id", user_id).execute()
        long_term_memory = ""
        if res.data and res.data[0].get("facts"):
            long_term_memory = "\n".join(res.data[0]["facts"])
        return {"memory": long_term_memory, "user_id": user_id}
    except Exception as e:
        return {"memory": "", "error": str(e), "user_id": user_id}

def process_a2ui_messages(answer: str):
    a2ui_msgs = []
    surface_id = f"chat_{uuid.uuid4().hex[:8]}"
    spoken_text = answer
    new_answer = answer
    
    cleaned_answer = answer.replace("```json", "").replace("```", "")
    json_match = re.search(r'\{[\s\S]*\}', cleaned_answer)
    if json_match:
        try:
            # Fix common LLM JSON mistakes (single quotes to double quotes, trailing commas)
            json_str = json_match.group(0)
            json_str = re.sub(r"'", '"', json_str)
            json_str = re.sub(r",\s*}", "}", json_str)
            json_str = re.sub(r",\s*]", "]", json_str)
            
            parsed = json.loads(json_str, strict=False)
            if "type" in parsed and parsed["type"] == "WeatherCard":
                props = parsed.get("props", {})
                spoken_text = f"The weather in {props.get('city', 'your location')} is {props.get('temperature', '')} degrees."
                new_answer = f"Here is the weather information for {props.get('city', 'your location')}."
                
                a2ui_msgs = [
                    {
                        "version": "v0.9",
                        "createSurface": { "surfaceId": surface_id, "catalogId": "https://example.com/my-catalog.json" }
                    },
                    {
                        "version": "v0.9",
                        "updateComponents": {
                            "surfaceId": surface_id,
                            "components": [
                                { "id": "root", "component": "WeatherCard", "props": props }
                            ]
                        }
                    }
                ]
            else:
                # Not a WeatherCard — ignore the JSON, keep original answer as plain text
                pass
        except Exception as e:
            print(f"JSON Parse Error: {e}")
            
    return new_answer, spoken_text, a2ui_msgs, surface_id

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None

@server.post("/api/chat")
async def chat(request: ChatRequest, user_id: str = Depends(get_current_user), token: str = Depends(get_token)):
    thread_id = request.session_id or user_id
    config = {"configurable": {"thread_id": thread_id}}
    
    user_supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY, options=ClientOptions(headers={"Authorization": f"Bearer {token}"}))
    user_message = request.message
    
    # Auto-create session if session_id is provided and doesn't exist
    if request.session_id:
        session_res = user_supabase.table("chat_sessions").select("*").eq("id", request.session_id).execute()
        if not session_res.data:
            try:
                client = ChatGroq(model="llama-3.1-8b-instant", api_key=os.getenv("GROQ_API_KEY"))
                title_msg = client.invoke([
                    SystemMessage(content="Generate a short title (max 5 words) for this chat based on the user's first message. Do not include quotes or extra text. If the message is just a greeting, title it 'Greeting'."),
                    HumanMessage(content=user_message)
                ])
                title = title_msg.content.strip('"').strip()
                user_supabase.table("chat_sessions").insert({
                    "id": request.session_id,
                    "user_id": user_id,
                    "title": title
                }).execute()
            except Exception as e:
                print(f"Failed to create session: {e}")
    user_message = request.message
    
    if not user_message.strip():
        return {"text": "Please enter a message.", "audio_base64": None}
    
    # Fetch Long-Term Memory
    memory_res = user_supabase.table("user_memory").select("facts").eq("user_id", user_id).execute()
    long_term_memory = ""
    if memory_res.data and memory_res.data[0].get("facts"):
        long_term_memory = "\n".join(memory_res.data[0]["facts"])
        
    initial_state = {
        "question":user_message, 
        "messages":[("user", user_message)], 
        "context":"", 
        "answer":"", 
        "long_term_memory": long_term_memory,
        "user_id": user_id,
        "token": token
    }
    
    # MAGIC HAPPENS HERE
    async with AsyncSqliteSaver.from_conn_string("checkpoints.db") as memory:
        langgraph_app = workflow.compile(checkpointer=memory)
        final_state = await langgraph_app.ainvoke(initial_state, config = config)
        
    answer = final_state['answer']
    new_answer, spoken_text, a2ui_msgs, surface_id = process_a2ui_messages(answer)
    # ... return response ...

    return {
        "text": new_answer,
        "audio_base64": None,
        "a2ui_messages": a2ui_msgs,
        "surface_id": surface_id
    }

@server.get("/api/sessions")
async def get_sessions(user_id: str = Depends(get_current_user), token: str = Depends(get_token)):
    user_supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY, options=ClientOptions(headers={"Authorization": f"Bearer {token}"}))
    try:
        res = user_supabase.table("chat_sessions").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
        return {"sessions": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@server.get("/api/sessions/{session_id}/history")
async def get_session_history(session_id: str, user_id: str = Depends(get_current_user), token: str = Depends(get_token)):
    user_supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY, options=ClientOptions(headers={"Authorization": f"Bearer {token}"}))
    # Verify ownership
    res = user_supabase.table("chat_sessions").select("*").eq("id", session_id).eq("user_id", user_id).execute()
    if not res.data:
        raise HTTPException(status_code=403, detail="Session not found or access denied")
        
    config = {"configurable": {"thread_id": session_id}}
    async with AsyncSqliteSaver.from_conn_string("checkpoints.db") as memory:
        langgraph_app = workflow.compile(checkpointer=memory)
        state = await langgraph_app.aget_state(config)
        
    messages = []
    if state and hasattr(state, "values") and "messages" in state.values:
        for msg in state.values["messages"]:
            content = msg.content
            a2ui_msgs = []
            
            # If AI message, check if it contains A2UI JSON
            if msg.type != "human":
                from server import process_a2ui_messages
                new_text, _, parsed_a2ui, _ = process_a2ui_messages(content)
                if parsed_a2ui:
                    content = new_text
                    a2ui_msgs = parsed_a2ui
                    
            messages.append({
                "type": "user" if msg.type == "human" else "ai",
                "content": content,
                "a2ui_messages": a2ui_msgs
            })
            
    return {"history": messages}

@server.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str, user_id: str = Depends(get_current_user), token: str = Depends(get_token)):
    user_supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY, options=ClientOptions(headers={"Authorization": f"Bearer {token}"}))
    try:
        # Verify ownership
        res = user_supabase.table("chat_sessions").select("id").eq("id", session_id).eq("user_id", user_id).execute()
        if not res.data:
            raise HTTPException(status_code=403, detail="Session not found or access denied")
            
        # Delete from Supabase
        user_supabase.table("chat_sessions").delete().eq("id", session_id).execute()
        
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@server.post("/api/chat/audio")
async def chat_audio(audio: UploadFile = File(...), session_id: Optional[str] = Form(None), user_id: str = Depends(get_current_user), token: str = Depends(get_token)):
    
    user_supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY, options=ClientOptions(headers={"Authorization": f"Bearer {token}"}))
    audio_bytes = await audio.read()
    
    user_message = await transcribe_audio_file(audio_bytes)
    
    import re
    # Fix common Sarvam STT mistranscriptions
    user_message = re.sub(r'(?i)\bjio\s*phones?\s*plus\b', 'Jio Plus', user_message)
    
    if not user_message.strip():
        return {
            "text": "🎤 [Audio Mode] No speech detected. Please try speaking again.",
            "user_message": "",
            "audio_base64": None
        }
        
    thread_id = session_id or user_id
    config = {"configurable": {"thread_id": thread_id}}
    
    # Auto-create session if session_id is provided and doesn't exist
    if session_id:
        session_res = user_supabase.table("chat_sessions").select("*").eq("id", session_id).execute()
        if not session_res.data:
            try:
                client = ChatGroq(model="llama-3.1-8b-instant", api_key=os.getenv("GROQ_API_KEY"))
                title_msg = client.invoke([
                    SystemMessage(content="Generate a short title (max 5 words) for this audio message based on the transcript. Do not include quotes."),
                    HumanMessage(content=user_message)
                ])
                title = title_msg.content.strip('"').strip()
                user_supabase.table("chat_sessions").insert({
                    "id": session_id,
                    "user_id": user_id,
                    "title": title
                }).execute()
            except Exception as e:
                print(f"Failed to create session: {e}")
                
    # Fetch Long-Term Memory
    memory_res = user_supabase.table("user_memory").select("facts").eq("user_id", user_id).execute()
    long_term_memory = ""
    if memory_res.data and memory_res.data[0].get("facts"):
        long_term_memory = "\n".join(memory_res.data[0]["facts"])
                
    initial_state = {
        "question": user_message, 
        "messages": [("user", user_message)], 
        "context": "", 
        "answer": "",
        "long_term_memory": long_term_memory,
        "user_id": user_id,
        "token": token
    }
    
    async with AsyncSqliteSaver.from_conn_string("checkpoints.db") as memory:
        langgraph_app = workflow.compile(checkpointer=memory)
        final_state = await langgraph_app.ainvoke(initial_state, config=config)
        
    answer = final_state['answer']
    
    new_answer, spoken_text, a2ui_msgs, surface_id = process_a2ui_messages(answer)
        
    # Generate speech only for audio mode
    b64_audio = await generate_speech(spoken_text, return_base64=True)
    
    return {
        "text": new_answer,
        "user_message": user_message,
        "audio_base64": b64_audio,
        "a2ui_messages": a2ui_msgs,
        "surface_id": surface_id
    }

@server.post("/api/upload")
async def upload_document(background_tasks : BackgroundTasks, file: UploadFile = File(...), session_id: str = Form(...), user_id: str = Depends(get_current_user)):
    if not file.filename.endswith(".pdf"):
        return {"error":"Only PDF files are supported."}

    temp_file_path = f"temp_{uuid.uuid4().hex}_{file.filename}"
    try:
        file_bytes = await file.read()
        with open(temp_file_path, "wb") as buffer:
            buffer.write(file_bytes)
        background_tasks.add_task(process_pdf_background, temp_file_path, file.filename, user_id, session_id)
        return {"success": True, "message": f"{file.filename} is uploading and being processed in the background!"}

    except Exception as e:
        return {"error": f"Failed to process file: {str(e)}"}

from langchain_openai import ChatOpenAI
CLOUDFARE_ID = os.getenv("CLOUDFARE_ACCOUNT_ID")
WORKERS_API_KEY = os.getenv("WORKERS_API_KEY")

OPEN_ROUTER_API_KEY = os.getenv("OPEN_ROUTER_API_KEY")

from langchain_openai import ChatOpenAI
kimi_vision_llm = ChatOpenAI(
    model="openai/gpt-4o-mini",
    api_key=os.getenv("OPEN_ROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1",
    max_tokens=250
)
@server.post("/api/vision")
async def analyze_image(image: UploadFile=File(...)):
    try:
        #Read the uploaded image bytes and convert to Base64.File
        image_bytes = await image.read()
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        mime_type = image.content_type or "image/jpeg"
        message = HumanMessage(
                content=[
                    {"type": "text", "text": "Describe this image concisely."},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{base64_image}",
                            "detail": "low"
                        },
                    },
                ]
            )
        response = await kimi_vision_llm.ainvoke([message])
        return {"success":True, "text":response.content}
    except Exception as e:
        return {"error":str(e)}
import requests
from pydantic import BaseModel

class ImageRequest(BaseModel):
    prompt :str
import httpx

@server.post("/api/generate_image")
async def generate_image(request:ImageRequest):
    URL = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFARE_ID}/ai/run/@cf/black-forest-labs/flux-1-schnell"
    headers = {
        "Authorization": f"Bearer {WORKERS_API_KEY}",
        "Content-Type": "application/json"
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(URL, headers = headers, json= {"prompt":request.prompt})
        if response.status_code == 200:
            result = response.json().get("result")
            image_base64 = result.get("image")
            return {"success": True, "image_base64" : image_base64}
        else:
            return {"error":f"Cloudfare Error:{response.text}"}
    except Exception as e:
        return {"error":str(e)}

import base64
import os
from collections import deque
import hashlib
import time

from langchain_groq import ChatGroq
# ChatGroq streams genuine tokens (sub-50ms TTFT) — ChatNVIDIA buffers internally
primary_llm = ChatGroq(model="llama-3.1-8b-instant", api_key=os.getenv("GROQ_API_KEY"), streaming=True)

class Session:
    def __init__(self, session_id: str, user_id: str):
        self.session_id = session_id
        self.user_id = user_id
        self.frame_buffer: deque = deque(maxlen=5)
        self.conversation_history: list = []
        self.world_state: dict = {
            "objects": {},
            "people": {},
            "text_seen": {},
            "recent_events": []
        }
        self.last_region_hashes: tuple = (None, None, None)
        self.is_processing: bool = False
        self.last_activity_time: float = time.time()
        
        # Audio buffering
        self.audio_buffer = bytearray()
        self.vad_iterator = None
        
        # Unified background vision cache (replaces pre_analyze + periodic_summary)
        self.cached_visual_desc: str = ""
        self.cached_visual_time: float = 0
        self.cached_visual_hashes: tuple = (None, None, None)
        self.is_analyzing_vision: bool = False
        self.last_analysis_time: float = 0

    def touch(self):
        self.last_activity_time = time.time()

class ConnectionManager:
    def __init__(self):
        self.sessions: dict[str, Session] = {}
        self._cleanup_task = None

    def get_session(self, session_id: str, user_id: str) -> Session:
        if session_id not in self.sessions:
            self.sessions[session_id] = Session(session_id, user_id)
        self.sessions[session_id].touch()
        return self.sessions[session_id]

    def start_cleanup(self, ttl_seconds: int = 600):
        async def _cleanup():
            while True:
                await asyncio.sleep(120)
                now = time.time()
                stale = [sid for sid, s in self.sessions.items()
                         if now - s.last_activity_time > ttl_seconds]
                for sid in stale:
                    del self.sessions[sid]
                if stale:
                    print(f"[Cleanup] Removed {len(stale)} stale sessions")
        self._cleanup_task = asyncio.create_task(_cleanup())

manager = ConnectionManager()

MIN_ANALYSIS_INTERVAL = 3.0

# Pre-cache shared aiohttp session for TTS
_tts_session = None
async def get_tts_session():
    global _tts_session
    if _tts_session is None:
        import aiohttp
        _tts_session = aiohttp.ClientSession()
    return _tts_session

async def fetch_tts_sentence(text: str) -> str | None:
    """Fetch TTS for a single sentence and return base64 audio string or None."""
    api_key = os.getenv("SARVAM_API_KEY")
    url = "https://api.sarvam.ai/text-to-speech"
    payload = {
        "inputs": [text],
        "target_language_code": "hi-IN",
        "speaker": "shubh",
        "model": "bulbul:v3"
    }
    headers = {"api-subscription-key": api_key}
    try:
        tts_sess = await get_tts_session()
        async with tts_sess.post(url, json=payload, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                if "audios" in data and data["audios"]:
                    return data["audios"][0]
            else:
                err_text = await resp.text()
                print(f"TTS API error {resp.status} for: '{text[:40]}' - Reason: {err_text}")
    except Exception as e:
        print(f"TTS sentence error: {e}")
    return None

def scene_changed(frame_b64: str, last_hashes: tuple[int, str],
                  sample_size: int = 5000) -> tuple[bool, tuple]:
    """Detect scene changes using multi-region hashing.
    Divides frame into 3 regions (top, mid, bottom). A scene change requires
    at least 2 of 3 regions to change, ignoring minor localized movement."""
    total = len(frame_b64)
    if total < 100:
        return False, last_hashes
    region = min(sample_size, total // 3)
    h1 = hashlib.md5(frame_b64[:region].encode()).hexdigest()
    mid_start = max(0, total // 2 - region // 2)
    h2 = hashlib.md5(frame_b64[mid_start:mid_start + region].encode()).hexdigest()
    h3 = hashlib.md5(frame_b64[-region:].encode()).hexdigest()
    new_hashes = (h1, h2, h3)
    if last_hashes[0] is None:
        return False, new_hashes
    changes = sum(1 for a, b in zip(new_hashes, last_hashes) if a != b)
    return changes >= 2, new_hashes



def needs_visual_context(question: str) -> bool:
    q = question.lower().strip()

    negative_patterns = [
        "what is your", "what is the capital", "what is the meaning",
        "what is the difference", "tell me about yourself",
        "what are you", "who are you", "what can you", "how are you",
        "what time", "what date", "what day", "what's your name"
    ]
    for pat in negative_patterns:
        if pat in q:
            return False

    visual_keywords = [
        "what is", "what's", "what are", "what does",
        "what do", "can you see", "look at",
        "read", "tell me about", "describe",
        "what color", "how many", "what kind", "what type",
        "is there", "are there", "do you see",
        "who is", "whose",
        "how does this", "does this look", "show me",
        "can you read", "translate", "identify",
        "recognize", "see this", "looks like",
        "what's happening", "what is happening", "what's on"
    ]

    short_trigger_words = ["this", "that", "these", "those"]
    if q in short_trigger_words or (len(q.split()) <= 3 and any(w in q.split() for w in short_trigger_words)):
        return True

    for keyword in visual_keywords:
        if keyword in q:
            return True
    return False

def build_live_prompt(session: Session, question: str) -> str:
    parts = [
        "You are a live visual assistant. You can see through the user's camera. "
        "Answer naturally and conversationally. Be concise."
    ]


    parts.append(f"Q: {question}")
    return "\n".join(parts)




async def _send_tts_filler(websocket: WebSocket, text: str):
    """Send a short TTS filler to mask vision LLM latency."""
    from get_audio import generate_speech_stream
    try:
        async for chunk in generate_speech_stream(text):
            await websocket.send_json({"type": "tts_chunk", "payload": chunk})
    except Exception:
        pass

_FILLER_PHRASES = ["Let me look...", "Let me see...", "One moment...", "Looking..."]

async def handle_user_question(session: Session, question: str, websocket: WebSocket):
    """
    Streaming LLM → Parallel TTS pipeline.
    - LLM tokens stream in via astream()
    - Sentence boundaries trigger async TTS fetch tasks immediately
    - Producer/consumer queue delivers TTS chunks in order while LLM still streams
    - Result: time-to-first-audio = LLM first sentence latency + TTS latency
      (vs. previously: full LLM latency + TTS latency)
    """
    t_start = time.time()
    session.is_processing = True
    session.conversation_history.append({"role": "user", "content": question})

    needs_vision = needs_visual_context(question)
    prompt_text = build_live_prompt(session, question)

    try:
        messages = []

        if needs_vision and session.frame_buffer:
            latest_frame = session.frame_buffer[-1]

            # Compress image before sending
            try:
                from PIL import Image
                import io
                img_data = base64.b64decode(latest_frame)
                img = Image.open(io.BytesIO(img_data))
                img.thumbnail((512, 512))
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                out_io = io.BytesIO()
                img.save(out_io, format='JPEG', quality=85)
                latest_frame = base64.b64encode(out_io.getvalue()).decode('utf-8')
            except Exception as resize_err:
                print(f"Image resize error: {resize_err}")

            import random
            asyncio.create_task(_send_tts_filler(
                websocket, random.choice(_FILLER_PHRASES)))
            vision_content = [
                {"type": "text", "text": f"The user asks: '{question}'. Describe what you see in the image to answer the question. Be concise and factual. Do not make things up."}
            ]
            vision_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{latest_frame}"}})
            vision_msg = HumanMessage(content=vision_content)
            try:
                t_vision = time.time()
                vis_resp = await asyncio.wait_for(kimi_vision_llm.ainvoke([vision_msg]), timeout=7.0)
                visual_desc = vis_resp.content.strip()
                print(f"[LATENCY] Vision LLM took {(time.time() - t_vision)*1000:.0f}ms")
            except Exception as e:
                print(f"Vision error type: {type(e)}, error: {repr(e)}")
                visual_desc = f"[Vision unavailable: {e}]"

            final_prompt = (
                f"{prompt_text}\n\nVisual analysis of camera feed:\n{visual_desc}\n"
                "Answer the user's question naturally based on what you see."
            )
            messages = [
                {"role": "system", "content": "You are a helpful live visual assistant. Answer concisely."},
                {"role": "user", "content": final_prompt}
            ]
        else:
            messages = [{"role": "system", "content": prompt_text}]
            for msg in session.conversation_history[-6:]:
                role = "user" if msg["role"] == "user" else "assistant"
                messages.append({"role": role, "content": msg["content"]})

        # ── Streaming LLM → Ordered Parallel TTS ──────────────────────────────
        # Sentence boundaries that trigger a TTS request
        SENTENCE_ENDINGS = {'.', '!', '?'}
        # Avoid firing TTS for very short fragments (e.g. "Ok.")
        MIN_SENTENCE_LEN = 12

        full_answer = ""
        tts_queue: asyncio.Queue = asyncio.Queue()

        async def llm_producer():
            """Stream LLM tokens, enqueue ordered TTS tasks on sentence boundaries."""
            nonlocal full_answer
            sentence_buffer = ""
            t_llm = time.time()
            first_token = True
            try:
                async for chunk in primary_llm.astream(messages):
                    if not session.is_processing:
                        print("[STREAM] LLM interrupted by barge-in.")
                        break
                    token = chunk.content
                    if not token:
                        continue
                    full_answer += token
                    sentence_buffer += token
                    if first_token:
                        print(f"[LATENCY] LLM first token: {(time.time() - t_llm)*1000:.0f}ms")
                        first_token = False
                    # Stream text to frontend for live display
                    try:
                        await websocket.send_json({"type": "text_chunk", "payload": token})
                    except Exception:
                        break
                    # Fire TTS as soon as a sentence is complete
                    stripped = sentence_buffer.strip()
                    if stripped and stripped[-1] in SENTENCE_ENDINGS and len(stripped) >= MIN_SENTENCE_LEN:
                        task = asyncio.create_task(fetch_tts_sentence(stripped))
                        await tts_queue.put(task)
                        sentence_buffer = ""
                print(f"[LATENCY] LLM streaming done: {(time.time() - t_llm)*1000:.0f}ms | chars={len(full_answer)}")
            except Exception as e:
                print(f"[STREAM] LLM streaming error: {e}")
            finally:
                # Flush any remaining sentence that didn't end with punctuation
                if sentence_buffer.strip() and session.is_processing:
                    task = asyncio.create_task(fetch_tts_sentence(sentence_buffer.strip()))
                    await tts_queue.put(task)
                await tts_queue.put(None)  # Sentinel: signals consumer to stop

        async def tts_consumer():
            """Consume ordered TTS tasks and forward audio chunks to WebSocket."""
            t_tts = time.time()
            first_chunk = True
            while True:
                task = await tts_queue.get()
                if task is None:
                    break  # Sentinel received — all sentences processed
                if not session.is_processing:
                    task.cancel()
                    continue
                try:
                    audio_b64 = await task
                    if audio_b64:
                        if first_chunk:
                            print(f"[LATENCY] TTS first chunk: {(time.time() - t_tts)*1000:.0f}ms")
                            first_chunk = False
                        await websocket.send_json({"type": "tts_chunk", "payload": audio_b64})
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    print(f"[STREAM] TTS consumer error: {e}")

        # Run producer and consumer concurrently
        await asyncio.gather(llm_producer(), tts_consumer())
        # ─────────────────────────────────────────────────────────────────────

        answer = full_answer or "I'm having trouble thinking right now. Please try again."
        session.conversation_history.append({"role": "assistant", "content": answer})

        # Send the final complete text (for UI to finalize the streaming bubble)
        try:
            await websocket.send_json({"type": "assistant_response", "payload": answer})
        except Exception as ws_err:
            print(f"WebSocket send error (assistant_response): {ws_err}")

        print(f"[LATENCY] Total question→done: {(time.time() - t_start)*1000:.0f}ms")

    except Exception as e:
        print(f"Error handling question: {e}")
        try:
            await websocket.send_json({"type": "error", "payload": "Failed to generate response"})
        except Exception:
            pass

    session.is_processing = False

import torch
import numpy as np
from get_transcript import transcribe_pcm, _vad_model, VADIterator, SAMPLE_RATE, VAD_WINDOW

async def process_audio_chunk(session: Session, audio_chunk_b64: str, websocket: WebSocket):
    pcm_bytes = base64.b64decode(audio_chunk_b64)
    session.audio_buffer.extend(pcm_bytes)
    
    if session.vad_iterator is None:
        session.vad_iterator = VADIterator(
            _vad_model,
            threshold=0.5,
            sampling_rate=SAMPLE_RATE,
            min_silence_duration_ms=1000,
        )
        
    samples = (np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0).tolist()
    
    if not hasattr(session, "vad_sample_buffer"):
        session.vad_sample_buffer = []
        
    session.vad_sample_buffer.extend(samples)
    
    speech_ended = False
    while len(session.vad_sample_buffer) >= VAD_WINDOW:
        window = torch.tensor(session.vad_sample_buffer[:VAD_WINDOW], dtype=torch.float32)
        session.vad_sample_buffer = session.vad_sample_buffer[VAD_WINDOW:]
        result = session.vad_iterator(window)
        if result:
            if "start" in result:
                # User started speaking (barge-in), cancel ongoing generation and TTS
                session.is_processing = False
                try:
                    await websocket.send_json({"type": "interrupt_ack"})
                except Exception:
                    pass
            if "end" in result:
                speech_ended = True
            
    if speech_ended:
        audio_data = bytes(session.audio_buffer)
        session.audio_buffer = bytearray()
        buffer_duration_ms = len(audio_data) / (SAMPLE_RATE * 2) * 1000  # 16-bit = 2 bytes/sample
        print(f"[LATENCY] Speech ended. Buffer: {buffer_duration_ms:.0f}ms of audio")
        
        try:
            t_stt_start = time.time()
            transcript = await transcribe_pcm(audio_data, SAMPLE_RATE)
            t_stt_end = time.time()
            print(f"[LATENCY] STT took {(t_stt_end - t_stt_start)*1000:.0f}ms")
            if transcript and transcript.strip():
                import re
                transcript = re.sub(r'(?i)\bjio\s*phones?\s*plus\b', 'Jio Plus', transcript)
                await websocket.send_json({"type": "transcript", "payload": transcript})
                asyncio.create_task(handle_user_question(session, transcript, websocket))
        except Exception as e:
            print(f"STT Error in live chunk: {e}")

@server.websocket("/api/live/ws")
async def live_chat_websocket(websocket: WebSocket):
    await websocket.accept()
    print("[LIVE WS] WebSocket accepted")

    summary_task = None
    try:
        auth_data = await websocket.receive_json()
        print(f"[LIVE WS] Auth data received: {auth_data.get('type')}")
        payload = auth_data.get("payload", {})
        token = payload.get("token", "")
        session_id = payload.get("session_id", str(uuid.uuid4()))
        
        try:
            user_response = supabase.auth.get_user(token)
            user_id = user_response.user.id
        except Exception:
            await websocket.send_json({"type": "error", "payload": "Authentication failed"})
            await websocket.close()
            return

        print(f"[LIVE WS] Authenticated user: {user_id}, session: {session_id}")
        session = manager.get_session(session_id, user_id)

        try:
            while True:
                data = await websocket.receive_json()
                event_type = data.get("type")
                payload = data.get("payload")

                if event_type == "audio_chunk":
                    await process_audio_chunk(session, payload, websocket)

                elif event_type == "audio_file":
                    try:
                        import subprocess
                        file_bytes = base64.b64decode(payload)
                        proc = await asyncio.create_subprocess_exec(
                            "ffmpeg", "-y", "-i", "pipe:0", "-f", "s16le",
                            "-ac", "1", "-ar", "16000", "pipe:1",
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                        )
                        pcm_data, stderr = await proc.communicate(file_bytes)
                        if proc.returncode != 0:
                            print(f"ffmpeg error: {stderr.decode()[:200]}")
                            continue
                        b64_pcm = base64.b64encode(pcm_data).decode('utf-8')
                        await process_audio_chunk(session, b64_pcm, websocket)
                    except Exception as e:
                        print(f"Error decoding audio_file: {e}")

                elif event_type == "audio_file_full":
                    try:
                        file_bytes = base64.b64decode(payload)
                        transcript = await transcribe_audio_file(file_bytes)
                        if transcript and transcript.strip():
                            import re
                            transcript = re.sub(r'(?i)\bjio\s*phones?\s*plus\b', 'Jio Plus', transcript)
                            await websocket.send_json({"type": "transcript", "payload": transcript})
                            asyncio.create_task(handle_user_question(session, transcript, websocket))
                    except Exception as e:
                        print(f"Error processing audio_file_full: {e}")

                elif event_type == "video_frame":
                    session.frame_buffer.append(payload)
                    session.touch()

                elif event_type == "transcript":
                    await handle_user_question(session, payload, websocket)

                elif event_type == "interrupt":
                    session.is_processing = False
                    await websocket.send_json({"type": "interrupt_ack"})

        except WebSocketDisconnect:
            pass
    except Exception as e:
        print(f"Live WS Error: {e}")
        try:
            await websocket.close()
        except:
            pass

@server.websocket("/api/audio_stream/ws")
async def audio_stream_websocket(websocket: WebSocket):
    """
    Streaming WebSocket for the audio VAD chat mode.
    Pipeline: audio_blob → STT → RAG retrieval → streaming Groq LLM → streaming TTS

    Events sent to client:
      transcript        – recognised speech text
      text_chunk        – single LLM token (FAQ route) or full answer (general route)
      tts_chunk         – base64 WAV audio chunk
      assistant_response – final complete answer (signals end of turn)
      error             – problem description
    """
    await websocket.accept()
    print("[AUDIO WS] Connected")
    try:
        # ── Auth ─────────────────────────────────────────────────────────
        auth_data = await websocket.receive_json()
        payload   = auth_data.get("payload", {})
        token      = payload.get("token", "")
        session_id = payload.get("session_id", str(uuid.uuid4()))
        try:
            user_id = supabase.auth.get_user(token).user.id
        except Exception:
            await websocket.send_json({"type": "error", "payload": "Authentication failed"})
            await websocket.close()
            return

        print(f"[AUDIO WS] Auth ok: {user_id}")
        user_supabase = create_client(
            SUPABASE_URL, SUPABASE_ANON_KEY,
            options=ClientOptions(headers={"Authorization": f"Bearer {token}"})
        )

        # ── Message loop ──────────────────────────────────────────────────
        while True:
            data = await websocket.receive_json()
            if data.get("type") != "audio_blob":
                continue

            t0 = time.time()
            audio_bytes = base64.b64decode(data["payload"])

            # 1. STT ─────────────────────────────────────────────────────
            try:
                transcript = await transcribe_audio_file(audio_bytes)
            except Exception as e:
                await websocket.send_json({"type": "error", "payload": f"STT failed: {e}"})
                continue

            import re as _re
            transcript = _re.sub(r'(?i)\bjio\s*phones?\s*plus\b', 'Jio Plus', transcript or "")
            print(f"[LATENCY] STT: {(time.time()-t0)*1000:.0f}ms → '{transcript}'")

            if not transcript.strip():
                await websocket.send_json({"type": "transcript", "payload": ""})
                continue
            await websocket.send_json({"type": "transcript", "payload": transcript})

            # 2. Long-term memory ─────────────────────────────────────────
            long_term_memory = ""
            try:
                mem = user_supabase.table("user_memory").select("facts").eq("user_id", user_id).execute()
                if mem.data and mem.data[0].get("facts"):
                    long_term_memory = "\n".join(mem.data[0]["facts"])
            except Exception:
                pass

            # 3. RAG Retrieval (sync → thread executor) ──────────────────
            from nodes import retrieve_node
            from langchain_core.messages import HumanMessage as _HM
            config = {"configurable": {"thread_id": session_id}}
            retrieve_state = {
                "question": transcript,
                "messages": [_HM(content=transcript)],
                "context": "", "answer": "",
                "long_term_memory": long_term_memory,
                "user_id": user_id, "token": token
            }
            t_ret = time.time()
            retrieval_result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: retrieve_node(retrieve_state, config)
            )
            context = retrieval_result.get("context", "")
            router  = retrieval_result.get("router", 1)
            print(f"[LATENCY] Retrieval: {(time.time()-t_ret)*1000:.0f}ms, router={router}")

            full_answer = ""
            SENTENCE_ENDINGS = {'.', '!', '?'}
            MIN_SENTENCE_LEN = 12

            if router == 2 and context:
                # ── FAQ: streaming Groq + parallel TTS ───────────────────
                system_prompt = (
                    "You are a helpful JIO customer support assistant. "
                    "Unless specified otherwise in the LONG TERM MEMORY, your default name is Jio Assistant.\n"
                    "Use the provided CONTEXT to answer the user's question about Jio.\n\n"
                    f"USER'S LONG TERM MEMORY:\n{long_term_memory}\n\n"
                    "INSTRUCTIONS:\n"
                    "1. Answer using ONLY the provided context for Jio-related questions.\n"
                    "2. If context doesn't contain the answer, say you couldn't find it in the Jio FAQs.\n"
                    "3. Do not guess or fabricate information.\n\n"
                    f"CONTEXT:\n{context}"
                )
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": transcript}
                ]
                tts_q: asyncio.Queue = asyncio.Queue()

                async def faq_llm_producer():
                    nonlocal full_answer
                    buf = ""
                    t_llm = time.time(); first = True
                    try:
                        async for chunk in primary_llm.astream(messages):
                            tok = chunk.content
                            if not tok:
                                continue
                            full_answer += tok; buf += tok
                            if first:
                                print(f"[LATENCY] LLM first token: {(time.time()-t_llm)*1000:.0f}ms")
                                first = False
                            try:
                                await websocket.send_json({"type": "text_chunk", "payload": tok})
                            except Exception:
                                break
                            s = buf.strip()
                            if s and s[-1] in SENTENCE_ENDINGS and len(s) >= MIN_SENTENCE_LEN:
                                await tts_q.put(asyncio.create_task(fetch_tts_sentence(s)))
                                buf = ""
                        print(f"[LATENCY] LLM done: {(time.time()-t_llm)*1000:.0f}ms")
                        # Send the full text to the UI immediately!
                        try:
                            await websocket.send_json({"type": "assistant_response", "payload": full_answer})
                        except Exception:
                            pass
                    except Exception as e:
                        print(f"[AUDIO WS] LLM error: {e}")
                    finally:
                        if buf.strip():
                            await tts_q.put(asyncio.create_task(fetch_tts_sentence(buf.strip())))
                        await tts_q.put(None)

                async def faq_tts_consumer():
                    t_tts = time.time(); first = True
                    while True:
                        task = await tts_q.get()
                        if task is None:
                            break
                        try:
                            b64 = await task
                            if b64:
                                if first:
                                    print(f"[LATENCY] TTS first chunk: {(time.time()-t_tts)*1000:.0f}ms")
                                    first = False
                                await websocket.send_json({"type": "tts_chunk", "payload": b64})
                        except Exception as e:
                            print(f"[AUDIO WS] TTS err: {e}")

                await asyncio.gather(faq_llm_producer(), faq_tts_consumer())

            else:
                # ── General (tool-capable): blocking LLM + streaming TTS ─
                from nodes import general_generation_node
                gen_state = {**retrieve_state, "question": transcript,
                             "messages": [_HM(content=transcript)]}
                t_gen = time.time()
                gen_result = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: general_generation_node(gen_state)
                )
                full_answer = gen_result.get("answer", "I'm having trouble right now.")
                print(f"[LATENCY] General LLM: {(time.time()-t_gen)*1000:.0f}ms")

                # Send full text chunk immediately to UI!
                await websocket.send_json({"type": "assistant_response", "payload": full_answer})
                
                sentences = [s.strip() for s in _re.split(r'(?<=[.!?])\s+', full_answer)
                             if s.strip() and len(s.strip()) >= 8]
                if not sentences:
                    sentences = [full_answer]
                tts_tasks = [asyncio.create_task(fetch_tts_sentence(s)) for s in sentences]
                t_tts = time.time(); first = True
                for task in tts_tasks:
                    b64 = await task
                    if b64:
                        if first:
                            print(f"[LATENCY] TTS first (general): {(time.time()-t_tts)*1000:.0f}ms")
                            first = False
                        await websocket.send_json({"type": "tts_chunk", "payload": b64})

            print(f"[LATENCY] Total: {(time.time()-t0)*1000:.0f}ms")

    except WebSocketDisconnect:
        print("[AUDIO WS] Disconnected")
    except Exception as e:
        print(f"[AUDIO WS] Error: {e}")
        try:
            await websocket.close()
        except Exception:
            pass

@server.on_event("startup")
async def startup():
    manager.start_cleanup(ttl_seconds=600)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:server", host="0.0.0.0", port=8000, reload=False)

