import asyncio
import sounddevice as sd
import numpy as np
from sarvamai import SarvamAI
import os
from dotenv import load_dotenv
from websockets.exceptions import ConnectionClosed

load_dotenv(override=True)

api_key = os.getenv("SARVAM_API_KEY")

client = SarvamAI(api_subscription_key=api_key)

SAMPLE_RATE = 16000
CHANNELS = 1
BLOCKSIZE = 1600   # 100 ms chunks


async def mic_audio_generator(queue):
    loop = asyncio.get_running_loop()

    def callback(indata, frames, time, status):
        if status:
            print("Audio status:", status)

        # microphone volume check
        volume = np.linalg.norm(indata)

        audio_data = (indata * 32767).astype(np.int16)

        loop.call_soon_threadsafe(
            queue.put_nowait,
            audio_data.tobytes()
        )

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
        blocksize=BLOCKSIZE,
        callback=callback,
    ):
        print("\n🎤 Speak into the microphone...\n")
        await asyncio.Event().wait()


async def stream_to_sarvam():
    audio_queue = asyncio.Queue()

    asyncio.create_task(
        mic_audio_generator(audio_queue)
    )

    with client.speech_to_text_streaming.connect(
        model="saaras:v3",
        language_code="hi-IN",
        mode="codemix",
        high_vad_sensitivity=True,
    ) as stt_ws:

        print("✅ Connected to Sarvam websocket\n")

        async def sender():
            while True:
                audio_chunk = await audio_queue.get()

                import base64
                b64_audio = base64.b64encode(audio_chunk).decode('utf-8')

                try:
                    await asyncio.to_thread(stt_ws.transcribe, audio=b64_audio)


                except Exception as e:
                    print("Sender error:", e)
                    break

        async def receiver():
            while True:
                try:
                    response = await asyncio.to_thread(stt_ws.recv)

                    print("\n===================")
                    print("RAW RESPONSE:")
                    print(type(response))
                    print(response)
                    print("===================\n")

                except Exception as e:
                    print("Receiver error:", e)
                    break
        
        await asyncio.gather(
            sender(),
            receiver()
        )


if __name__ == "__main__":
    asyncio.run(stream_to_sarvam())