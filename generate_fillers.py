import asyncio
import base64
from get_audio import generate_speech

async def main():
    phrases = [
        "hmmm",
        "uhmm",
        "aahh",
        "hmmm, let me check",
        "uhmm, just a moment",
    ]
    
    js_content = "export const sarvamFillers = [\n"
    
    for p in phrases:
        print(f"Generating for: {p}")
        # kwargs to return base64
        b64 = await generate_speech(p, return_base64=True)
        js_content += f"  \"{b64}\",\n"
        
    js_content += "];\n"
    
    with open("frontend/src/fillersData.js", "w") as f:
        f.write(js_content)

if __name__ == "__main__":
    asyncio.run(main())
