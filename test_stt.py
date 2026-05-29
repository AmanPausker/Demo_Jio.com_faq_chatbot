import asyncio
from get_transcript import transcribe_audio_file
import os

async def main():
    if not os.path.exists("profile_output.mp3"):
        print("No test file found")
        return
        
    with open("profile_output.mp3", "rb") as f:
        audio_bytes = f.read()
        
    print("Transcribing...")
    res = await transcribe_audio_file(audio_bytes)
    print(f"RESULT: '{res}'")

asyncio.run(main())
