import os
import base64
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage
from dotenv import load_dotenv

load_dotenv(override=True)

# Create a dummy 1x1 jpeg base64
dummy_img = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="

llm = ChatGroq(model="llama-3.2-11b-vision-preview", max_tokens=100)
msg = HumanMessage(content=[
    {"type": "text", "text": "What is this?"},
    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{dummy_img}"}}
])

try:
    res = llm.invoke([msg])
    print("Success:", res.content)
except Exception as e:
    print("Error:", e)
