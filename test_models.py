import time
from sarvamai import SarvamAI
import os
from dotenv import load_dotenv

load_dotenv(override=True)
API_KEY = os.getenv("SARVAM_API_KEY")

def test():
    client = SarvamAI(api_subscription_key=API_KEY)
    text = "The Jio Swiggy Recharge Offer provides a Swiggy One Lite subscription bundled with prepaid recharges. With Swiggy One Lite, you can enjoy the following benefits: 1. 10 free home deliveries on food orders above 149 rupees."
    
    # Test v3
    t0 = time.time()
    client.text_to_speech.convert(text=text, target_language_code="hi-IN", speaker="shubh", model="bulbul:v3")
    print(f"bulbul:v3 took: {time.time() - t0:.2f} seconds")
    
    # Test v2
    t0 = time.time()
    client.text_to_speech.convert(text=text, target_language_code="hi-IN", speaker="anushka", model="bulbul:v2")
    print(f"bulbul:v2 took: {time.time() - t0:.2f} seconds")

if __name__ == "__main__":
    test()
