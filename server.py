from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
from app import app as langgraph_app
from get_audio import generate_speech
from get_transcript import transcribe_audio_file

server = FastAPI(title="Jio FAQ Bot API")

server.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str

@server.post("/api/chat")
async def chat(request: ChatRequest):
    user_message = request.message
    
    if not user_message.strip():
        return {"text": "Please enter a message.", "audio_base64": None}
    
    initial_state = {"question": user_message, "messages": [], "context": "", "answer": ""}
    final_state = await langgraph_app.ainvoke(initial_state)
    answer = final_state['answer']
    
    # Generate speech
    b64_audio = await generate_speech(answer, return_base64=True)
    
    return {
        "text": answer,
        "audio_base64": b64_audio
    }

@server.post("/api/chat/audio")
async def chat_audio(audio: UploadFile = File(...)):
    audio_bytes = await audio.read()
    
    user_message = await transcribe_audio_file(audio_bytes)
    
    if not user_message.strip():
        return {
            "text": "🎤 [Audio Mode] No speech detected. Please try speaking again.",
            "user_message": "",
            "audio_base64": None
        }
        
    initial_state = {"question": user_message, "messages": [], "context": "", "answer": ""}
    final_state = await langgraph_app.ainvoke(initial_state)
    answer = final_state['answer']
    
    # Generate speech
    b64_audio = await generate_speech(answer, return_base64=True)
    
    return {
        "text": answer,
        "user_message": user_message,
        "audio_base64": b64_audio
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:server", host="0.0.0.0", port=8000, reload=True)
