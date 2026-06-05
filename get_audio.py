import asyncio
import base64
from sarvamai import AsyncSarvamAI, AudioOutput
import os 
from dotenv import load_dotenv

load_dotenv(override = True)
API_KEY = os.getenv("SARVAM_API_KEY")

import uuid

async def generate_speech(input_text: str, **kwargs):
    """
    * Takes text input
    * Splits it into smaller chunks
    * Sends chunks to the Sarvam AI TTS API
    * Converts text → speech
    * Downloads audio bytes
    * Combines all audio chunks
    * Returns playable audio
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
                target_language_code="hi-IN",
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
            concatenated_audio = np.concatenate(audio_data_list)
            if kwargs.get("return_base64", False):
                import io
                import wave
                out_io = io.BytesIO()
                with wave.open(out_io, 'wb') as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2) # 16-bit
                    wav_file.setframerate(framerate)
                    wav_file.writeframes(concatenated_audio.tobytes())
                b64_audio = base64.b64encode(out_io.getvalue()).decode('utf-8')
                return b64_audio
            return (framerate, concatenated_audio)
        
    except Exception as e:
        print(f"Error generating speech: {e}")

    return None

_shared_session = None

async def _get_shared_session():
    global _shared_session
    if _shared_session is None:
        import aiohttp
        _shared_session = aiohttp.ClientSession()
    return _shared_session


async def generate_speech_stream(text: str):
    """Generate TTS and yield base64 WAV chunks as they arrive."""
    import os
    import re
    import asyncio

    api_key = os.getenv("SARVAM_API_KEY")
    url = "https://api.sarvam.ai/text-to-speech"

    # Split into sentences for parallel requests
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks = []
    for sentence in sentences:
        if len(sentence) > 200:
            words = sentence.split()
            for i in range(0, len(words), 30):
                chunks.append(" ".join(words[i:i+30]))
        else:
            if sentence.strip():
                chunks.append(sentence.strip())

    if not chunks and text.strip():
        chunks = [text.strip()]

    session = await _get_shared_session()
    headers = {"api-subscription-key": api_key}

    async def fetch_chunk(chunk_text):
        payload = {
            "inputs": [chunk_text],
            "target_language_code": "hi-IN",
            "speaker": "shubh",
            "pitch": 0,
            "pace": 1.0,
            "model": "bulbul:v3"
        }
        try:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "audios" in data and data["audios"]:
                        return data["audios"][0]
        except Exception as e:
            print(f"TTS Streaming Error: {e}")
        return None

    tasks = [asyncio.create_task(fetch_chunk(chunk)) for chunk in chunks]
    
    for task in tasks:
        result = await task
        if result:
            yield result

