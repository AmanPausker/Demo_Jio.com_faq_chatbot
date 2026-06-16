import asyncio
import base64
import os
from dotenv import load_dotenv

load_dotenv()

from get_transcript import StreamingSTTSession, SAMPLE_RATE

async def test_streaming_stt():
    print("Testing Sarvam Streaming STT...")
    try:
        stt = StreamingSTTSession()
        print("Opening session...")
        await stt.__aenter__()
        print("Session opened successfully.")
        
        # Send empty PCM frames (1 second)
        pcm_bytes = b'\x00' * (SAMPLE_RATE * 2)
        await stt.send_pcm(pcm_bytes)
        
        await asyncio.sleep(2)
        partial = await stt.drain_partials()
        print(f"Partial: {partial}")
        
        final = await stt.finalize()
        print(f"Final: {final}")
        
        await stt.__aexit__()
        print("Session closed.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_streaming_stt())
