import json, asyncio, aiohttp

async def fetch_qwen():
    url = "http://localhost:11434/v1/chat/completions"
    payload = {
        "model": "cow/gemma2_tools:2b",
        "stream": True,
        "messages": [
            {"role": "system", "content": "You are Aman, a friendly, professional Jio customer service agent. The user is talking to you through a voice call. Keep responses conversational, brief, and to the point. Do NOT use markdown, emojis, or lists."},
            {"role": "user", "content": "How are you?"}
        ]
    }
    r_buf = ""
    c_buf = ""
    async with aiohttp.ClientSession() as sess:
        async with sess.post(url, json=payload) as resp:
            async for line in resp.content:
                line = line.decode('utf-8').strip()
                if line.startswith("data: ") and line != "data: [DONE]":
                    data = json.loads(line[6:])
                    delta = data.get("choices", [{}])[0].get("delta", {})
                    r = delta.get("reasoning", "")
                    c = delta.get("content", "")
                    if r: r_buf += r
                    if c: c_buf += c
    print("REASONING:", r_buf)
    print("CONTENT:", c_buf)

asyncio.run(fetch_qwen())
