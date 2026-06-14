import asyncio
import base64
from get_audio import generate_speech

async def main():
    phrases = [
        "hmmm, let me look into that for you. Give me just a second...",
        "uhmm, I am checking the details for you right now...",
        "aahh, just a moment please, I am pulling up that information...",
        "let me quickly check that for you, it will just take a few seconds...",
        "hmm, that's a good question. Let me find the exact answer for you...",
        "uhm, please bear with me for a moment while I search the details...",
        "just a second, I am looking through the Jio information for that...",
        "aah, let me double check that for you so I can give you the exact details...",
        "hmm, getting that information for you right away. Hold on...",
        "let me see... I'm pulling up the relevant details right now...",
        "uhmm, give me a brief moment to find the best answer for your query...",
        "alright, let me check the system to get the most accurate information...",
        "hmm, searching for that specific detail right now. Give me a second...",
        "uhm, just processing your request, it will take a quick moment...",
        "aahh, let me fetch those details for you immediately..."
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
