import asyncio
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_ollama import ChatOllama

async def main():
    client = ChatOllama(model="cow/gemma2_tools:2b", base_url="http://localhost:11434", think=False, streaming=True)
    
    messages = [
        SystemMessage(content="You are a helpful assistant."),
        HumanMessage(content="Tell me about JioPlus"),
        AIMessage(content="JioPlus is a great postpaid plan."),
        HumanMessage(content="What is JioPlus")
    ]
    
    response = None
    async for chunk in client.astream(messages):
        print("CHUNK:", chunk.content)
        if response is None:
            response = chunk
        else:
            response += chunk
            
    print("FINAL CONTENT:", response.content)

asyncio.run(main())
