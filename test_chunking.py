import asyncio
import time
import base64
import os
import re
from sarvamai import AsyncSarvamAI
from dotenv import load_dotenv

load_dotenv(override=True)
API_KEY = os.getenv("SARVAM_API_KEY")

async def test():
    client = AsyncSarvamAI(api_subscription_key=API_KEY)
    text = "With JioPlus, you can enjoy the best postpaid service experience for up to 4 new connections per user. You get more value starting at 449 rupees per month, and additional 3 add-on connections at 150 rupees per SIM. The total monthly charge for a family of 4 is just 899 rupees, making it an effective charge of 225 rupees per SIM. You can enjoy truly unlimited free 5G Data with Jio True 5G Welcome Offer, and share data with your entire family without any daily data limits. Other benefits include priority call-back service by care-specialist on single-click, 1 international roaming plan for 150 plus countries, and many more! And wait, there's even more text here to see if it completely truncates the end of the sentence or if it keeps going on forever and ever."
    
    # Split by punctuation
    chunks = [c.strip() for c in re.split(r'(?<=[.!?])\s+', text) if c.strip()]
    
    print(f"Split into {len(chunks)} chunks.")
    
    t0 = time.time()
    
    async def get_chunk(c, index):
        res = await client.text_to_speech.convert(
            text=c,
            target_language_code="hi-IN",
            speaker="shubh",
            model="bulbul:v3"
        )
        return index, base64.b64decode(res.audios[0])
        
    tasks = [get_chunk(c, i) for i, c in enumerate(chunks)]
    results = await asyncio.gather(*tasks)
    
    # Sort by index
    results.sort(key=lambda x: x[0])
    
    # Concatenate WAVs (strip 44 byte header for all but first)
    final_audio = bytearray()
    for i, (_, audio_bytes) in enumerate(results):
        if i == 0:
            final_audio.extend(audio_bytes)
        else:
            final_audio.extend(audio_bytes[44:])
            
    with open("test_chunked.wav", "wb") as f:
        f.write(final_audio)
        
    print(f"Finished in {time.time() - t0:.2f} seconds")

if __name__ == "__main__":
    asyncio.run(test())
