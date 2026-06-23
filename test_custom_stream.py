import asyncio
import json
import aiohttp

async def custom_ollama_stream(msgs):
    url = "http://localhost:11434/v1/chat/completions"
    payload = {
        "model": "cow/gemma2_tools:2b",
        "stream": True,
        "messages": msgs
    }
    async with aiohttp.ClientSession() as sess:
        async with sess.post(url, json=payload) as resp:
            async for line in resp.content:
                line = line.decode('utf-8').strip()
                if line.startswith("data: ") and line != "data: [DONE]":
                    try:
                        data = json.loads(line[6:])
                        delta = data.get("choices", [{}])[0].get("delta", {})
                        yield delta.get("content", ""), delta.get("reasoning", "")
                    except Exception as e:
                        print("Parse error:", e)

async def main():
    msgs = [
        {"role": "system", "content": "You are Aman, a friendly, professional Jio customer service agent."},
        {"role": "user", "content": "How are you?"}
    ]
    full_content = ""
    full_reasoning = ""
    async for content_token, reasoning_token in custom_ollama_stream(msgs):
        if content_token:
            full_content += content_token
        if reasoning_token:
            full_reasoning += reasoning_token
            
    print(f"REASONING ({len(full_reasoning)} chars): {full_reasoning}")
    print(f"CONTENT ({len(full_content)} chars): {full_content}")

asyncio.run(main())
