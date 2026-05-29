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

import uuid
import re
import json

def process_a2ui_messages(answer: str):
    a2ui_msgs = []
    surface_id = f"chat_{uuid.uuid4().hex[:8]}"
    spoken_text = answer
    new_answer = answer
    
    json_match = re.search(r'\{[\s\S]*\}', answer)
    if json_match:
        try:
            parsed = json.loads(json_match.group(0))
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
        except Exception as e:
            print(f"JSON Parse Error: {e}")
            
    return new_answer, spoken_text, a2ui_msgs, surface_id

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
    new_answer, spoken_text, a2ui_msgs, surface_id = process_a2ui_messages(answer)
    
    # Disable TTS for text chat
    return {
        "text": new_answer,
        "audio_base64": None,
        "a2ui_messages": a2ui_msgs,
        "surface_id": surface_id
    }

@server.post("/api/chat/audio")
async def chat_audio(audio: UploadFile = File(...)):
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
        
    initial_state = {"question": user_message, "messages": [], "context": "", "answer": ""}
    final_state = await langgraph_app.ainvoke(initial_state)
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:server", host="0.0.0.0", port=8000, reload=True)
