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
import os
import shutil
import uuid
from file_workflow import converter_pdf, create_chunking, create_embeddings, store_in_qdrant

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

@server.post("/api/upload")
async def upload_document(file: UploadFile = File()):
    if not file.filename.endswith(".pdf"):
        return {"error":"Only PDF files are supported."}

    temp_file_path = f"temp_{uuid.uuid4().hex}_{file.filename}"
    try:
        file_bytes = await file.read()
        with open(temp_file_path, "wb") as buffer:
            buffer.write(file_bytes)
        document_id = str(uuid.uuid4())
        markdown_text = converter_pdf(temp_file_path)
        chunks = create_chunking(markdown_text, document_id)
        embeddings = create_embeddings(chunks)

        store_in_qdrant(chunks, embeddings)

        return {"success": True, "message": f"Successfully processed {len(chunks)} chunks from {file.filename}!"}
    except Exception as e:
        return {"error": f"Failed to process file: {str(e)}"}
    finally:
        if os.path.exists(temp_file_path):
                os.remove(temp_file_path)  #remove the temporary file.

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
CLOUDFARE_ID = os.getenv("CLOUDFARE_ACCOUNT_ID")
WORKERS_API_KEY = os.getenv("WORKERS_API_KEY")

kimi_vision_llm = ChatOpenAI(
    api_key=WORKERS_API_KEY,
    base_url=f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFARE_ID}/ai/v1",
    model="@cf/moonshotai/kimi-k2.6",
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
@server.post("/api/generate_image")
def generate_image(request:ImageRequest):
    URL = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFARE_ID}/ai/run/@cf/black-forest-labs/flux-1-schnell"
    headers = {
        "Authorization": f"Bearer {WORKERS_API_KEY}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.post(URL, headers = headers, json= {"prompt":request.prompt})
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
if __name__ == "__main__":

    import uvicorn
    uvicorn.run("server:server", host="0.0.0.0", port=8000, reload=False)
