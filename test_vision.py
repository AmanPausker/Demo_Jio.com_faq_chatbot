import asyncio
import os
import traceback
from dotenv import load_dotenv
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_core.messages import HumanMessage
import base64

load_dotenv(override=True)
client = ChatNVIDIA(
    model="meta/llama-3.2-11b-vision-instruct",
    nvidia_api_key=os.getenv("NVDIA_API_KEY"),
    max_tokens=100
)

# create a 1x1 black pixel base64 image
b64_image = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="

msg = HumanMessage(content=[
    {"type": "text", "text": "What color is this image?"},
    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_image}"}}
])

async def run():
    try:
        resp = await client.ainvoke([msg])
        print("Response:", resp.content)
    except Exception as e:
        print("Error:")
        traceback.print_exc()

asyncio.run(run())
