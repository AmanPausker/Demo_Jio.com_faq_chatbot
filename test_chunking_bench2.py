import asyncio
import time
import base64
import os
import re
from sarvamai import AsyncSarvamAI
from dotenv import load_dotenv

load_dotenv(override=True)
API_KEY = os.getenv("SARVAM_API_KEY")

async def test_size(max_len):
    client = AsyncSarvamAI(api_subscription_key=API_KEY)
    text = "With JioPlus, you can enjoy the best postpaid service experience for up to 4 new connections per user. You get more value starting at 449 rupees per month, and additional 3 add-on connections at 150 rupees per SIM. The total monthly charge for a family of 4 is just 899 rupees, making it an effective charge of 225 rupees per SIM. You can enjoy truly unlimited free 5G Data with Jio True 5G Welcome Offer, and share data with your entire family without any daily data limits. Other benefits include priority call-back service by care-specialist on single-click, 1 international roaming plan for 150 plus countries, and many more! And wait, there's even more text here to see if it completely truncates the end of the sentence or if it keeps going on forever and ever."
    
    sentences = [c.strip() for c in re.split(r'(?<=[.!?])\s+', text) if c.strip()]
    
    chunks = []
    current_chunk = ""
    for s in sentences:
        if len(current_chunk) + len(s) < max_len:
            current_chunk += s + " "
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = s + " "
    if current_chunk:
        chunks.append(current_chunk.strip())
        
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
    
    print(f"Max {max_len} chars: {len(chunks)} chunks -> {time.time() - t0:.2f} seconds")

async def main():
    await test_size(400)
    await test_size(600)

if __name__ == "__main__":
    asyncio.run(main())
