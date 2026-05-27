import asyncio
from get_transcript import transcribe_audio_file

async def main():
    # Make a dummy wav of 1 second of silence
    header = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x44\xac\x00\x00\x88\x58\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    audio_bytes = header + (b'\x00' * 32000)
    res = await transcribe_audio_file(audio_bytes)
    print(f"Result: '{res}'")

asyncio.run(main())
