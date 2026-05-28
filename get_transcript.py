import asyncio
import sounddevice as sd
import numpy as np
import base64
from sarvamai import SarvamAI
import os
from dotenv import load_dotenv
from silero_vad import load_silero_vad, VADIterator
import torch

load_dotenv(override=True)
api_key = os.getenv("SARVAM_API_KEY")
client = SarvamAI(api_subscription_key=api_key)

SAMPLE_RATE = 16000
CHANNELS = 1
BLOCKSIZE = 1600   # 100 ms chunks at 16kHz
VAD_WINDOW = 512   # 32 ms — Silero VAD expects exactly 512 samples at 16kHz

_vad_model = load_silero_vad()
print("Silero VAD model loaded.")


async def listen_for_speech(silence_timeout: float = 0.5) -> str:
    """
    Capture microphone audio with real-time Silero VAD silence detection.
    Returns the transcribed text once the user stops speaking.
    """
    audio_queue = asyncio.Queue()
    vad_event_queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def callback(indata, frames, time, status):
        audio_data = (indata * 32767).astype(np.int16)
        loop.call_soon_threadsafe(
            audio_queue.put_nowait,
            audio_data.tobytes()
        )

    state = {
        "latest_transcript": "",
        "is_done": False,
    }

    async def sender(stt_ws):
        vad_buffer = []
        vad_iterator = VADIterator(
            _vad_model,
            threshold=0.5,
            sampling_rate=SAMPLE_RATE,
            min_silence_duration_ms=int(silence_timeout * 1000),
        )
        while not state["is_done"]:
            try:
                audio_chunk = await asyncio.wait_for(audio_queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue

            # Send to Sarvam STT
            b64_audio = base64.b64encode(audio_chunk).decode("utf-8")
            await asyncio.to_thread(stt_ws.transcribe, audio=b64_audio)

            # Silero VAD — process 512-sample sliding windows
            samples = (
                np.frombuffer(audio_chunk, dtype=np.int16).astype(np.float32)
                / 32768.0
            )
            vad_buffer.extend(samples.tolist())
            while len(vad_buffer) >= VAD_WINDOW:
                window = torch.tensor(vad_buffer[:VAD_WINDOW], dtype=torch.float32)
                vad_buffer[:] = vad_buffer[VAD_WINDOW:]
                result = vad_iterator(window)
                if result:
                    vad_event_queue.put_nowait(result)

    async def receiver(stt_ws):
        while not state["is_done"]:
            try:
                response = await asyncio.to_thread(stt_ws.recv)
                if (
                    getattr(response, "type", None) == "data"
                    and response.data.transcript
                ):
                    transcript = response.data.transcript.strip()
                    if transcript != state["latest_transcript"]:
                        state["latest_transcript"] = transcript
                        print(
                            f"\rTranscript: {state['latest_transcript']}",
                            end="",
                            flush=True,
                        )
            except Exception:
                break

    async def monitor(max_duration: float = 30.0):
        speech_detected = False
        start_time = asyncio.get_event_loop().time()

        while not state["is_done"]:
            if asyncio.get_event_loop().time() - start_time > max_duration:
                print("\n[Recording timeout reached]")
                state["is_done"] = True
                break

            try:
                event = await asyncio.wait_for(vad_event_queue.get(), timeout=0.1)
                if "start" in event:
                    speech_detected = True
                    print("\r[Speech detected]", end="", flush=True)
                elif "end" in event and speech_detected:
                    state["is_done"] = True
                    print("\n[Speech ended. Finalizing transcript...]")
                    break
            except asyncio.TimeoutError:
                continue
            except Exception:
                break

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
        blocksize=BLOCKSIZE,
        callback=callback,
    ):
        print("\nSpeak into the microphone...\n")

        with client.speech_to_text_streaming.connect(
            model="saaras:v3",
            language_code="hi-IN",
            mode="codemix",
            high_vad_sensitivity=True,
        ) as stt_ws:
            sender_task = asyncio.create_task(sender(stt_ws))
            receiver_task = asyncio.create_task(receiver(stt_ws))
            await monitor()

    return state["latest_transcript"]


async def transcribe_audio_file(file_path_or_bytes) -> str:
    """Transcribe an audio file using Sarvam REST API"""
    from sarvamai import AsyncSarvamAI
    import tempfile
    import os

    async_client = AsyncSarvamAI(api_subscription_key=os.getenv("SARVAM_API_KEY"))

    temp_file_path = None
    if isinstance(file_path_or_bytes, bytes):
        fd, temp_file_path = tempfile.mkstemp(suffix=".wav")
        with os.fdopen(fd, 'wb') as f:
            f.write(file_path_or_bytes)
        file_path = temp_file_path
    else:
        file_path = file_path_or_bytes

    try:
        with open(file_path, "rb") as file_obj:
            res = await async_client.speech_to_text.transcribe(
                file=file_obj,
                model="saaras:v3",
                language_code="hi-IN",
                mode="codemix",
            )
            return res.transcript
    except Exception as e:
        print(f"STT Error: {e}")
        return ""
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)
