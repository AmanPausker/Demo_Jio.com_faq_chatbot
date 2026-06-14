import time
import os
import requests
import asyncio
from dotenv import load_dotenv

load_dotenv(override=True)

# 1. Sarvam Latency
def measure_sarvam(text="Hello, this is a test."):
    api_key = os.getenv("SARVAM_API_KEY")
    url = "https://api.sarvam.ai/text-to-speech"
    payload = {
        "inputs": [text],
        "target_language_code": "hi-IN",
        "speaker": "shubh",
        "model": "bulbul:v3"
    }
    headers = {"api-subscription-key": api_key, "Content-Type": "application/json"}
    
    t0 = time.time()
    res = requests.post(url, json=payload, headers=headers)
    t1 = time.time()
    
    if res.status_code == 200:
        return t1 - t0
    else:
        print("Sarvam Error:", res.text)
        return None

# 2. Qwen Latency
async def measure_qwen(text="Hello, this is a test."):
    from get_audio import generate_speech
    # Pre-load model to exclude load time from latency calculation
    import get_audio
    get_audio.get_qwen_tts_model()
    
    t0 = time.time()
    # pass language matching the qwen logic or default
    # qwen local generation
    await generate_speech(text, speaker="ryan", language="english")
    t1 = time.time()
    
    return t1 - t0

async def main():
    text = "Hello, this is a test of the text to speech latency."
    print("Testing Sarvam API Latency...")
    sarvam_lat = measure_sarvam(text)
    print(f"Sarvam Latency: {sarvam_lat:.2f} seconds")
    
    print("\nTesting Qwen3-0.6B Local Latency...")
    qwen_lat = await measure_qwen(text)
    print(f"Qwen Latency: {qwen_lat:.2f} seconds")
    
if __name__ == "__main__":
    asyncio.run(main())
