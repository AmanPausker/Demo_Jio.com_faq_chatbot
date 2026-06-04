import asyncio
import base64
from get_audio import generate_speech

async def main():
    phrases = [
        "hmmm, let me look into that for you. Give me just a second...",
        "uhmm, I am checking the details for you right now...",
        "aahh, just a moment please, I am pulling up that information...",
        "let me quickly check that for you, it will just take a few seconds..."
    ]
    
    js_content = "export const sarvamFillers = [\n"
    
    for p in phrases:
        print(f"Generating for: {p}")
        # kwargs to return base64
        b64 = await generate_speech(p, return_base64=True)
        if b64:
            js_content += f"  \"{b64}\",\n"
        
    js_content += "];\n"
    
    with open("frontend/src/fillersData.js", "w") as f:
        f.write(js_content)

if __name__ == "__main__":
    asyncio.run(main())
