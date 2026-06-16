import os
import requests
import json
from dotenv import load_dotenv

load_dotenv(override=True)
api_key = os.getenv("SARVAM_API_KEY")
print(f"Testing Sarvam Key: {api_key[:5]}...{api_key[-5:]}")

url = "https://api.sarvam.ai/text-to-speech"
payload = {
    "inputs": ["Hello, test."],
    "target_language_code": "hi-IN",
    "speaker": "shubh",
    "model": "bulbul:v3"
}
headers = {"api-subscription-key": api_key, "Content-Type": "application/json"}
res = requests.post(url, json=payload, headers=headers)
print("Status Code:", res.status_code)
print("Response:", res.text[:200])
