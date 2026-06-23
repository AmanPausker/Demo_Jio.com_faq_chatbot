import asyncio
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage

async def main():
    llm = ChatOllama(model="cow/gemma2_tools:2b", base_url="http://localhost:11434", streaming=True, think=False)
    try:
        async for chunk in llm.astream([HumanMessage(content="Hello")]):
            print(f"CHUNK: {repr(chunk.content)}")
    except Exception as e:
        print(f"ERROR: {e}")

asyncio.run(main())
