import asyncio
import base64
from sarvamai import AsyncSarvamAI, AudioOutput
import os 
from dotenv import load_dotenv

load_dotenv(override = True)

API_KEY = os.getenv("SARVAM_API_KEY")

async def tts_stream(input_text):
    client = AsyncSarvamAI(api_subscription_key=API_KEY)

    async with client.text_to_speech_streaming.connect(model="bulbul:v3") as ws:
        await ws.configure(target_language_code="hi-IN", speaker="shubh")
        print("Sent configuration")

        long_text = input_text

        await ws.convert(long_text)
        print("Sent text message")

        await ws.flush()
        print("Flushed buffer")

        chunk_count = 0
        with open("output.mp3", "wb") as f:
            async for message in ws:
                if isinstance(message, AudioOutput):
                    chunk_count += 1
                    audio_chunk = base64.b64decode(message.data.audio)
                    f.write(audio_chunk)
                    f.flush()

        print(f"All {chunk_count} chunks saved to output.mp3")
        print("Audio generation complete")


        if hasattr(ws, "_websocket") and not ws._websocket.closed:
            await ws._websocket.close()
            print("WebSocket connection closed.")


if __name__ == "__main__":
    asyncio.run(tts_stream("""JioPlus is the all-new Postpaid plan providing the best Postpaid service experience for up to 4 new connections per user. It offers several features and benefits, including:
More Value: Starting at ₹ 449 per month
Additional connections: 3 add-on connections @ ₹ 150 per SIM
Total monthly charge for a family of 4: ₹ 899
Effective monthly charge per SIM: ₹ 225
High-speed data: More Data, Share data with your entire family, No daily data limits
Truly unlimited free 5G Data with Jio True 5G Welcome Offer
Premium content and applications: Choice number, Premium Applications like Netflix, Amazon, JioTV, etc.
International roaming: In-flight connectivity while traveling abroad, India calling at ₹ 1 per minute with WiFi calling on international roaming, One international roaming plan for 150+ countries
Privileges: No Security Deposit required for Existing mobile postpaid users of other operators, Credit card users of Axis Bank, HDFC Bank, and SBI Card
Convenience: Priority call-back service by care-specialist on single-click, Move your existing number to Jio without any downtime, Missed call on 70 000-70 000 for free home delivery & activation"""))

