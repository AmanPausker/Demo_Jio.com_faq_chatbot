import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv(override=True)
url = os.getenv("VITE_SUPABASE_URL")
key = os.getenv("VITE_SUPABASE_ANON_KEY")
supabase: Client = create_client(url, key)

# Delete all memory rows (for testing purposes)
# Alternatively, fetch all and update facts to []
res = supabase.table("user_memory").select("*").execute()
for row in res.data:
    supabase.table("user_memory").update({"facts": []}).eq("user_id", row["user_id"]).execute()
print("Memory cleared successfully!")
