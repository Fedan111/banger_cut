import os
from typing import Optional, Dict, Any
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL и SUPABASE_KEY должны быть указаны в .env")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# --- Настройки пользователей ---

def get_user_settings(user_id: int) -> Dict[str, Any]:
    """Получает настройки пользователя из Supabase. Если их нет — создает дефолтные."""
    res = supabase.table("user_settings").select("*").eq("user_id", user_id).execute()
    
    if res.data:
        return res.data[0]
    
    default_settings = {
        "user_id": user_id,
        "preset": "milo",
        "v_offset": 0.8,
        "h_align": "center",
        "font_size": "4.8cqh"
    }
    supabase.table("user_settings").insert(default_settings).execute()
    return default_settings


def update_user_settings(user_id: int, settings: Dict[str, Any]) -> Dict[str, Any]:
    """Обновляет настройки пользователя."""
    payload = {"user_id": user_id, **settings}
    res = supabase.table("user_settings").upsert(payload).execute()
    return res.data[0] if res.data else {}


# --- Сессии редактирования ---

def create_session(
    chat_id: int,
    input_path: str,
    session_dir: str,
    transcript: list,
    keep_segments: list
) -> str:
    """Создает новую сессию редактирования в Supabase и возвращает ее UUID."""
    payload = {
        "chat_id": chat_id,
        "input_path": input_path,
        "session_dir": session_dir,
        "transcript": transcript,
        "keep_segments": keep_segments,
        "status": "pending"
    }
    res = supabase.table("sessions").insert(payload).execute()
    return res.data[0]["id"]


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Возвращает сессию по ее ID."""
    res = supabase.table("sessions").select("*").eq("id", session_id).execute()
    return res.data[0] if res.data else None


def update_session_transcript(session_id: str, transcript: list):
    """Обновляет отредактированный транскрипт сессии."""
    supabase.table("sessions").update({"transcript": transcript}).eq("id", session_id).execute()


def update_session_status(session_id: str, status: str):
    """Обновляет статус сессии (pending, rendering, done)."""
    supabase.table("sessions").update({"status": status}).eq("id", session_id).execute()