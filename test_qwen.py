import asyncio
import base64
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage

async def main():
    llm = ChatOllama(model="qwen-vision", base_url="http://localhost:11434", max_tokens=250, think=False)
    # create a dummy 1x1 black jpeg image in base64
    dummy_jpeg_b64 = "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAGBAQABAAAAAAf/xAAUAQEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAE/AH//xAAUAQEAAAAAAAAAAAAAAAAAAAAA/9oACAECAQE/AH//xAAUAQEAAAAAAAAAAAAAAAAAAAAA/9oACAEDAQE/AH//2Q=="
    
    # Try with data URI
    vision_content = [
        {"type": "text", "text": "What is in this image?"},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{dummy_jpeg_b64}"}}
    ]
    msg = HumanMessage(content=vision_content)
    try:
        resp = await llm.ainvoke([msg])
        print("Success with data URI:", resp.content)
    except Exception as e:
        print("Error with data URI:", repr(e))

    # Try with raw base64
    vision_content = [
        {"type": "text", "text": "What is in this image?"},
        {"type": "image_url", "image_url": {"url": f"{dummy_jpeg_b64}"}}
    ]
    msg = HumanMessage(content=vision_content)
    try:
        resp = await llm.ainvoke([msg])
        print("Success with raw base64:", resp.content)
    except Exception as e:
        print("Error with raw base64:", repr(e))

asyncio.run(main())
