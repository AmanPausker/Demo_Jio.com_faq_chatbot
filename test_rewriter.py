import os
from dotenv import load_dotenv
load_dotenv(override=True)
from langchain_cerebras import ChatCerebras
from langchain_core.messages import SystemMessage, HumanMessage
import time

CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY")
client = ChatCerebras(model="llama3.1-8b", api_key=CEREBRAS_API_KEY)

rewrite_prompt = """You are a spelling and brand name corrector. 
Fix any typos and ensure brand names have proper spacing (e.g. 'jioplus' -> 'Jio Plus', 'jiofiber' -> 'Jio Fiber', 'siggy' -> 'Swiggy').
Do NOT answer the question. ONLY output the corrected question. If it's already correct, output it exactly as is."""

queries = [
    "what is jioplus",
    "tell me about siggy offers",
    "how to recharge myjio app",
    "what are the plans for jiofiber"
]

for q in queries:
    start = time.time()
    try:
        response = client.invoke([
            SystemMessage(content=rewrite_prompt),
            HumanMessage(content=q)
        ])
        print(f"Original: {q} | Rewritten: {response.content.strip().strip('\"')} | Time: {time.time() - start:.2f}s")
    except Exception as e:
        print(f"Error on '{q}': {e}")
