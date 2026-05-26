import asyncio
import os
import time
from sarvamai import AsyncSarvamAI, AudioOutput
from dotenv import load_dotenv

load_dotenv(override=True)

async def test():
    client = AsyncSarvamAI(api_subscription_key=os.getenv("SARVAM_API_KEY"))
    t0 = time.time()
    
    async with client.text_to_speech_streaming.connect(model="bulbul:v3") as ws:
        await ws.configure(target_language_code="hi-IN", speaker="shubh")
        await ws.convert("Hello, this is a short test.")
        await ws.flush()
        
        chunks = 0
        async for m in ws:
            chunks += 1
            print(f"[{time.time() - t0:.2f}s] Received chunk {chunks}. Fields: {dir(m)}")
            if hasattr(m, 'is_final'):
                print(f"is_final = {m.is_final}")
            if hasattr(m, 'data') and hasattr(m.data, 'is_final'):
                print(f"data.is_final = {m.data.is_final}")
                
    print(f"Done in {time.time() - t0:.2f}s")

if __name__ == "__main__":
    asyncio.run(test())
