import os
import jwt
import time
from supabase import create_client, ClientOptions
from dotenv import load_dotenv

load_dotenv(override=True)

url = os.getenv("VITE_SUPABASE_URL")
anon_key = os.getenv("VITE_SUPABASE_ANON_KEY")
jwt_secret = os.getenv("SUPABASE_JWT_SECRET")

payload = {
    "role": "service_role",
    "iss": "supabase",
    "iat": int(time.time()),
    "exp": int(time.time()) + 3600
}

token = jwt.encode(payload, jwt_secret, algorithm="HS256")

supabase = create_client(url, anon_key, options=ClientOptions(headers={"Authorization": f"Bearer {token}"}))

res = supabase.table("user_memory").select("*").execute()
print(f"Found {len(res.data)} rows.")

for row in res.data:
    supabase.table("user_memory").update({"facts": []}).eq("user_id", row["user_id"]).execute()

print("Memory cleared using service role!")
