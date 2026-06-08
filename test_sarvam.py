import os
import requests
from dotenv import load_dotenv

load_dotenv(override=True)

api_key = os.getenv("SARVAM_API_KEY")
url = "https://api.sarvam.ai/text-to-speech"
payload = {
    "inputs": ["I can see a TV mounted on the wall behind you."],
    "target_language_code": "en-IN",
    "speaker": "meera",
    "model": "bulbul:v3"
}
headers = {"api-subscription-key": api_key, "Content-Type": "application/json"}
res = requests.post(url, json=payload, headers=headers)
print("Status:", res.status_code)
if res.status_code != 200:
    print("Response:", res.text)
else:
    print("Success! Got audio.")
