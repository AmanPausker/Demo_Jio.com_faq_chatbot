import asyncio
import base64
from sarvamai import AsyncSarvamAI, AudioOutput
import os 
from dotenv import load_dotenv

load_dotenv(override = True)
API_KEY = os.getenv("SARVAM_API_KEY")

import uuid

async def generate_speech(input_text: str):
    """
    Connects to Sarvam's TTS API, converts the input_text into speech,
    and returns the audio data as a single tuple (sample_rate, numpy_data) 
    for direct playback in Gradio.
    """
    client = AsyncSarvamAI(api_subscription_key=API_KEY)

    try:
        import base64
        import wave
        import io
        import numpy as np
        import re
        import asyncio
        
        # Split text into sentences
        sentences = [c.strip() for c in re.split(r'(?<=[.!?\n])\s+', input_text) if c.strip()]
        
        # Group sentences to avoid sending too many concurrent API requests
        chunks = []
        current_chunk = ""
        for s in sentences:
            if len(current_chunk) + len(s) < 200:
                current_chunk += s + " "
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = s + " "
        if current_chunk:
            chunks.append(current_chunk.strip())
            
        if not chunks:
            chunks = [input_text]
            
        async def get_chunk(c, index):
            res = await client.text_to_speech.convert(
                text=c,
                target_language_code="en-IN",
                speaker="shubh",
                model="bulbul:v3"
            )
            return index, base64.b64decode(res.audios[0])
            
        # Launch all tasks in parallel
        tasks = [asyncio.create_task(get_chunk(c, i)) for i, c in enumerate(chunks)]
        results = await asyncio.gather(*tasks)
        results.sort(key=lambda x: x[0])
        
        audio_data_list = []
        framerate = None
        for i, (_, audio_bytes) in enumerate(results):
            with wave.open(io.BytesIO(audio_bytes), "rb") as input_wav:
                if i == 0:
                    framerate = input_wav.getframerate()
                frames = input_wav.readframes(input_wav.getnframes())
                audio_data_list.append(np.frombuffer(frames, dtype=np.int16))
                
        if audio_data_list:
            return (framerate, np.concatenate(audio_data_list))
        
    except Exception as e:
        print(f"Error generating speech: {e}")

    return None
