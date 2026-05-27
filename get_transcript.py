import asyncio
import sounddevice as sd
import numpy as np
import base64
from sarvamai import SarvamAI
import os
from dotenv import load_dotenv
load_dotenv(override=True)
api_key = os.getenv("SARVAM_API_KEY")
client = SarvamAI(api_subscription_key=api_key)
SAMPLE_RATE = 16000
CHANNELS = 1
BLOCKSIZE = 1600   # 100 ms chunks
async def listen_for_speech(silence_timeout: float = 2.0) -> str:
    """ 
    Creating input for microphone
    """
    audio_queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    def callback(indata, frames, time, status):
        audio_data = (indata * 32767).astype(np.int16)
        loop.call_soon_threadsafe(
            audio_queue.put_nowait,
            audio_data.tobytes()
        )
    # State tracking
    state = {
        "latest_transcript": "",
        "last_update_time": asyncio.get_event_loop().time(),
        "is_done": False
    }
    async def sender(stt_ws):
        while not state["is_done"]:
            try:
                audio_chunk = await asyncio.wait_for(audio_queue.get(), timeout=0.1)
                b64_audio = base64.b64encode(audio_chunk).decode('utf-8')
                await asyncio.to_thread(stt_ws.transcribe, audio=b64_audio)
            except asyncio.TimeoutError:
                continue
            except Exception:
                # Connection likely closed
                break
    async def receiver(stt_ws):
        while not state["is_done"]:
            try:
                response = await asyncio.to_thread(stt_ws.recv)
                
                # Check if it's a data response containing a transcript
                if getattr(response, "type", None) == "data" and response.data.transcript:
                    new_transcript = response.data.transcript.strip()
                    
                    # Only reset the silence timer if the transcript actually grew or changed
                    if new_transcript != state["latest_transcript"].strip():
                        state["latest_transcript"] = new_transcript
                        state["last_update_time"] = asyncio.get_event_loop().time()
                        
                        # Overwrite the same line in the console for a clean UX
                        print(f"\rTranscript: {state['latest_transcript']}", end="", flush=True)
            except Exception:
                # Connection closed
                break
    async def monitor():
        while not state["is_done"]:
            await asyncio.sleep(0.1)
            if state["latest_transcript"]:
                # If we have a transcript, check how long it's been since it last updated
                elapsed = asyncio.get_event_loop().time() - state["last_update_time"]
                if elapsed > silence_timeout:
                    state["is_done"] = True
                    print("\n[Silence detected. Finalizing transcript...]")
                    break
    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
        blocksize=BLOCKSIZE,
        callback=callback,
    ):
        print("\n🎤 Speak into the microphone... (Will auto-submit after a pause)\n")
        
        with client.speech_to_text_streaming.connect(
            model="saaras:v3",
            language_code="hi-IN",
            mode="codemix",
            high_vad_sensitivity=True,
        ) as stt_ws:
            
            # Start background tasks
            sender_task = asyncio.create_task(sender(stt_ws))
            receiver_task = asyncio.create_task(receiver(stt_ws))
            
            # Wait until the monitor detects silence
            await monitor()
            
    return state["latest_transcript"]
""" FOR TESTING ---- 
if __name__ == "__main__":
    async def main():
        final_text = await listen_for_speech(silence_timeout=2.0)
        print("\n=======================")
        print(f"Final Returned Text: '{final_text}'")
        print("=======================\n")
        
    asyncio.run(main())
"""