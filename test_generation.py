import asyncio
import time
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_ollama import ChatOllama

async def run():
    print("Initializing ChatOllama...")
    client = ChatOllama(model="cow/gemma2_tools:2b", base_url="http://localhost:11434", temperature=0.7, think=False, streaming=True, num_ctx=2048, keep_alive=-1)
    
    messages = [
        SystemMessage(content="You are a helpful and friendly AI assistant named Kia.\nIf the user says hello, greets you, or asks a general question, just answer it normally and conversationally in plain text."),
        HumanMessage(content="Hey how are you")
    ]
    
    print("Starting generation...")
    t0 = time.time()
    response = None
    
    async for chunk in client.astream(messages):
        if response is None:
            t1 = time.time()
            print(f"Time to first chunk: {t1 - t0:.2f}s")
            response = chunk
        else:
            response += chunk
            
    t2 = time.time()
    print(f"Total time: {t2 - t0:.2f}s")
    print(f"Answer: {response.content}")

if __name__ == "__main__":
    asyncio.run(run())
