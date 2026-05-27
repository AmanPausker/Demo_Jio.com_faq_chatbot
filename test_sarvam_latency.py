import asyncio
import time
import base64
from get_audio import generate_speech

async def test():
    t0 = time.time()
    text = """The Jio Swiggy Recharge Offer provides a Swiggy One Lite subscription bundled with prepaid recharges. With Swiggy One Lite, you can enjoy the following benefits:

1. 10 free home deliveries on food orders above ₹149
2. 10 free home deliveries on Instamart orders above ₹199
3. No surge fees on food delivery and Instamart orders
4. Up to 30% extra discounts on 20K+ food delivery restaurants above regular offers
5. 10% discount on Genie deliveries above ₹60

The Swiggy One Lite subscription is valid for 3 months and is provided in a quarterly subscription.

You can avail this offer through all modes of recharge, and once you recharge with the plan, you can activate the Swiggy One Lite subscription by following a few simple steps:

- Visit the MyJio coupon section
- Copy the Swiggy One Lite subscription coupon code
- Login to the Swiggy app with your existing account or create a new one
- Enter the coupon code to activate your Swiggy One subscription"""
    print("Sending text to Sarvam...")
    async for _ in generate_speech(text):
        pass
    print(f"Total time: {time.time()-t0:.2f} seconds")

asyncio.run(test())
