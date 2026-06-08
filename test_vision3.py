import os
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_core.messages import HumanMessage
from dotenv import load_dotenv

load_dotenv(override=True)
api_key = os.getenv("NVDIA_API_KEY")

try:
    llm = ChatNVIDIA(model="google/paligemma", nvidia_api_key=api_key, max_tokens=20)
    msg = HumanMessage(content="Hello!")
    res = llm.invoke([msg])
    print("Success google/paligemma:", res.content)
except Exception as e:
    print("Error:", e)
