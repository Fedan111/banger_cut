import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv(override=True)

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")

print(f"URL: {url}")
print(f"KEY prefix: {key[:15] if key else None}...")
print(f"KEY length: {len(key) if key else 0}")

try:
    client = create_client(url, key)
    res = client.table("user_settings").select("*").limit(1).execute()
    print("✅ Успешное подключение к Supabase!")
except Exception as e:
    print("❌ Ошибка подключения:", e)