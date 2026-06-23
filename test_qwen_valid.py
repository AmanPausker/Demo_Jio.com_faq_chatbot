import asyncio
import base64
import json
import aiohttp
from PIL import Image
import io

async def test_api():
    # Create valid 10x10 red jpeg
    img = Image.new('RGB', (10, 10), color = 'red')
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='JPEG')
    valid_b64 = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')

    url = "http://localhost:11434/api/chat"
    payload = {
        "model": "qwen-vision",
        "messages": [
            {
                "role": "user",
                "content": "What color is this image?",
                "images": [valid_b64]
            }
        ],
        "stream": False
    }

    async with aiohttp.ClientSession() as sess:
        async with sess.post(url, json=payload) as resp:
            text = await resp.text()
            print("Status:", resp.status)
            print("Response:", text)

asyncio.run(test_api())
