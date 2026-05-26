import asyncio
import base64
from sarvamai import AsyncSarvamAI, AudioOutput
import os 
from dotenv import load_dotenv

load_dotenv(override = True)
API_KEY = os.getenv("SARVAM_API_KEY")

import uuid

async def generate_speech(input_text: str, filename: str = None) -> str:
    """
    Connects to Sarvam's TTS API, converts the input_text into speech,
    saves the output to a file, and returns the file path.
    """
    if filename is None:
        filename = f"output_{uuid.uuid4().hex[:8]}.mp3"
    client = AsyncSarvamAI(api_subscription_key=API_KEY)

    async with client.text_to_speech_streaming.connect(model="bulbul:v3") as ws:
        # We can configure speaker/language here
        await ws.configure(target_language_code="hi-IN", speaker="shubh")
        
        await ws.convert(input_text)
        await ws.flush()

        with open(filename, "wb") as f:
            try:
                iterator = ws.__aiter__()
                while True:
                    # Break if no new chunks arrive for 3 seconds
                    message = await asyncio.wait_for(iterator.__anext__(), timeout=1.0)
                    if isinstance(message, AudioOutput):
                        audio_chunk = base64.b64decode(message.data.audio)
                        f.write(audio_chunk)
                        f.flush()
            except asyncio.TimeoutError:
                # End of stream reached (idle timeout)
                pass
            except StopAsyncIteration:
                pass
            except Exception as e:
                pass

    return filename
