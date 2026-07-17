from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, Depends, HTTPException, Header, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
from typing import Optional

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, RemoveMessage
from langchain_ollama import ChatOllama
from get_audio import generate_speech
from get_transcript import transcribe_audio_file
from system_instructions import (
    SESSION_TITLE_PROMPT,
    get_live_voice_jio_prompt,
    get_live_voice_general_prompt,
    get_live_vision_query_prompt,
    LIVE_VISION_SYSTEM_PROMPT,
    get_live_vision_final_prompt,
    get_live_webrtc_faq_prompt
)
import base64
import os
import re
import json
import uuid
import time
import shutil
from collections import deque
import hashlib
import fractions
import numpy as np

from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamTrack
import av

from logger import logger, live_logger

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    manager.start_cleanup(ttl_seconds=600)
    yield

from fastapi.staticfiles import StaticFiles

server = FastAPI(title="Jio FAQ Bot API", lifespan=lifespan)
server.mount("/public", StaticFiles(directory="public"), name="public")
from app import workflow

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from dotenv import load_dotenv
from supabase import create_client, Client, ClientOptions

load_dotenv(override=True)

SUPABASE_URL = os.getenv("VITE_SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("VITE_SUPABASE_ANON_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

from file_workflow import converter_pdf, create_chunking, create_embeddings, store_in_qdrant
import datetime

async def save_messages_to_supabase(token: str, session_id: str, user_msg: str, ai_msg: str, a2ui_msgs: list):
    user_supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY, options=ClientOptions(headers={"Authorization": f"Bearer {token}"}))
    now = datetime.datetime.utcnow().isoformat()
    rows = [
        {"session_id": session_id, "role": "user", "content": user_msg, "a2ui": None, "created_at": now},
        {"session_id": session_id, "role": "ai", "content": ai_msg, "a2ui": json.dumps(a2ui_msgs) if a2ui_msgs else None, "created_at": now},
    ]
    user_supabase.table("chat_messages").insert(rows).execute()
def get_token(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    return authorization.split(" ")[1]


def get_current_user(token: str = Depends(get_token)):
    try:
        user_response = supabase.auth.get_user(token)
        return user_response.user.id
    except Exception as e:
        logger.warning(f"Auth error in get_current_user: {repr(e)}"); raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


server.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def process_pdf_background(temp_file_path: str, filename: str, user_id: str, session_id: str):
    try:
        document_id = str(uuid.uuid4())
        logger.info(f"[PDF] Processing started: file={filename} user={user_id} session={session_id} doc={document_id}")
        markdown_text = converter_pdf(temp_file_path)
        chunks = create_chunking(markdown_text, document_id, user_id, session_id)
        embeddings = create_embeddings(chunks)
        store_in_qdrant(chunks, embeddings)
        logger.info(f"[PDF] Processing complete: file={filename} chunks={len(chunks)} user={user_id}")
    except Exception as e:
        logger.error(f"[PDF] Processing failed: file={filename} user={user_id} error={e}")
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
def generate_session_title_bg(session_id: str, user_id:str, token : str, user_message:str):
    try:
        user_supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY, options =ClientOptions(headers = {"Authorization":f"Bearer {token}"}))
        from langchain_ollama import ChatOllama
        from langchain_core.messages import SystemMessage, HumanMessage
        OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        client = ChatOllama(model="cow/gemma2_tools:2b", base_url=OLLAMA_BASE_URL, think=False, num_ctx=2048, keep_alive=-1)
        title_msg = client.invoke([
            SystemMessage(content=SESSION_TITLE_PROMPT)
            , 
            HumanMessage(content = user_message)
        ])
        title = title_msg.content.strip('"').strip()
        user_supabase.table("chat_sessions").update({"title": title}).eq("id", session_id).execute()
        logger.info(f"[BG TASK] Updated title for session {session_id} to '{title}'")
    except Exception as e:
        logger.error(f"[BG TASK] Failed to generate title: {e}")


def process_a2ui_messages(answer: str):
    a2ui_msgs = []
    surface_id = f"chat_{uuid.uuid4().hex[:8]}"
    spoken_text = answer
    new_answer = answer

    if "WeatherCard" in answer:
        try:
            city_match = re.search(r'"city"\s*:\s*"([^"]+)"', answer)
            temp_match = re.search(r'"temperature"\s*:\s*([\d\.]+)', answer)
            condition_match = re.search(r'"condition"\s*:\s*"([^"]+)"', answer)
            
            if city_match:
                city = city_match.group(1)
                temp = temp_match.group(1) if temp_match else "unknown"
                condition = condition_match.group(1) if condition_match else "unknown"
                
                props = {
                    "city": city,
                    "temperature": float(temp) if temp != "unknown" else None,
                    "condition": condition
                }
                
                spoken_text = f"The weather in {city} is {temp} degrees."
                new_answer = f"Here is the weather information for {city}."
                a2ui_msgs = [
                    {
                        "version": "v0.9",
                        "createSurface": {"surfaceId": surface_id, "catalogId": "https://example.com/my-catalog.json"}
                    },
                    {
                        "version": "v0.9",
                        "updateComponents": {
                            "surfaceId": surface_id,
                            "components": [
                                {"id": "root", "component": "WeatherCard", "props": props}
                            ]
                        }
                    }
                ]
        except Exception as e:
            logger.debug(f"A2UI Extraction Error: {e}")

    return new_answer, spoken_text, a2ui_msgs, surface_id


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    image_base64: Optional[str] = None

class ChatSaveRequest(BaseModel):
    user_message: str
    ai_message: str
    session_id: str
    router: str
    a2ui_messages: Optional[list] = None

class MemoryApplyRequest(BaseModel):
    action: str
    old_fact: Optional[str] = None
    new_fact: Optional[str] = None

class SummaryApplyRequest(BaseModel):
    session_id: str
    summary: str

class MemoryCleanRequest(BaseModel):
    facts: list[str]

@server.post("/api/chat")
async def chat(request: ChatRequest, background_tasks: BackgroundTasks, user_id: str = Depends(get_current_user), token: str = Depends(get_token)):
    t_chat = time.time()
    thread_id = request.session_id or user_id
    config = {"configurable": {"thread_id": thread_id}}
    logger.info(f"[CHAT] user={user_id} session={thread_id} msg_len={len(request.message)}")

    user_supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY, options=ClientOptions(headers={"Authorization": f"Bearer {token}"}))
    user_message = request.message

    # Auto-create session if session_id is provided and doesn't exist
    if request.session_id:
        session_res = user_supabase.table("chat_sessions").select("*").eq("id", request.session_id).execute()
        if not session_res.data:
            try:
                # 1. Immediately insert a placeholder title
                user_supabase.table("chat_sessions").insert({
                    "id": request.session_id,
                    "user_id": user_id,
                    "title": "New Chat"
                }).execute()
                # 2. Tell FastAPI to update the title in the background
                background_tasks.add_task(generate_session_title_bg, request.session_id, user_id, token, user_message)
            except Exception as e:
                logger.debug(f"Failed to create session: {e}")

    if not user_message.strip():
        return {"text": "Please enter a message.", "audio_base64": None}

    initial_state = {
        "question": user_message,
        "messages": [("user", user_message)],
        "context": "",
        "answer": "",
        "user_id": user_id,
        "token": token
    }

    async def event_generator():
        nonlocal user_message
        if request.image_base64:
            try:
                logger.info(f"[VISION] Received image_base64 length={len(request.image_base64)}")
                yield f"data: {json.dumps({'type': 'token', 'payload': ''})}\n\n"
                prompt = user_message if user_message else "What is shown in this image?"
                t_vision_llm = time.time()
                full_answer = await query_qwen_vision(
                    prompt, request.image_base64,
                    max_tokens=512,
                    system_override="Answer the user's question directly based on the image. Be concise."
                )
                vision_llm_ms = (time.time() - t_vision_llm) * 1000
                logger.info(f"[LATENCY] /api/chat vision LLM: {vision_llm_ms:.0f}ms")
                logger.info(f"[VISION] Qwen Vision response: {full_answer}")
                full_answer = full_answer.strip()

                new_answer, spoken_text, a2ui_msgs, surface_id = process_a2ui_messages(full_answer)

                final_payload = json.dumps({
                    "type": "final",
                    "text": new_answer,
                    "audio_base64": None,
                    "a2ui_messages": a2ui_msgs,
                    "surface_id": surface_id,
                    "session_id": thread_id
                })
                yield f"data: {final_payload}\n\n"

                async with AsyncSqliteSaver.from_conn_string("checkpoints.db") as memory:
                    langgraph_app = workflow.compile(checkpointer=memory)
                    await langgraph_app.aupdate_state(
                        config,
                        {"messages": [HumanMessage(content=f"[Attached Image] {prompt}"), AIMessage(content=full_answer)]},
                        as_node="__start__"
                    )
                    await save_messages_to_supabase(token, request.session_id, user_message, new_answer, a2ui_msgs)
            except Exception as e:
                logger.error(f"[VISION API] error: {e}")
                yield f"data: {json.dumps({'type': 'token', 'payload': '[Error analyzing image] '})}\n\n"
            return

        from langchain_core.messages import AIMessageChunk
        async with AsyncSqliteSaver.from_conn_string("checkpoints.db") as memory:
            langgraph_app = workflow.compile(checkpointer=memory)
            full_answer = ""
            router_val = "unknown"
            t_llm_start = time.time()
            first_token = True
            
            try:
                async for event in langgraph_app.astream_events(initial_state, config=config, version="v2"):
                    kind = event["event"]
                    if kind == "on_chat_model_stream":
                        chunk = event["data"]["chunk"]
                        if isinstance(chunk, AIMessageChunk) and chunk.content:
                            if first_token:
                                ttft = (time.time() - t_llm_start) * 1000
                                logger.info(f"[LATENCY] /api/chat time_to_first_token: {ttft:.0f}ms")
                                first_token = False
                            token_payload = json.dumps({"type": "token", "payload": chunk.content})
                            yield f"data: {token_payload}\n\n"
                            full_answer += chunk.content
                llm_ms = (time.time() - t_llm_start) * 1000
            except Exception as e:
                logger.error(f"[CHAT STREAM] Error: {e}")
                
            state = await langgraph_app.aget_state(config)
            if state and hasattr(state, "values"):
                router_val = state.values.get("router", "unknown")
                answer = state.values.get("answer", "") or full_answer
            else:
                answer = full_answer
                
            logger.info(f"[CHAT] Done: user={user_id} session={thread_id} router={router_val} answer_len={len(answer)}")
            logger.info(f"[LATENCY] /api/chat LLM generation: {llm_ms:.0f}ms chars={len(answer)}")
            
            if str(router_val).strip() != "2":
                from nodes import evaluate_and_save_memory_bg
                asyncio.create_task(evaluate_and_save_memory_bg(user_message, answer, user_id, token))
                
            from nodes import summarize_short_term_memory_bg
            asyncio.create_task(summarize_short_term_memory_bg(thread_id))
            
            new_answer, spoken_text, a2ui_msgs, surface_id = process_a2ui_messages(answer)
            await save_messages_to_supabase(token, request.session_id, user_message, new_answer, a2ui_msgs)
            final_payload = json.dumps({
                "type": "final",
                "text": new_answer,
                "audio_base64": None,
                "a2ui_messages": a2ui_msgs,
                "surface_id": surface_id,
                "session_id": thread_id
            })
            yield f"data: {final_payload}\n\n"
        logger.info(f"[LATENCY] /api/chat: total={time.time() - t_chat:.2f}s router={router_val} ans_len={len(answer)}")

    from fastapi.responses import StreamingResponse
    return StreamingResponse(event_generator(), media_type="text/event-stream", background=background_tasks)

@server.post("/api/chat/prepare")
async def prepare_chat(request: ChatRequest, user_id: str = Depends(get_current_user), token: str = Depends(get_token)):
    t_prepare = time.time()
    state = {"question": request.message}
    config = {"configurable": {"thread_id": request.session_id or user_id}}
    
    from nodes import retrieve_node, fetch_user_memories
    from system_instructions import get_general_generation_prompt, get_faq_generation_prompt
    
    # retrieve_node returns a Python dictionary, not an object
    t_rag = time.time()
    router_response = retrieve_node(state, config)
    rag_ms = (time.time() - t_rag) * 1000
    context = router_response.get("context", "")
    router = router_response.get("router", 1)
    
    #fetch the user memories!
    t_mem = time.time()
    memory_context = fetch_user_memories(user_id, token)
    mem_ms = (time.time() - t_mem) * 1000

    if router == 1:
        # You need to assign the result of the function to the 'system_prompt' variable
        system_prompt = get_general_generation_prompt(memory_context)
    else:
        system_prompt = get_faq_generation_prompt(memory_context, context)
    
    total_ms = (time.time() - t_prepare) * 1000
    logger.info(f"[LATENCY] /api/chat/prepare: rag={rag_ms:.0f}ms mem={mem_ms:.0f}ms router={router} context_chars={len(context)} total={total_ms:.0f}ms (NOTE: LLM inference NOT included - runs client-side)")
    
    direct_answer = router_response.get("direct_answer", False)
    answer_text = router_response.get("answer_text", "")
    return {"prompt": system_prompt, "router": router, "context": context, "direct_answer": direct_answer, "answer_text": answer_text}

@server.post("/api/chat/save_history")
async def save_chat_history(request: ChatSaveRequest, background_tasks: BackgroundTasks, user_id: str = Depends(get_current_user), token: str = Depends(get_token)):
    if str(request.router).strip() != "2":
        from nodes import evaluate_and_save_memory_bg
        background_tasks.add_task(evaluate_and_save_memory_bg, request.user_message, request.ai_message, user_id, token)
    config = {"configurable": {"thread_id": request.session_id}}
    
    # 0. Auto-create session if it doesn't exist
    user_supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY, options=ClientOptions(headers={"Authorization": f"Bearer {token}"}))
    if request.session_id:
        session_res = user_supabase.table("chat_sessions").select("*").eq("id", request.session_id).execute()
        if not session_res.data:
            try:
                user_supabase.table("chat_sessions").insert({
                    "id": request.session_id,
                    "user_id": user_id,
                    "title": "New Chat"
                }).execute()
                background_tasks.add_task(generate_session_title_bg, request.session_id, user_id, token, request.user_message)
            except Exception as e:
                logger.debug(f"Failed to create session in save_history: {e}")

    # 1. Update LangGraph State
    async with AsyncSqliteSaver.from_conn_string("checkpoints.db") as memory:
        langgraph_app = workflow.compile(checkpointer=memory)
        await langgraph_app.aupdate_state(
            config,
            {"messages": [HumanMessage(content=request.user_message), AIMessage(content=request.ai_message)]},
            as_node="__start__"
        )
    
    # 2. Save to Supabase
    await save_messages_to_supabase(token, request.session_id, request.user_message, request.ai_message, request.a2ui_messages)
    
    logger.info(f"[CHAT SAVE] Saved history for session={request.session_id} router={request.router}")
    
    return {"success": True}

@server.post("/api/memory/apply")
async def apply_memory(request: MemoryApplyRequest, user_id: str = Depends(get_current_user), token: str = Depends(get_token)):
    user_supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY, options=ClientOptions(headers={"Authorization": f"Bearer {token}"}))
    res = user_supabase.table("user_memory").select("facts").eq("user_id", user_id).execute()
    facts = []
    if res.data:
        facts = res.data[0].get("facts", []) or []
        
    action = request.action.upper()
    new_fact = request.new_fact
    old_fact = request.old_fact

    if action == "ADD" and new_fact and new_fact not in facts:
        facts.append(new_fact)
    elif action == "UPDATE" and new_fact:
        if old_fact in facts:
            facts.remove(old_fact)
        if new_fact not in facts:
            facts.append(new_fact)
    elif action == "DELETE" and old_fact in facts:
        facts.remove(old_fact)
        
    if res.data:
        user_supabase.table("user_memory").update({"facts": facts}).eq("user_id", user_id).execute()
    else:
        user_supabase.table("user_memory").insert({"user_id": user_id, "facts": facts}).execute()
    
    logger.info(f"[MOBILE LTM SAVED] Successfully {action} memory for user {user_id}. New fact: {new_fact} | Current facts: {facts}")
    return {"success": True, "facts": facts}

@server.post("/api/memory/clean")
async def clean_memory(request: MemoryCleanRequest, user_id: str = Depends(get_current_user), token: str = Depends(get_token)):
    user_supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY, options=ClientOptions(headers={"Authorization": f"Bearer {token}"}))
    res = user_supabase.table("user_memory").select("facts").eq("user_id", user_id).execute()
    facts = res.data[0].get("facts", []) if res.data else []
    cleaned = [f for f in facts if f not in request.facts]
    removed = len(facts) - len(cleaned)
    if res.data:
        user_supabase.table("user_memory").update({"facts": cleaned}).eq("user_id", user_id).execute()
    else:
        user_supabase.table("user_memory").insert({"user_id": user_id, "facts": cleaned}).execute()
    logger.info(f"[MEMORY CLEAN] user={user_id} removed={removed} remaining={len(cleaned)}")
    return {"success": True, "removed": removed, "facts": cleaned}

@server.post("/api/chat/apply_summary")
async def apply_summary(request: SummaryApplyRequest, user_id: str = Depends(get_current_user)):
    config = {"configurable": {"thread_id": request.session_id}}
    async with AsyncSqliteSaver.from_conn_string("checkpoints.db") as memory:
        langgraph_app = workflow.compile(checkpointer=memory)
        state = await langgraph_app.aget_state(config)
        
        if not state or not hasattr(state, "values") or "messages" not in state.values:
            return {"success": False, "message": "No state found"}
            
        messages = state.values["messages"]
        if len(messages) <= 5:
            return {"success": False, "message": "Not enough messages"}
            
        messages_to_summarize = messages[:-2]
        summary_message = SystemMessage(content=f"Summary of conversation earlier: {request.summary}")
        
        delete_messages = [RemoveMessage(id=m.id) for m in messages_to_summarize]
        
        await langgraph_app.aupdate_state(config, {"messages": delete_messages}, as_node="__start__")
        await langgraph_app.aupdate_state(config, {"messages": [summary_message]}, as_node="__start__")
        
    logger.info(f"[MOBILE STM SAVED] Updated summary for session={request.session_id}")
    return {"success": True}

class ToolExecuteRequest(BaseModel):
    tool_name: str
    tool_args: dict

@server.post("/api/tools/execute")
async def execute_tools(request : ToolExecuteRequest):
    from tools import get_current_location, get_weather

    if request.tool_name == "get_current_location":
        result = get_current_location.invoke(request.tool_args)
    
    elif request.tool_name == "get_weather":
        result = get_weather.invoke(request.tool_args)
        
    else:
        result = f"Error: Unknown tool {request.tool_name}"
    
    return {"result": str(result)}

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
    res = user_supabase.table("chat_messages")\
        .select("*")\
        .eq("session_id", session_id)\
        .order("created_at")\
        .execute()

    messages = []
    for msg in res.data:
        a2ui = json.loads(msg["a2ui"]) if msg.get("a2ui") else []
        messages.append({
            "type": msg["role"],
            "content": msg["content"],
            "a2ui_messages": a2ui
        })

    return {"history": messages}
    
@server.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str, user_id: str = Depends(get_current_user), token: str = Depends(get_token)):
    user_supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY, options=ClientOptions(headers={"Authorization": f"Bearer {token}"}))
    try:
        res = user_supabase.table("chat_sessions").select("id").eq("id", session_id).eq("user_id", user_id).execute()
        if not res.data:
            raise HTTPException(status_code=403, detail="Session not found or access denied")
        user_supabase.table("chat_sessions").delete().eq("id", session_id).execute()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@server.post("/api/chat/audio")
async def chat_audio(background_tasks: BackgroundTasks, audio: UploadFile = File(...), session_id: Optional[str] = Form(None), user_id: str = Depends(get_current_user), token: str = Depends(get_token)):
    user_supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY, options=ClientOptions(headers={"Authorization": f"Bearer {token}"}))
    audio_bytes = await audio.read()
    logger.info(f"[AUDIO] Received: user={user_id} session={session_id} bytes={len(audio_bytes)}")

    user_message = await transcribe_audio_file(audio_bytes)
    user_message = re.sub(r'(?i)\bjio\s*phones?\s*plus\b', 'Jio Plus', user_message)

    if not user_message.strip():
        logger.warning(f"[AUDIO] No speech detected: user={user_id} session={session_id}")
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
                # 1. Immediately insert a placeholder title
                user_supabase.table("chat_sessions").insert({
                    "id": session_id,
                    "user_id": user_id,
                    "title": "New Chat"
                }).execute()
                # 2. Tell FastAPI to update the title in the background
                background_tasks.add_task(generate_session_title_bg, session_id, user_id, token, user_message)
            except Exception as e:
                logger.debug(f"Failed to create session: {e}")

    initial_state = {
        "question": user_message,
        "messages": [("user", user_message)],
        "context": "",
        "answer": "",
        "user_id": user_id,
        "token": token
    }

    async with AsyncSqliteSaver.from_conn_string("checkpoints.db") as memory:
        langgraph_app = workflow.compile(checkpointer=memory)
        final_state = await langgraph_app.ainvoke(initial_state, config=config)

    answer = final_state['answer']
    router = final_state.get('router', 'unknown')
    
    if str(router).strip() != "2":
        from nodes import evaluate_and_save_memory_bg
        asyncio.create_task(evaluate_and_save_memory_bg(user_message, answer, user_id, token))
        
    from nodes import summarize_short_term_memory_bg
    asyncio.create_task(summarize_short_term_memory_bg(thread_id))
        
    new_answer, spoken_text, a2ui_msgs, surface_id = process_a2ui_messages(answer)
    await save_messages_to_supabase(token, session_id, user_message, new_answer, a2ui_msgs)
    logger.info(f"[AUDIO] Done: user={user_id} session={session_id} transcript_len={len(user_message)} answer_len={len(answer)}")

    b64_audio = await generate_speech(spoken_text, return_base64=True)

    return {
        "text": new_answer,
        "user_message": user_message,
        "audio_base64": b64_audio,
        "a2ui_messages": a2ui_msgs,
        "surface_id": surface_id
    }


@server.post("/api/upload")
async def upload_document(background_tasks: BackgroundTasks, file: UploadFile = File(...), session_id: str = Form(...), user_id: str = Depends(get_current_user)):
    if not file.filename.endswith(".pdf"):
        logger.warning(f"[UPLOAD] Rejected non-PDF: file={file.filename} user={user_id}")
        return {"error": "Only PDF files are supported."}

    temp_file_path = f"temp_{uuid.uuid4().hex}_{file.filename}"
    try:
        file_bytes = await file.read()
        with open(temp_file_path, "wb") as buffer:
            buffer.write(file_bytes)
        background_tasks.add_task(process_pdf_background, temp_file_path, file.filename, user_id, session_id)
        logger.info(f"[UPLOAD] Queued for processing: file={file.filename} user={user_id} session={session_id}")
        return {"success": True, "message": f"{file.filename} is uploading and being processed in the background!"}
    except Exception as e:
        logger.error(f"[UPLOAD] Failed: file={file.filename} user={user_id} error={e}")
        return {"error": f"Failed to process file: {str(e)}"}


@server.post("/api/vision")
async def vision_upload(file: UploadFile = File(...), user_id: str = Depends(get_current_user), token: str = Depends(get_token)):
    try:
        image_bytes = await file.read()
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        text = await query_qwen_vision("What is shown in this image?", base64_image)
        return {"success": True, "text": text}
    except Exception as e:
        logger.error(f"[VISION UPLOAD] error: {e}")
        return {"success": False, "error": str(e)}


OPEN_ROUTER_API_KEY = os.getenv("OPEN_ROUTER_API_KEY")

# kimi_vision_llm removed in favor of direct aiohttp call to qwen-vision

# ChatGroq streams genuine tokens (sub-50ms TTFT)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
primary_llm = ChatOllama(model="cow/gemma2_tools:2b", base_url=OLLAMA_BASE_URL, streaming=True, think=False, num_ctx=2048, keep_alive=-1)


class TTSAudioTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self):
        super().__init__()
        self._queue = asyncio.Queue()
        self._buffer = bytearray()
        self._pts = 0
        self._time_base = fractions.Fraction(1, 16000)

    async def add_audio(self, wav_bytes: bytes):
        import io
        import numpy as np
        try:
            container = av.open(io.BytesIO(wav_bytes))
            resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
            for frame in container.decode(audio=0):
                resampled = resampler.resample(frame)
                for r_frame in resampled:
                    arr = r_frame.to_ndarray()
                    arr = np.clip(arr * 5.0, -32768, 32767).astype(np.int16)
                    await self._queue.put(arr.tobytes())
        except Exception as e:
            logger.error(f"Failed to decode TTS audio for WebRTC: {e}")

    async def add_silence(self, duration: float = 0.5):
        samples = int(16000 * duration)
        pcm = b'\x00' * (samples * 2)
        await self._queue.put(pcm)

    def clear_queue(self):
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._buffer.clear()

    async def recv(self):
        chunk_size = 640  # 320 samples (20ms at 16000Hz)

        while len(self._buffer) < chunk_size:
            try:
                chunk = await asyncio.wait_for(self._queue.get(), timeout=0.02)
                self._buffer.extend(chunk)
            except asyncio.TimeoutError:
                break

        if len(self._buffer) >= chunk_size:
            pcm_data = bytes(self._buffer[:chunk_size])
            del self._buffer[:chunk_size]
        else:
            pcm_data = b'\x00' * chunk_size

        samples = len(pcm_data) // 2
        frame = av.AudioFrame(format='s16', layout='mono', samples=samples)
        frame.sample_rate = 16000
        frame.planes[0].update(pcm_data)
        
        frame.pts = self._pts
        frame.time_base = self._time_base
        self._pts += samples

        # Pace the stream
        if not hasattr(self, "_start"):
            self._start = time.time()

        wait = self._start + (self._pts / 16000) - time.time()
        if wait > 0:
            await asyncio.sleep(wait)

        return frame


class Session:
    def __init__(self, session_id: str, user_id: str, token: str = None):
        self.session_id = session_id
        self.user_id = user_id
        self.token = token
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
        self.current_response_id: str | None = None
        self.last_activity_time: float = time.time()

        # Audio buffering
        self.audio_buffer = bytearray()
        self.vad_iterator = None

        # Streaming STT session (Sarvam WS, lives for the duration of one utterance)
        self.stt_session: "StreamingSTTSession | None" = None

        # Background vision cache
        self.cached_visual_desc: str = ""
        self.cached_visual_time: float = 0
        self.cached_visual_hashes: tuple = (None, None, None)
        self.is_analyzing_vision: bool = False
        self.last_analysis_time: float = 0

        # WebRTC
        self.pc: RTCPeerConnection | None = None
        self.tts_track: TTSAudioTrack | None = None

    def touch(self):
        self.last_activity_time = time.time()


class ConnectionManager:
    def __init__(self):
        self.sessions: dict[str, Session] = {}
        self._cleanup_task = None

    def get_session(self, session_id: str, user_id: str, token: str = None) -> Session:
        if session_id not in self.sessions:
            self.sessions[session_id] = Session(session_id, user_id, token)
        elif token and getattr(self.sessions[session_id], 'token', None) is None:
            self.sessions[session_id].token = token
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
                    logger.debug(f"[Cleanup] Removed {len(stale)} stale sessions")
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
    import re
    # Strip emojis and special symbols that crash the Sarvam TTS API
    clean_text = re.sub(r'[^\w\s.,!?\'"-]', '', text).strip()
    if not re.search(r'[a-zA-Z\u0900-\u097F]', clean_text):
        return None
        
    api_key = os.getenv("SARVAM_API_KEY")
    url = "https://api.sarvam.ai/text-to-speech"
    payload = {
        "inputs": [clean_text],
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
                logger.error(f"[TTS] API error {resp.status} for: '{clean_text[:40]}' - Reason: {err_text}")
    except Exception as e:
        logger.error(f"[TTS] sentence error: {e}")
    return None


def scene_changed(frame_b64: str, last_hashes: tuple,
                  sample_size: int = 5000) -> tuple:
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

async def analyze_scene_background(session):
    """
    Background vision analysis stub to prevent NameError.
    """
    pass


async def query_qwen_vision(prompt: str, base64_image: str,
                           max_tokens: int = 1024, system_override: str = None) -> str:
    import io
    from PIL import Image
    import aiohttp
    import json

    img_data = base64.b64decode(base64_image)
    img = Image.open(io.BytesIO(img_data))
    img.thumbnail((512, 512))
    if img.mode != 'RGB':
        img = img.convert('RGB')
    out_io = io.BytesIO()
    img.save(out_io, format='JPEG', quality=85)
    compressed_b64 = base64.b64encode(out_io.getvalue()).decode('utf-8')

    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    url = f"{OLLAMA_BASE_URL}/api/chat"
    system_text = system_override or 'Output ONLY valid JSON in this exact format: {"description": "1 short sentence max 15 words"}'
    payload = {
        "model": "qwen-vision",
        "format": "json",
        "messages": [
            {
                "role": "system",
                "content": system_text
            },
            {
                "role": "user",
                "content": prompt,
                "images": [compressed_b64]
            },
            {
                "role": "assistant",
                "content": '{"description": "'
            }
        ],
        "options": {
            "num_predict": max_tokens,
            "temperature": 0.1 # Decreased the temperature of the llm to strict more of deterministic responses and faster.
        },
        "stream": False
    }
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                data = await resp.json()
                if "error" in data:
                    logger.error(f"[VISION API] Ollama returned error: {data['error']}")
                    return f"[Vision unavailable: {data['error']}]"
                msg = data.get("message", {})
                content = msg.get("content", "").strip()
                if not content:
                    content = msg.get("thinking", "").strip()
                
                # Prepend the prefill since Ollama returns the continuation
                # This is required because qwen3.5 is reasoning model and is programmed to always reason and output the reasoning.
                # It creates <think> </think> tags and outputs the reasoning and thus increases the latency of responses.
                # To avoid this - We prefill the response with '{"description": "' and check for the same.
                # This reduced the vision-llm's response latency from >22seconds to <5seconds.

                if not content.startswith("{"):
                    full_json_str = '{"description": "' + content
                else:
                    full_json_str = content

                # Try to parse as JSON
                try:
                    parsed = json.loads(full_json_str)
                    if "description" in parsed:
                        content = parsed["description"]
                except Exception:
                    pass

                logger.info(f"[VISION API] response ({len(base64_image)}b img): {content[:200]}")
                return content
    except Exception as e:
        live_logger.error(f"[VISION API] error: {e}")
        return f"[Vision unavailable: {e}]"



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


def build_live_prompt(session: Session, question: str, context: str = "", memory_context: str = "") -> str:
    if context:
        return get_live_voice_jio_prompt(memory_context, context)
    else:
        return get_live_voice_general_prompt(memory_context)


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
    """
    import random
    import base64
    import asyncio

    filler_phrases = [# Combined list for professional filler phrases

    # Analytical & Precise
    "Analyzing the parameters of your request...",
    "Evaluating the requirements...",
    "Synthesizing data to ensure accuracy...",
    "Structuring the information for clarity...",
    "Refining the response for precision...",
    "Cross-referencing the technical details...",
    "Formulating a strategic response...",
    "Conducting a comprehensive review...",
    "Verifying logical consistency...",
    "Filtering for the most relevant insights...",
    
    # Efficiency & Process-Oriented
    "Processing the request...",
    "Compiling the necessary information...",
    "Generating an optimized solution...",
    "Retrieving relevant data points...",
    "Organizing the requested content...",
    "Executing the necessary procedures...",
    "Validating the internal logic...",
    "Preparing the final synthesis...",
    "Synchronizing the data sets...",
    "Optimizing the response architecture...",
    
    # Client-Focused & Supportive
    "Drafting the response for your review...",
    "Assembling the best possible approach for you...",
    "Building a solution tailored to your specifications...",
    "Summarizing the core findings...",
    "Putting together the requested information...",
    "Developing a clear path forward...",
    "Identifying the most relevant insights...",
    "Finalizing the details...",
    "Preparing the documentation for your convenience...",
    "Aligning the output with your objectives..."

         ]
    chosen_phrase = random.choice(filler_phrases)
    # 1. Send the filler word to UI immediately- 
    await websocket.send_json({"type":"filler_word", "payload":chosen_phrase})
    t_start = time.time()
    import uuid
    my_response_id = str(uuid.uuid4())
    session.current_response_id = my_response_id
    session.is_processing = True
    session.conversation_history.append({"role": "user", "content": question})

    needs_vision = True
    
    # 1. Fetch Retrieval Context from Neo4j/Qdrant
    retrieved_context = ""
    t_live_rag = time.time()
    
    # Only fetch retrieval context if we are in live-audio-chat (no video frames)
    if not session.frame_buffer:
        try:
            from nodes import retrieve_node
            from langchain_core.messages import HumanMessage as _HM
            config = {"configurable": {"thread_id": session.session_id}}
            retrieve_state = {
                "question": question,
                "messages": [_HM(content=question)],
                "context": "", "answer": "",
                "user_id": session.user_id, "token": getattr(session, "token", "")
            }
            retrieval_result = await asyncio.to_thread(retrieve_node, retrieve_state, config)
            retrieved_context = retrieval_result.get("context", "")
            live_logger.info(f"[LATENCY] live RAG retrieval: {(time.time() - t_live_rag)*1000:.0f}ms")
        except Exception as e:
            live_logger.error(f"[RETRIEVAL ERROR] {e}")

    memory_context = ""
    from nodes import fetch_user_memories
    t_live_mem = time.time()
    try:
        if getattr(session, "token", None):
            memory_context = await asyncio.to_thread(fetch_user_memories, session.user_id, session.token)
            live_logger.info(f"[LATENCY] live memory fetch: {(time.time() - t_live_mem)*1000:.0f}ms")
    except Exception as e:
        logger.debug(f"Live memory fetch error: {e}")

    prompt_text = build_live_prompt(session, question, retrieved_context, memory_context)

    try:
        messages = []

        is_weather_query = any(kw in question.lower() for kw in ["weather", "temperature", "forecast", "rain", "hot", "cold", "climate", "location", "where am i", "current city"])

        if is_weather_query:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
            from workflow import workflow
            initial_state = {
                "question": question,
                "messages": [("user", question)],
                "context": "", "answer": "",
                "user_id": session.user_id, "token": getattr(session, "token", "")
            }
            config = {"configurable": {"thread_id": session.session_id or session.user_id}}
            try:
                async with AsyncSqliteSaver.from_conn_string("checkpoints.db") as memory:
                    langgraph_app = workflow.compile(checkpointer=memory)
                    final_state = await langgraph_app.ainvoke(initial_state, config=config)
                full_answer = final_state.get('answer', '')
                new_answer, spoken_text, a2ui_msgs, surface_id = process_a2ui_messages(full_answer)
                if a2ui_msgs:
                    try:
                        await websocket.send_json({"type": "a2ui_messages", "payload": a2ui_msgs})
                    except Exception as ws_err:
                        pass
                skip_primary_llm = True
                visual_desc = spoken_text
            except Exception as e:
                live_logger.error(f"[WEATHER LIVE ERROR] {e}")
                is_weather_query = False

        if not is_weather_query and needs_vision and session.frame_buffer:
            latest_frame = session.frame_buffer[-1]

            try:
                t_vision = time.time()
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
                    live_logger.error(f"[VISION] Image resize error: {resize_err}")

                import random
                asyncio.create_task(_send_tts_filler(websocket, random.choice(_FILLER_PHRASES)))
                prompt = get_live_vision_query_prompt(question)
                visual_desc = await asyncio.wait_for(query_qwen_vision(prompt, latest_frame), timeout=45.0)
                
                vision_latency = (time.time() - t_vision) * 1000
                logger.debug(f"[LATENCY] Vision processing took {vision_latency:.0f}ms")
                live_logger.info(
                    f"[VISION] user={session.user_id} session={session.session_id} "
                    f"latency_ms={vision_latency:.0f} "
                    f"response='{visual_desc[:200]}'"
                )
            except Exception as e:
                live_logger.error(f"[VISION ERROR] type={type(e).__name__} error={repr(e)}")
                live_logger.error(
                    f"[VISION] FAILED: user={session.user_id} session={session.session_id} "
                    f"error='{repr(e)}'"
                )
                visual_desc = f"[Vision unavailable: {e}]"

            skip_primary_llm = True

        elif not is_weather_query:
            skip_primary_llm = False
            from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
            
            messages = [SystemMessage(content=prompt_text)]
            last_role = "system"
            
            for msg in session.conversation_history[-3:]:
                role = "user" if msg["role"] == "user" else "assistant"
                content = msg["content"]
                
                # Merge consecutive messages with the same role
                if role == last_role and len(messages) > 1:
                    messages[-1].content += f"\n\n{content}"
                else:
                    if role == "user":
                        messages.append(HumanMessage(content=content))
                    else:
                        messages.append(AIMessage(content=content))
                    last_role = role
        SENTENCE_ENDINGS = {'.', '!', '?'}
        MIN_SENTENCE_LEN = 12

        full_answer = ""
        tts_queue: asyncio.Queue = asyncio.Queue()

        async def custom_ollama_stream(msgs):
            import json, aiohttp, os
            OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            url = f"{OLLAMA_BASE_URL}/v1/chat/completions"
            payload = {
                "model": "cow/gemma2_tools:2b",
                "stream": True,
                "messages": [{"role": "system" if m.type == "system" else "user" if m.type == "human" else "assistant", "content": m.content} for m in msgs]
            }
            async with aiohttp.ClientSession() as sess:
                async with sess.post(url, json=payload) as resp:
                    if resp.status != 200:
                        err_text = await resp.text()
                        logger.error(f"[OLLAMA ERROR] Status {resp.status}: {err_text}")
                        return
                    async for line in resp.content:
                        line = line.decode('utf-8').strip()
                        if not line:
                            continue
                        if line.startswith("data: ") and line != "data: [DONE]":
                            try:
                                data = json.loads(line[6:])
                                delta = data.get("choices", [{}])[0].get("delta", {})
                                yield delta.get("content", ""), delta.get("reasoning", "")
                            except Exception:
                                pass

        async def llm_producer():
            """Stream LLM tokens, enqueue ordered TTS tasks on sentence boundaries."""
            nonlocal full_answer
            sentence_buffer = ""
            t_llm = time.time()
            first_token = True
            
            async def text_to_stream(text):
                yield text, ""
                
            try:
                stream_source = text_to_stream(visual_desc) if skip_primary_llm else custom_ollama_stream(messages)
                async for content_token, reasoning_token in stream_source:
                    if not session.is_processing or session.current_response_id != my_response_id:
                        logger.debug("[STREAM] LLM interrupted by barge-in.")
                        break
                    
                    if reasoning_token:
                        continue
                        
                    token = content_token
                    if not token:
                        continue
                        
                    full_answer += token
                    sentence_buffer += token
                    if first_token:
                        logger.debug(f"[LATENCY] LLM first token: {(time.time() - t_llm)*1000:.0f}ms")
                        first_token = False
                    try:
                        await websocket.send_json({"type": "text_chunk", "payload": token})
                    except Exception:
                        break
                    stripped = sentence_buffer.strip()
                    is_sentence_end = stripped and stripped[-1] in SENTENCE_ENDINGS
                    is_newline = '\n' in token
                    is_too_long = len(stripped) > 400
                    
                    if stripped and len(stripped) >= MIN_SENTENCE_LEN and (is_sentence_end or is_newline or is_too_long):
                        task = asyncio.create_task(fetch_tts_sentence(stripped))
                        await tts_queue.put(task)
                        sentence_buffer = ""
                logger.debug(f"[LATENCY] LLM streaming done: {(time.time() - t_llm)*1000:.0f}ms | chars={len(full_answer)}")
            except Exception as e:
                live_logger.error(f"[STREAM] LLM streaming error: {e}")
            finally:
                if not full_answer and session.is_processing and session.current_response_id == my_response_id:
                    task = asyncio.create_task(fetch_tts_sentence("I'm having trouble thinking right now. Please try again."))
                    await tts_queue.put(task)

                if sentence_buffer.strip() and session.is_processing and session.current_response_id == my_response_id:
                    task = asyncio.create_task(fetch_tts_sentence(sentence_buffer.strip()))
                    await tts_queue.put(task)
                await tts_queue.put(None)  # Sentinel

        async def tts_consumer():
            """Consume ordered TTS tasks and forward audio chunks to WebSocket."""
            t_tts = time.time()
            first_chunk = True
            while True:
                task = await tts_queue.get()
                if task is None:
                    break
                if not session.is_processing or session.current_response_id != my_response_id:
                    task.cancel()
                    continue
                try:
                    audio_b64 = await task
                    if audio_b64:
                        if first_chunk:
                            logger.debug(f"[LATENCY] TTS first chunk: {(time.time() - t_tts)*1000:.0f}ms")
                            first_chunk = False
                            if hasattr(session, "tts_track") and session.tts_track:
                                await session.tts_track.add_silence(0.8)
                        if hasattr(session, "tts_track") and session.tts_track:
                            import base64
                            wav_bytes = base64.b64decode(audio_b64)
                            await session.tts_track.add_audio(wav_bytes)
                        else:
                            await websocket.send_json({"type": "tts_chunk", "payload": audio_b64})
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.debug(f"[STREAM] TTS consumer error: {e}")

        await asyncio.gather(llm_producer(), tts_consumer())

        if not full_answer and (not session.is_processing or session.current_response_id != my_response_id):
            # It was interrupted before it could generate anything!
            # Abort gracefully without polluting history or UI.
            live_logger.info(f"[ABORT] user={session.user_id} question='{question[:30]}' (Interrupted before LLM response)")
            return

        answer = full_answer or "I'm having trouble thinking right now. Please try again."
        session.conversation_history.append({"role": "assistant", "content": answer})

        live_logger.info(
            f"[FINAL ANSWER] user={session.user_id} session={session.session_id} "
            f"question='{question[:80]}' "
            f"total_ms={(time.time() - t_start)*1000:.0f} "
            f"answer='{answer[:200]}'"
        )

        try:
            await websocket.send_json({"type": "assistant_response", "payload": answer})
        except Exception as ws_err:
            live_logger.error(f"[WS] Send error (assistant_response): {ws_err}")

        logger.info(f"[LATENCY] Total question→done: {(time.time() - t_start)*1000:.0f}ms")

    except Exception as e:
        live_logger.error(f"[PRIMARY LLM] Error handling question: {repr(e)}")
        try:
            await websocket.send_json({"type": "error", "payload": "Failed to generate response"})
        except Exception:
            pass

    if session.current_response_id == my_response_id:
        session.is_processing = False


import torch
import numpy as np
from get_transcript import transcribe_pcm, _vad_model, VADIterator, SAMPLE_RATE, VAD_WINDOW, StreamingSTTSession


async def finalize_transcript(session: Session, websocket: WebSocket):
    audio_data = bytes(session.audio_buffer)
    session.audio_buffer = bytearray()
    
    if len(audio_data) == 0:
        return

    buffer_duration_ms = len(audio_data) / (SAMPLE_RATE * 2) * 1000
    logger.debug(f"[LATENCY] Speech ended. Buffer: {buffer_duration_ms:.0f}ms of audio")

    try:
        t_stt_start = time.time()

        # ── Finalise the streaming STT session → get final transcript ──
        transcript = await transcribe_pcm(audio_data, SAMPLE_RATE)
        
        t_stt_end = time.time()
        logger.debug(f"[LATENCY] STT took {(t_stt_end - t_stt_start)*1000:.0f}ms")

        if transcript and transcript.strip():
            transcript = re.sub(r'(?i)\bjio\s*phones?\s*plus\b', 'Jio Plus', transcript)
            await websocket.send_json({"type": "transcript", "payload": transcript})
            asyncio.create_task(handle_user_question(session, transcript, websocket))

    except Exception as e:
        logger.debug(f"STT Error in live chunk: {e}")

async def process_audio_chunk(session: Session, audio_chunk_b64: str, websocket: WebSocket):
    pcm_bytes = base64.b64decode(audio_chunk_b64)
    session.audio_buffer.extend(pcm_bytes)

    if session.vad_iterator is None:
        session.vad_iterator = VADIterator(
            _vad_model,
            threshold=0.95,
            sampling_rate=SAMPLE_RATE,
            min_silence_duration_ms=800,
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
                logger.info(f"[VAD] Speech started")
                
                # Abort any ongoing LLM/TTS processing immediately
                session.current_response_id = None
                session.is_processing = False
                
                asyncio.create_task(analyze_scene_background(session))
                if getattr(session, "tts_track", None):
                    session.tts_track.clear_queue()
                try:
                    await websocket.send_json({"type": "interrupt_ack"})
                    await websocket.send_json({"type": "user_speaking_start"})
                except Exception:
                    pass
            if "end" in result:
                logger.info(f"[VAD] Speech ended")
                speech_ended = True
                try:
                    await websocket.send_json({"type": "user_speaking_end"})
                except Exception:
                    pass

    if speech_ended:
        await finalize_transcript(session, websocket)


async def handle_incoming_track(session: Session, track, websocket: WebSocket):
    logger.info(f"[WebRTC] Incoming track received: {track.kind}")
    resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
    frame_count = 0
    while True:
        try:
            frame = await track.recv()
            frame_count += 1
            resampled_frames = resampler.resample(frame)
            for r_frame in resampled_frames:
                pcm_bytes = r_frame.to_ndarray().tobytes()
                
                # Log max volume occasionally to verify audio isn't completely silent
                if frame_count % 50 == 0:
                    arr = np.frombuffer(pcm_bytes, dtype=np.int16)
                    if len(arr) > 0:
                        logger.info(f"[WebRTC] Audio frame max volume: {np.max(np.abs(arr))} / 32768")

                b64_pcm = base64.b64encode(pcm_bytes).decode('utf-8')
                await process_audio_chunk(session, b64_pcm, websocket)
        except Exception as e:
            logger.error(f"[WebRTC] track ended with error: {e}")
            break
async def handle_incoming_video_track(session: Session, track):
    import io
    import base64
    import time
    from PIL import Image

    last_frame_time = 0
    FRAME_INTERVAL = 2.0

    while True:
        try:
            frame = await track.recv()
            now = time.time()
            if now - last_frame_time >= FRAME_INTERVAL:
                last_frame_time = now
                img = frame.to_image()
                img.thumbnail((512, 512))
                if img.mode != "RGB":
                    img = img.convert('RGB')
                out_io = io.BytesIO()

                img.save(out_io, format = "JPEG", quality = 85)
                compressed_frame = base64.b64encode(out_io.getvalue()).decode('utf-8')
                session.frame_buffer.append(compressed_frame)
                session.touch()

        except Exception as e: #Track ended or connection closed
            break 
@server.websocket("/api/live/ws")
async def live_chat_websocket(websocket: WebSocket):
    await websocket.accept()
    live_logger.info("[LIVE WS] WebSocket accepted")

    try:
        auth_data = await websocket.receive_json()
        logger.debug(f"[LIVE WS] Auth data received: {auth_data.get('type')}")
        payload = auth_data.get("payload", {})
        token = payload.get("token", "")
        session_id = payload.get("session_id", str(uuid.uuid4()))

        try:
            user_response = supabase.auth.get_user(token)
            user_id = user_response.user.id
        except Exception:
            live_logger.warning(f"[LIVE WS] Auth failed for session={session_id}")
            await websocket.send_json({"type": "error", "payload": "Authentication failed"})
            await websocket.close()
            return

        live_logger.info(f"[LIVE WS] Authenticated: user={user_id} session={session_id}")
        session = manager.get_session(session_id, user_id, token)

        # Clear any stale WebRTC connection from previous WebSocket sessions
        if getattr(session, "pc", None) is not None:
            try:
                asyncio.create_task(session.pc.close())
            except Exception:
                pass
            session.pc = None
            session.tts_track = None

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
                            logger.debug(f"ffmpeg error: {stderr.decode()[:200]}")
                            continue
                        b64_pcm = base64.b64encode(pcm_data).decode('utf-8')
                        await process_audio_chunk(session, b64_pcm, websocket)
                    except Exception as e:
                        logger.debug(f"Error decoding audio_file: {e}")

                elif event_type == "audio_file_full":
                    try:
                        file_bytes = base64.b64decode(payload)
                        transcript = await transcribe_audio_file(file_bytes)
                        if transcript and transcript.strip():
                            transcript = re.sub(r'(?i)\bjio\s*phones?\s*plus\b', 'Jio Plus', transcript)
                            await websocket.send_json({"type": "transcript", "payload": transcript})
                            asyncio.create_task(handle_user_question(session, transcript, websocket))
                    except Exception as e:
                        logger.debug(f"Error processing audio_file_full: {e}")

                elif event_type == "video_frame":
                    session.frame_buffer.append(payload)
                    session.touch()

                elif event_type == "transcript":
                    await handle_user_question(session, payload, websocket)

                elif event_type == "interrupt":
                    session.is_processing = False
                    asyncio.create_task(analyze_scene_background(session))
                    if getattr(session, "tts_track", None):
                        session.tts_track.clear_queue()
                    await websocket.send_json({"type": "interrupt_ack"})

                elif event_type == "speech_ended":
                    await finalize_transcript(session, websocket)

                elif event_type == "webrtc_offer":
                    if session.pc is None:
                        session.pc = RTCPeerConnection()
                        session.tts_track = TTSAudioTrack()
                        session.pc.addTrack(session.tts_track)

                        @session.pc.on("track")
                        def on_track(track):
                            if track.kind == "audio":
                                asyncio.create_task(handle_incoming_track(session, track, websocket))
                            elif track.kind == "video":
                                asyncio.create_task(handle_incoming_video_track(session, track))

                    offer = RTCSessionDescription(sdp=payload["sdp"], type=payload["type"])
                    await session.pc.setRemoteDescription(offer)
                    answer = await session.pc.createAnswer()
                    await session.pc.setLocalDescription(answer)
                    await websocket.send_json({
                        "type": "webrtc_answer",
                        "payload": {
                            "sdp": session.pc.localDescription.sdp,
                            "type": session.pc.localDescription.type
                        }
                    })

        except WebSocketDisconnect:
            live_logger.info(f"[LIVE WS] Disconnected: user={user_id} session={session_id}")
            if getattr(session, "pc", None) is not None:
                try:
                    asyncio.create_task(session.pc.close())
                except Exception:
                    pass
                session.pc = None
                session.tts_track = None
    except Exception as e:
        live_logger.error(f"[LIVE WS] Error: {e}")
        try:
            await websocket.close()
        except Exception:
            pass


@server.websocket("/api/audio_stream/ws")
async def audio_stream_websocket(websocket: WebSocket):
    """
    Streaming WebSocket for the audio VAD chat mode.
    Pipeline: audio_blob → STT → RAG retrieval → streaming Groq LLM → streaming TTS

    Events sent to client:
      transcript         – recognised speech text
      text_chunk         – single LLM token (FAQ route) or full answer (general route)
      tts_chunk          – base64 WAV audio chunk
      assistant_response – final complete answer (signals end of turn)
      error              – problem description
    """
    await websocket.accept()
    logger.info("[AUDIO WS] Connected")
    try:
        # ── Auth ─────────────────────────────────────────────────────────
        auth_data = await websocket.receive_json()
        payload = auth_data.get("payload", {})
        token = payload.get("token", "")
        session_id = payload.get("session_id", str(uuid.uuid4()))
        try:
            user_id = supabase.auth.get_user(token).user.id
        except Exception:
            logger.warning(f"[AUDIO WS] Auth failed for session={session_id}")
            await websocket.send_json({"type": "error", "payload": "Authentication failed"})
            await websocket.close()
            return

        logger.info(f"[AUDIO WS] Authenticated: user={user_id} session={session_id}")
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

            transcript = re.sub(r'(?i)\bjio\s*phones?\s*plus\b', 'Jio Plus', transcript or "")
            logger.debug(f"[LATENCY] STT: {(time.time()-t0)*1000:.0f}ms → '{transcript}'")
            logger.info(f"[AUDIO WS] STT: user={user_id} duration_ms={(time.time()-t0)*1000:.0f} transcript='{transcript[:60]}'")

            if not transcript.strip():
                await websocket.send_json({"type": "transcript", "payload": ""})
                continue
            await websocket.send_json({"type": "transcript", "payload": transcript})

            # 3. RAG Retrieval ──────────────────────────────────────────
            from nodes import retrieve_node
            from langchain_core.messages import HumanMessage as _HM
            config = {"configurable": {"thread_id": session_id}}
            retrieve_state = {
                "question": transcript,
                "messages": [_HM(content=transcript)],
                "context": "", "answer": "",
                "user_id": user_id, "token": token
            }
            t_ret = time.time()
            retrieval_result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: retrieve_node(retrieve_state, config)
            )
            context = retrieval_result.get("context", "")
            router = retrieval_result.get("router", 1)
            logger.debug(f"[LATENCY] Retrieval: {(time.time()-t_ret)*1000:.0f}ms, router={router}")

            full_answer = ""
            SENTENCE_ENDINGS = {'.', '!', '?'}
            MIN_SENTENCE_LEN = 12

            if router == 2 and context:
                # ── FAQ: streaming Groq + parallel TTS ───────────────────
                system_prompt = get_live_webrtc_faq_prompt(context)
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": transcript}
                ]
                tts_q: asyncio.Queue = asyncio.Queue()

                async def faq_llm_producer():
                    nonlocal full_answer
                    buf = ""
                    t_llm = time.time()
                    first = True
                    try:
                        async for chunk in primary_llm.astream(messages):
                            tok = chunk.content
                            if not tok:
                                continue
                            full_answer += tok
                            buf += tok
                            if first:
                                logger.debug(f"[LATENCY] LLM first token: {(time.time()-t_llm)*1000:.0f}ms")
                                first = False
                            try:
                                await websocket.send_json({"type": "text_chunk", "payload": tok})
                            except Exception:
                                break
                            s = buf.strip()
                            if s and s[-1] in SENTENCE_ENDINGS and len(s) >= MIN_SENTENCE_LEN:
                                await tts_q.put(asyncio.create_task(fetch_tts_sentence(s)))
                                buf = ""
                        logger.debug(f"[LATENCY] LLM done: {(time.time()-t_llm)*1000:.0f}ms")
                        try:
                            await websocket.send_json({"type": "assistant_response", "payload": full_answer})
                        except Exception:
                            pass
                    except Exception as e:
                        logger.debug(f"[AUDIO WS] LLM error: {e}")
                    finally:
                        if buf.strip():
                            await tts_q.put(asyncio.create_task(fetch_tts_sentence(buf.strip())))
                        await tts_q.put(None)

                async def faq_tts_consumer():
                    t_tts = time.time()
                    first = True
                    while True:
                        task = await tts_q.get()
                        if task is None:
                            break
                        try:
                            b64 = await task
                            if b64:
                                if first:
                                    logger.debug(f"[LATENCY] TTS first chunk: {(time.time()-t_tts)*1000:.0f}ms")
                                    first = False
                                await websocket.send_json({"type": "tts_chunk", "payload": b64})
                        except Exception as e:
                            logger.debug(f"[AUDIO WS] TTS err: {e}")

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
                logger.debug(f"[LATENCY] General LLM: {(time.time()-t_gen)*1000:.0f}ms")

                await websocket.send_json({"type": "assistant_response", "payload": full_answer})

                sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', full_answer)
                             if s.strip() and len(s.strip()) >= 8]
                if not sentences:
                    sentences = [full_answer]
                tts_tasks = [asyncio.create_task(fetch_tts_sentence(s)) for s in sentences]
                t_tts = time.time()
                first = True
                for task in tts_tasks:
                    b64 = await task
                    if b64:
                        if first:
                            logger.debug(f"[LATENCY] TTS first (general): {(time.time()-t_tts)*1000:.0f}ms")
                            first = False
                        await websocket.send_json({"type": "tts_chunk", "payload": b64})

            logger.debug(f"[LATENCY] Total: {(time.time()-t0)*1000:.0f}ms")
            logger.info(f"[AUDIO WS] Turn complete: user={user_id} total_ms={(time.time()-t0)*1000:.0f} answer_len={len(full_answer)}")

    except WebSocketDisconnect:
        logger.info(f"[AUDIO WS] Disconnected: user={user_id} session={session_id}")
    except Exception as e:
        logger.error(f"[AUDIO WS] Error: {e}")
        try:
            await websocket.close()
        except Exception:
            pass


# Startup is now handled by the lifespan context manager


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:server", host="0.0.0.0", port=8000, reload=False, log_level="warning", access_log=False)
