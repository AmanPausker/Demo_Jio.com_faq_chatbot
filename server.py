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
                                { "id": "root", "component": "WeatherCard", **props }
                            ]
                        }
                    }
                ]
            else:
                if "message" in parsed:
                    new_answer = parsed["message"]
                    spoken_text = parsed["message"]
                elif "text" in parsed:
                    new_answer = parsed["text"]
                    spoken_text = parsed["text"]
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
            messages.append({
                "type": "user" if msg.type == "human" else "ai",
                "content": msg.content
            })
            
    return {"history": messages}

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
from langchain_core.messages import HumanMessage
CLOUDFARE_ID = os.getenv("CLOUDFARE_ACCOUNT_ID")
WORKERS_API_KEY = os.getenv("WORKERS_API_KEY")

from langchain_openai import ChatOpenAI
OPEN_ROUTER_API_KEY = os.getenv("OPEN_ROUTER_API_KEY")

kimi_vision_llm = ChatOpenAI(
    api_key=OPEN_ROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
    model="nvidia/nemotron-nano-12b-v2-vl:free",
    max_tokens=1000
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
                    {"type": "text", "text": "You are a helpful Assistant. Describe this image in detail and tell the user."},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{base64_image}"
                        },
                    },
                ]
            )
        response = kimi_vision_llm.invoke([message])
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

from langchain_cerebras import ChatCerebras
cerebras_llm = ChatCerebras(model="llama3.1-70b", api_key=os.getenv("CEREBRAS_API_KEY"))

class Session:
    def __init__(self, session_id: str, user_id: str):
        self.session_id = session_id
        self.user_id = user_id
        self.frame_buffer: deque = deque(maxlen=10)
        self.conversation_history: list = []
        self.world_state: dict = {
            "objects": {},
            "people": {},
            "text_seen": {},
            "recent_events": []
        }
        self.last_frame_hash: str = ""
        self.is_processing: bool = False
        
        # Audio buffering
        self.audio_buffer = bytearray()
        self.vad_iterator = None

class ConnectionManager:
    def __init__(self):
        self.sessions: dict[str, Session] = {}

    def get_session(self, session_id: str, user_id: str) -> Session:
        if session_id not in self.sessions:
            self.sessions[session_id] = Session(session_id, user_id)
        return self.sessions[session_id]

manager = ConnectionManager()

def scene_changed(frame_b64: str, last_hash: str, threshold: int = 5000) -> tuple[bool, str]:
    current_hash = hashlib.md5(frame_b64[:threshold].encode()).hexdigest()
    changed = current_hash != last_hash
    return changed, current_hash

async def periodic_visual_summary(session: Session, websocket: WebSocket):
    while True:
        await asyncio.sleep(5)
        if not session.frame_buffer or session.is_processing:
            continue
            
        latest_frame = session.frame_buffer[-1]
        changed, current_hash = scene_changed(latest_frame, session.last_frame_hash)
        
        if changed:
            session.last_frame_hash = current_hash
            current_state_str = json.dumps(session.world_state, indent=2)
            prompt_text = f"""You are a realtime world model analyzer.
Look at this image. The current world state is:
{current_state_str}

Identify any changes (objects moved, new people, actions occurring).
Output ONLY valid JSON containing any state updates and new events.
Format:
{{
  "objects": {{ "item_name": {{"location": "new location", "last_seen": "timestamp/now"}} }},
  "people": {{ "person_name": {{"action": "what they are doing"}} }},
  "text_seen": {{ "snippet": "text content" }},
  "new_events": ["user picked up mug", "person entered room"]
}}
Return ONLY the JSON object, without markdown blocks."""
            message = HumanMessage(content=[
                {
                    "type": "text",
                    "text": prompt_text
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{latest_frame}",
                        "detail": "low"
                    }
                }
            ])
            try:
                response = await kimi_vision_llm.ainvoke([message])
                json_str = response.content.strip()
                import re
                json_str = re.sub(r"```json", "", json_str)
                json_str = re.sub(r"```", "", json_str).strip()
                parsed = json.loads(json_str)
                
                if "objects" in parsed: session.world_state["objects"].update(parsed["objects"])
                if "people" in parsed: session.world_state["people"].update(parsed["people"])
                if "text_seen" in parsed: session.world_state["text_seen"].update(parsed["text_seen"])
                if "new_events" in parsed and isinstance(parsed["new_events"], list):
                    session.world_state["recent_events"].extend(parsed["new_events"])
                    # Keep only last 20 events to prevent bloat
                    session.world_state["recent_events"] = session.world_state["recent_events"][-20:]
                
                await websocket.send_json({
                    "type": "visual_summary",
                    "payload": "World state updated."
                })
            except Exception as e:
                print(f"World model update failed: {e}")

def needs_visual_context(question: str) -> bool:
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

def build_live_prompt(session: Session, question: str) -> str:
    parts = []
    parts.append(
        "You are a live visual assistant. You can see through the user's camera. "
        "Answer naturally and conversationally. Be concise."
    )
    
    world_state_str = json.dumps(session.world_state, indent=2)
    parts.append(f"Current World Model:\n{world_state_str}")

    recent = session.conversation_history[-8:]
    if recent:
        parts.append("Recent conversation:")
        for msg in recent:
            prefix = "User" if msg["role"] == "user" else "Assistant"
            parts.append(f"{prefix}: {msg['content']}")

    parts.append(f"Current question: {question}")
    return "\n\n".join(parts)

async def handle_user_question(session: Session, question: str, websocket: WebSocket):
    session.is_processing = True
    session.conversation_history.append({"role": "user", "content": question})

    needs_vision = needs_visual_context(question)
    prompt = build_live_prompt(session, question)

    try:
        if needs_vision and session.frame_buffer:
            latest_frame = session.frame_buffer[-1]
            vision_msg = HumanMessage(content=[
                {"type": "text", "text": f"The user is asking: '{question}'. Answer based on what you see in the image. Be specific and concise."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{latest_frame}", "detail": "high"}}
            ])
            try:
                vis_resp = await kimi_vision_llm.ainvoke([vision_msg])
                visual_desc = vis_resp.content.strip()
            except Exception as e:
                visual_desc = f"[Vision unavailable: {e}]"
                
            final_prompt = f"{prompt}\n\nVisual analysis of camera feed:\n{visual_desc}\n\nAnswer the user's question naturally based on what you see."
            messages = [
                {"role": "system", "content": "You are a helpful live visual assistant. Answer concisely."},
                {"role": "user", "content": final_prompt}
            ]
        else:
            messages = [
                {"role": "system", "content": prompt},
            ]
            for msg in session.conversation_history[-6:]:
                role = "user" if msg["role"] == "user" else "assistant"
                messages.append({"role": role, "content": msg["content"]})
                
        try:
            response = await cerebras_llm.ainvoke(messages)
            answer = response.content
        except Exception:
            groq = ChatGroq(model="llama-3.1-8b-instant", api_key=os.getenv("GROQ_API_KEY"))
            response = await groq.ainvoke(messages)
            answer = response.content

        session.conversation_history.append({"role": "assistant", "content": answer})

        try:
            await websocket.send_json({
                "type": "assistant_response",
                "payload": answer
            })

            from get_audio import generate_speech_stream
            async for audio_chunk_b64 in generate_speech_stream(answer):
                await websocket.send_json({
                    "type": "tts_chunk",
                    "payload": audio_chunk_b64
                })
        except Exception as ws_err:
            print(f"WebSocket closed during response transmission: {ws_err}")
            
    except Exception as e:
        print(f"Error handling question: {e}")
        try:
            await websocket.send_json({"type": "error", "payload": "Failed to generate response"})
        except Exception:
            pass
        
    session.is_processing = False

import torch
import numpy as np
from get_transcript import transcribe_audio_file, _vad_model, VADIterator, SAMPLE_RATE, VAD_WINDOW

async def process_audio_chunk(session: Session, audio_chunk_b64: str, websocket: WebSocket):
    pcm_bytes = base64.b64decode(audio_chunk_b64)
    session.audio_buffer.extend(pcm_bytes)
    print(f"[VAD] Received {len(pcm_bytes)} PCM bytes, buffer total: {len(session.audio_buffer)}")
    
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
    vad_start_detected = False
    while len(session.vad_sample_buffer) >= VAD_WINDOW:
        window = torch.tensor(session.vad_sample_buffer[:VAD_WINDOW], dtype=torch.float32)
        session.vad_sample_buffer = session.vad_sample_buffer[VAD_WINDOW:]
        result = session.vad_iterator(window)
        if result:
            print(f"[VAD] Event detected: {result}")
            if "start" in result:
                vad_start_detected = True
            if "end" in result:
                speech_ended = True
    print(f"[VAD] speech_ended={speech_ended}, remaining_vad_buffer={len(session.vad_sample_buffer)}")
            
    if speech_ended:
        audio_data = bytes(session.audio_buffer)
        session.audio_buffer = bytearray()
        
        import tempfile
        import wave
        
        fd, temp_wav = tempfile.mkstemp(suffix=".wav")
        with os.fdopen(fd, 'wb') as f:
            with wave.open(f, 'wb') as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(SAMPLE_RATE)
                wav_file.writeframes(audio_data)
                
        try:
            with open(temp_wav, "rb") as f:
                wav_bytes = f.read()
            transcript = await transcribe_audio_file(wav_bytes)
            if transcript and transcript.strip():
                import re
                transcript = re.sub(r'(?i)\bjio\s*phones?\s*plus\b', 'Jio Plus', transcript)
                await websocket.send_json({"type": "transcript", "payload": transcript})
                asyncio.create_task(handle_user_question(session, transcript, websocket))
        except Exception as e:
            print(f"STT Error in live chunk: {e}")
        finally:
            if os.path.exists(temp_wav):
                os.remove(temp_wav)

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

        summary_task = asyncio.create_task(periodic_visual_summary(session, websocket))

        try:
            print("[LIVE WS] Entering message loop")
            while True:
                data = await websocket.receive_json()
                event_type = data.get("type")
                payload = data.get("payload")
                if event_type != "video_frame":
                    print(f"[LIVE WS] Received event: {event_type}, payload size: {len(str(payload)[:100])}")

                if event_type == "audio_chunk":
                    print(f"[LIVE WS] Processing audio_chunk, size: {len(payload)}")
                    await process_audio_chunk(session, payload, websocket)

                elif event_type == "audio_file":
                    try:
                        import tempfile
                        import subprocess
                        import os
                        file_bytes = base64.b64decode(payload)
                        fd_in, temp_in = tempfile.mkstemp(suffix=".tmp")
                        fd_out, temp_out = tempfile.mkstemp(suffix=".wav")
                        with os.fdopen(fd_in, 'wb') as f:
                            f.write(file_bytes)
                            
                        # Use ffmpeg to extract 16kHz raw PCM
                        print(f"[LIVE WS] Running ffmpeg on {len(file_bytes)} bytes")
                        result = subprocess.run(["ffmpeg", "-y", "-i", temp_in, "-f", "s16le", "-ac", "1", "-ar", "16000", temp_out], check=True, capture_output=True)
                        with open(temp_out, "rb") as f:
                            pcm_data = f.read()
                        print(f"[LIVE WS] ffmpeg produced {len(pcm_data)} bytes of PCM")
                            
                        # Feed the decoded PCM to process_audio_chunk by encoding to base64
                        b64_pcm = base64.b64encode(pcm_data).decode('utf-8')
                        await process_audio_chunk(session, b64_pcm, websocket)
                    except Exception as e:
                        print(f"Error decoding audio_file: {e}")
                    finally:
                        if os.path.exists(temp_in): os.remove(temp_in)
                        if os.path.exists(temp_out): os.remove(temp_out)

                elif event_type == "video_frame":
                    session.frame_buffer.append(payload)

                elif event_type == "transcript":
                    await handle_user_question(session, payload, websocket)

                elif event_type == "interrupt":
                    session.is_processing = False
                    await websocket.send_json({"type": "interrupt_ack"})

        except WebSocketDisconnect:
            if summary_task:
                summary_task.cancel()
    except Exception as e:
        print(f"Live WS Error: {e}")
        try:
            await websocket.close()
        except:
            pass

if __name__ == "__main__":

    import uvicorn
    uvicorn.run("server:server", host="0.0.0.0", port=8000, reload=False)

