import time
import base64
from sarvamai import SarvamAI
import os
from dotenv import load_dotenv

load_dotenv(override=True)
API_KEY = os.getenv("SARVAM_API_KEY")

def test():
    client = SarvamAI(api_subscription_key=API_KEY)
    text = "The Jio Swiggy Recharge Offer provides a Swiggy One Lite subscription bundled with prepaid recharges. With Swiggy One Lite, you can enjoy the following benefits: 1. 10 free home deliveries on food orders above 149 rupees."
    
    t0 = time.time()
    response = client.text_to_speech.convert(
        text=text,
        target_language_code="hi-IN",
        speaker="shubh",
        model="bulbul:v3"
    )
    t1 = time.time()
    print(f"REST API took: {t1 - t0:.2f} seconds")
    
    # Write output to test
    with open("rest_out.mp3", "wb") as f:
        f.write(base64.b64decode(response.audios[0]))
        
if __name__ == "__main__":
    test()
