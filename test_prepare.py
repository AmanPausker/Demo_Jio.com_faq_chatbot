import asyncio
from server import prepare_chat, ChatRequest

async def main():
    try:
        req = ChatRequest(message="Hey", session_id="123")
        res = await prepare_chat(req, user_id="8e5e03fb-3cf0-46ee-b43e-54381920c892", token="fake_token")
        print("Success:", res)
    except Exception as e:
        import traceback
        traceback.print_exc()

asyncio.run(main())
