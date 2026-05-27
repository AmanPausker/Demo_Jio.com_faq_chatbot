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
    and yields the audio data chunks as tuples (sample_rate, numpy_data) 
    for direct streaming playback in Gradio.
    """
    client = AsyncSarvamAI(api_subscription_key=API_KEY)

    try:
        import base64
        import wave
        import io
        import numpy as np
        import re
        import asyncio
        
        # Split text into chunks (sentences)
        chunks = [c.strip() for c in re.split(r'(?<=[.!?\n])\s+', input_text) if c.strip()]
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
        
        # Yield results sequentially
        for task in tasks:
            index, audio_bytes = await task
            with wave.open(io.BytesIO(audio_bytes), "rb") as input_wav:
                framerate = input_wav.getframerate()
                frames = input_wav.readframes(input_wav.getnframes())
                data = np.frombuffer(frames, dtype=np.int16)
            yield (framerate, data)
        
    except Exception as e:
        print(f"Error generating speech stream: {e}")
