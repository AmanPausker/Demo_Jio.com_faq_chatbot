import asyncio
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_ollama import ChatOllama

async def main():
    client = ChatOllama(model="cow/gemma2_tools:2b", base_url="http://localhost:11434", think=False, streaming=True)
    
    # 3000 words
    long_text = "word " * 3000
    messages = [
        SystemMessage(content=long_text),
        HumanMessage(content="Say hi")
    ]
    
    response = None
    async for chunk in client.astream(messages):
        if response is None:
            response = chunk
        else:
            response += chunk
            
    print("FINAL CONTENT:", response.content if response else "NONE")

asyncio.run(main())
