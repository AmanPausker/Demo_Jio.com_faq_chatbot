import asyncio
import sounddevice as sd
import numpy as np 
"""1. Audio array manipulation, 2. converting float audio ->int16 PCM, 3. processing VAD samples"""
import base64 # sarvam websocket expects audio encoded as Base64 String
from sarvamai import SarvamAI
import os
from dotenv import load_dotenv
from silero_vad import load_silero_vad, VADIterator
import torch # silero model runs on pyTorch tensors.

load_dotenv(override=True)
api_key = os.getenv("SARVAM_API_KEY")
client = SarvamAI(api_subscription_key=api_key)

SAMPLE_RATE = 16000 #16000 samples per second.
CHANNELS = 1 # mono audio - 1 microphone channel
BLOCKSIZE = 1600   # 100 ms chunks at 16kHz
VAD_WINDOW = 512   # 32 ms — Silero VAD expects exactly 512 samples at 16kHz
# therefore audio chunks are further divided into 32ms windows for VAD.
_vad_model = load_silero_vad()
print("Silero VAD model loaded.")

#Allows multiple tasks to run concurrently
async def listen_for_speech(silence_timeout: float = 0.5) -> str: # returns final transcript string.
    """
    Capture microphone audio with real-time Silero VAD silence detection.
    Returns the transcribed text once the user stops speaking.
    """
    #Queues
    audio_queue = asyncio.Queue() # Stores microphone audio chunks.
    vad_event_queue = asyncio.Queue() #Stores speech events. start/end
    loop = asyncio.get_running_loop()

    #This function is automatically called by sounddevice every 100ms
    def callback(indata, frames, time, status):
        audio_data = (indata * 32767).astype(np.int16) #Converts float audio -> int16 PCM
        #push audio into queue
        loop.call_soon_threadsafe(
            audio_queue.put_nowait,
            audio_data.tobytes()
        )
    #Shared state dictionary.
    state = {
        "latest_transcript": "", #Stores most recent transcript
        "is_done": False, # Controls stopping condition
    }

    """
    1. Reads audio from queue
    2. Sends audio to Sarvam
    3. Runs VAD on audio
    """
    async def sender(stt_ws): #stt_ws = sarvam websocked connection object.
        vad_buffer = []
        # This continously tracks - speech start, speech end
        vad_iterator = VADIterator(
            _vad_model,
            threshold=0.5,
            sampling_rate=SAMPLE_RATE,
            min_silence_duration_ms=int(silence_timeout * 1000),
        )

        #Wait for Audio chunk -  gets microphone audio from queue
        while not state["is_done"]:
            try:
                audio_chunk = await asyncio.wait_for(audio_queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue

            # Send to Sarvam STT
            b64_audio = base64.b64encode(audio_chunk).decode("utf-8") #Sarvam expects base 64 string
            #Streams audio chunks
            await asyncio.to_thread(stt_ws.transcribe, audio=b64_audio)

            # Silero VAD — process 512-sample sliding windows
            #Prepares audio for VAD - converts floats back to float32, range [-1,1]
            samples = (
                np.frombuffer(audio_chunk, dtype=np.int16).astype(np.float32)
                / 32768.0
            )
            vad_buffer.extend(samples.tolist())
            while len(vad_buffer) >= VAD_WINDOW:
                window = torch.tensor(vad_buffer[:VAD_WINDOW], dtype=torch.float32) #Silero exepcts pytorch tensor input.
                vad_buffer[:] = vad_buffer[VAD_WINDOW:]
                result = vad_iterator(window)
                if result:
                    vad_event_queue.put_nowait(result) # Push VAD Event - used later by monitor()

    async def receiver(stt_ws): #Receives streaming transcripts from Sarvam.
        while not state["is_done"]:
            try:
                response = await asyncio.to_thread(stt_ws.recv)
                #Checks valid transcript
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
    #Input stream + callback callback = pushes mic audio into audio_queue.
    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
        blocksize=BLOCKSIZE,
        callback=callback,
    ):
        print("\nSpeak into the microphone...\n")
        #Creates websocket connection to Sarvam API
        with client.speech_to_text_streaming.connect(
            model="saaras:v3",
            language_code="en-IN",
            mode="codemix",
            high_vad_sensitivity=True,
        ) as stt_ws: # Created the object of sarvam websocket.
            sender_task = asyncio.create_task(sender(stt_ws))
            receiver_task = asyncio.create_task(receiver(stt_ws))
            await monitor()

    return state["latest_transcript"]


async def transcribe_audio_file(file_path_or_bytes) -> str:
    """Transcribe an audio file using Sarvam REST API"""
    from sarvamai import AsyncSarvamAI
    import tempfile
    import os
    import subprocess

    async_client = AsyncSarvamAI(api_subscription_key=os.getenv("SARVAM_API_KEY"))

    temp_file_path = None
    if isinstance(file_path_or_bytes, bytes):
        fd_in, temp_in_path = tempfile.mkstemp(suffix=".tmp")
        fd_out, temp_out_path = tempfile.mkstemp(suffix=".wav")
        
        with os.fdopen(fd_in, 'wb') as f:
            f.write(file_path_or_bytes)
            
        try:
            subprocess.run(["ffmpeg", "-y", "-i", temp_in_path, "-ar", "16000", "-ac", "1", temp_out_path], check=True, capture_output=True)
            temp_file_path = temp_out_path
        except subprocess.CalledProcessError as e:
            print(f"FFmpeg error: {e.stderr}")
            temp_file_path = temp_in_path
        finally:
            if os.path.exists(temp_in_path):
                os.remove(temp_in_path)
                
        file_path = temp_file_path
    else:
        file_path = file_path_or_bytes

    try:
        with open(file_path, "rb") as file_obj:
            res = await async_client.speech_to_text.transcribe(
                file=file_obj,
                model="saaras:v3",
                language_code="en-IN",
                mode="codemix",
            )
            return res.transcript
    except Exception as e:
        print(f"STT Error: {e}")
        return ""
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)
