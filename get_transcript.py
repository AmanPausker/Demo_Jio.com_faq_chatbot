import asyncio
import sounddevice as sd
import numpy as np 
"""1. Audio array manipulation, 2. converting float audio ->int16 PCM, 3. processing VAD samples"""
import base64 # sarvam websocket expects audio encoded as Base64 String
from sarvamai import SarvamAI
import os
import threading
import queue as thread_queue
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


class StreamingSTTSession:
    """
    Wraps Sarvam's synchronous streaming STT WebSocket in a background thread
    so it can be driven from an asyncio event loop without blocking.

    Usage:
        async with StreamingSTTSession() as stt:
            await stt.send_pcm(pcm_bytes)          # feed raw int16 PCM
            partial = await stt.get_partial()      # latest partial transcript (non-blocking)
            final   = await stt.finalize()         # flush and get final transcript
    """

    def __init__(self):
        self._stt_ws = None
        self._context_mgr = None
        self._send_q: thread_queue.Queue = thread_queue.Queue()   # PCM bytes → sender thread
        self._partial_q: asyncio.Queue = None                     # partials → async consumer
        self._latest_partial: str = ""
        self._final_transcript: str = ""
        self._done_event = threading.Event()
        self._loop = None
        self._sender_thread: threading.Thread = None
        self._receiver_thread: threading.Thread = None

    async def __aenter__(self):
        self._loop = asyncio.get_event_loop()
        self._partial_q = asyncio.Queue()

        # Open Sarvam streaming connection in a thread (synchronous context manager)
        ready = threading.Event()
        error_box = [None]

        def _open():
            try:
                self._context_mgr = client.speech_to_text_streaming.connect(
                    model="saaras:v3",
                    language_code="en-IN",
                    mode="codemix",
                    high_vad_sensitivity=True,
                )
                self._stt_ws = self._context_mgr.__enter__()
                ready.set()
                # Start sender + receiver loops
                self._run_sender()
            except Exception as e:
                error_box[0] = e
                ready.set()

        open_thread = threading.Thread(target=_open, daemon=True)
        open_thread.start()
        await asyncio.get_event_loop().run_in_executor(None, ready.wait)
        if error_box[0]:
            raise error_box[0]

        # Receiver runs in its own thread
        self._receiver_thread = threading.Thread(target=self._run_receiver, daemon=True)
        self._receiver_thread.start()
        return self

    async def __aexit__(self, *_):
        await self.finalize()
        self._done_event.set()
        # Signal sender to stop
        self._send_q.put(None)
        # Close the Sarvam context in a thread
        if self._context_mgr and self._stt_ws:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self._context_mgr.__exit__(None, None, None)
                )
            except Exception:
                pass

    def _run_sender(self):
        """Pulls PCM bytes from _send_q and forwards to Sarvam STT WS."""
        while not self._done_event.is_set():
            try:
                item = self._send_q.get(timeout=0.05)
                if item is None:
                    break
                b64 = base64.b64encode(item).decode("utf-8")
                self._stt_ws.transcribe(audio=b64)
            except thread_queue.Empty:
                continue
            except Exception as e:
                print(f"[StreamingSTT] Sender error: {e}")
                break

    def _run_receiver(self):
        """Reads partial transcripts from Sarvam STT WS and pushes to asyncio queue."""
        while not self._done_event.is_set():
            try:
                response = self._stt_ws.recv()
                if (
                    getattr(response, "type", None) == "data"
                    and response.data.transcript
                ):
                    text = response.data.transcript.strip()
                    if text and text != self._latest_partial:
                        self._latest_partial = text
                        self._final_transcript = text
                        # Thread-safe push to asyncio queue
                        self._loop.call_soon_threadsafe(
                            self._partial_q.put_nowait, text
                        )
            except Exception:
                break

    async def send_pcm(self, pcm_bytes: bytes):
        """Feed raw int16 PCM bytes to the STT stream (non-blocking)."""
        self._send_q.put(pcm_bytes)

    async def get_partial(self) -> str | None:
        """Return the latest partial transcript if available, else None."""
        try:
            return self._partial_q.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def drain_partials(self):
        """Drain all pending partials and return the last one."""
        last = None
        while True:
            try:
                last = self._partial_q.get_nowait()
            except asyncio.QueueEmpty:
                break
        return last or self._latest_partial

    async def finalize(self) -> str:
        """
        Signal end-of-speech to Sarvam, wait briefly for the final transcript,
        then return it.
        """
        # Give the receiver a moment to flush remaining responses
        await asyncio.sleep(0.15)
        await self.drain_partials()
        return self._final_transcript or self._latest_partial


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
            threshold=0.8,
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


async def transcribe_pcm(pcm_bytes: bytes, sample_rate: int = SAMPLE_RATE) -> str:
    """Transcribe raw PCM int16 audio directly, no temp files or ffmpeg needed.
    
    Wraps PCM data with a WAV header in-memory and sends to Sarvam REST API.
    """
    from sarvamai import AsyncSarvamAI
    import io
    import wave
    import os

    async_client = AsyncSarvamAI(api_subscription_key=os.getenv("SARVAM_API_KEY"))

    wav_io = io.BytesIO()
    with wave.open(wav_io, 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_bytes)

    wav_io.seek(0)
    try:
        res = await async_client.speech_to_text.transcribe(
            file=wav_io,
            model="saaras:v3",
            language_code="en-IN",
            mode="codemix",
        )
        return res.transcript
    except Exception as e:
        print(f"STT Error (pcm): {e}")
        return ""
