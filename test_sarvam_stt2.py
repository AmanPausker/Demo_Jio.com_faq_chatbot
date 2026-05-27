import asyncio
import os
from sarvamai import AsyncSarvamAI
from dotenv import load_dotenv

load_dotenv(override=True)
API_KEY = os.getenv("SARVAM_API_KEY")

async def test():
    client = AsyncSarvamAI(api_subscription_key=API_KEY)
    
    # create dummy wav file
    import wave
    import struct
    with wave.open("dummy.wav", 'w') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        for i in range(16000):
            value = int(32767.0 * (i / 16000.0))
            data = struct.pack('<h', value)
            wav_file.writeframesraw(data)

    with open("dummy.wav", "rb") as f:
        res = await client.speech_to_text.transcribe(
            file=f,
            model="saaras:v3",
            language_code="hi-IN",
            mode="codemix"
        )
    print(res)

asyncio.run(test())
