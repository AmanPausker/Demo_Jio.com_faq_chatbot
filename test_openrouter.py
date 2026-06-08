import os
import base64
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from dotenv import load_dotenv

load_dotenv(override=True)
api_key = os.getenv("OPEN_ROUTER_API_KEY")

llm = ChatOpenAI(
    model="google/gemini-1.5-flash",
    api_key=api_key,
    base_url="https://openrouter.ai/api/v1",
    max_tokens=50
)

# Create a dummy 1x1 jpeg base64
dummy_img = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="

msg = HumanMessage(content=[
    {"type": "text", "text": "Describe this image concisely."},
    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{dummy_img}"}}
])

try:
    res = llm.invoke([msg])
    print("Success google/gemini-1.5-flash:", res.content)
except Exception as e:
    print("Error:", e)
