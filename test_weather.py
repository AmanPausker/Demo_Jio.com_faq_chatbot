import os
import jwt
import time
import requests
from dotenv import load_dotenv

load_dotenv(override=True)

jwt_secret = os.getenv("SUPABASE_JWT_SECRET")

# Create a test token
payload = {
    "role": "authenticated",
    "iss": "supabase",
    "iat": int(time.time()),
    "exp": int(time.time()) + 3600,
    "sub": "00000000-0000-0000-0000-000000000000"
}
token = jwt.encode(payload, jwt_secret, algorithm="HS256")

headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
data = {"message": "what is the weather in mumbai?"}

res = requests.post("http://127.0.0.1:8000/api/chat", json=data, headers=headers)
print("Status Code:", res.status_code)
print("Response:", res.text)

