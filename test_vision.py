import os
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_core.messages import HumanMessage
from dotenv import load_dotenv

load_dotenv(override=True)
api_key = os.getenv("NVDIA_API_KEY")

models_to_test = [
    "meta/llama-3.2-11b-vision-instruct",
    "meta/llama-3.2-90b-vision-instruct",
    "microsoft/phi-3.5-vision-instruct"
]

for m in models_to_test:
    print(f"Testing {m}...")
    try:
        llm = ChatNVIDIA(model=m, nvidia_api_key=api_key, max_tokens=20)
        msg = HumanMessage(content="Hello!")
        res = llm.invoke([msg])
        print("Success:", res.content)
    except Exception as e:
        print("Error:", e)
    print("-" * 20)
