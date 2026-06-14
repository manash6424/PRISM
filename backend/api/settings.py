# backend/api/settings.py
# Drop this file in your backend/api/ folder
# Then in backend/main.py add:
#   from backend.api.settings import router as settings_router
#   app.include_router(settings_router)

from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel, EmailStr
from typing import Optional
import os
from supabase import create_client, Client
from cryptography.fernet import Fernet
import base64
import hashlib

router = APIRouter(prefix="/api/settings", tags=["settings"])

# ── Supabase client ──────────────────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")  # service role key (not anon)

def get_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# ── Encryption for API keys (reuses your existing ENCRYPTION_KEY) ────────────
def get_fernet() -> Fernet:
    raw_key = os.getenv("ENCRYPTION_KEY", "PrismSecretKey2024XYZ1234567890")
    # Derive a 32-byte key from whatever string is in .env
    key_bytes = hashlib.sha256(raw_key.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)

def encrypt_key(value: str) -> str:
    return get_fernet().encrypt(value.encode()).decode()

def decrypt_key(encrypted: str) -> str:
    return get_fernet().decrypt(encrypted.encode()).decode()

# ── Auth: get user_id from JWT ────────────────────────────────────────────────
def get_current_user(authorization: str = Header(...)) -> str:
    """Extract user_id from Supabase JWT passed as Bearer token."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Bearer token")
    token = authorization.split(" ", 1)[1]
    supabase = get_supabase()
    try:
        user = supabase.auth.get_user(token)
        return user.user.id
    except Exception:
        raise HTTPException(401, "Invalid or expired token")

# ── Models ────────────────────────────────────────────────────────────────────
class ProfileUpdate(BaseModel):
    full_name: str
    company_name: str
    role_title: str

class AppearanceUpdate(BaseModel):
    theme: str
    font_size: str
    density: str

class NotificationsUpdate(BaseModel):
    notif_query_alerts: bool
    notif_weekly_summary: bool
    notif_billing_alerts: bool
    notif_product_updates: bool
    notif_query_success: bool
    notif_connection_status: bool

class PreferencesUpdate(BaseModel):
    pref_row_limit: int
    pref_show_sql: bool
    pref_show_explanation: bool
    pref_export_format: str
    pref_filename_prefix: str

class PasswordChange(BaseModel):
    current_password: str
    new_password: str

class APIKeyUpsert(BaseModel):
    service: str   # 'openai', 'sendgrid', 'slack'
    key_value: str

# ── Helper: upsert settings row ───────────────────────────────────────────────
def upsert_settings(user_id: str, data: dict):
    supabase = get_supabase()
    existing = supabase.table("user_settings").select("id").eq("user_id", user_id).execute()
    if existing.data:
        supabase.table("user_settings").update(data).eq("user_id", user_id).execute()
    else:
        supabase.table("user_settings").insert({"user_id": user_id, **data}).execute()

# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("")
def get_all_settings(user_id: str = Depends(get_current_user)):
    """Load all settings for the current user."""
    supabase = get_supabase()
    
    # Settings
    settings_res = supabase.table("user_settings").select("*").eq("user_id", user_id).execute()
    settings = settings_res.data[0] if settings_res.data else {}

    # API keys (return service names + preview only, never the real key)
    keys_res = supabase.table("user_api_keys").select("service, key_preview, created_at").eq("user_id", user_id).execute()
    api_keys = {row["service"]: row["key_preview"] for row in (keys_res.data or [])}

    # Email from Supabase auth
    user_res = get_supabase().auth.admin.get_user_by_id(user_id)
    email = user_res.user.email if user_res and user_res.user else ""

    return {
        "email": email,
        "settings": settings,
        "api_keys": api_keys   # e.g. {"openai": "3a8f", "sendgrid": null}
    }


@router.put("/profile")
def update_profile(body: ProfileUpdate, user_id: str = Depends(get_current_user)):
    upsert_settings(user_id, body.dict())
    return {"ok": True}


@router.put("/appearance")
def update_appearance(body: AppearanceUpdate, user_id: str = Depends(get_current_user)):
    upsert_settings(user_id, body.dict())
    return {"ok": True}


@router.put("/notifications")
def update_notifications(body: NotificationsUpdate, user_id: str = Depends(get_current_user)):
    upsert_settings(user_id, body.dict())
    return {"ok": True}


@router.put("/preferences")
def update_preferences(body: PreferencesUpdate, user_id: str = Depends(get_current_user)):
    upsert_settings(user_id, body.dict())
    return {"ok": True}


@router.post("/password")
def change_password(body: PasswordChange, user_id: str = Depends(get_current_user)):
    """Change password via Supabase Admin API."""
    if len(body.new_password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    supabase = get_supabase()
    try:
        supabase.auth.admin.update_user_by_id(user_id, {"password": body.new_password})
        return {"ok": True}
    except Exception as e:
        raise HTTPException(400, str(e))


@router.put("/api-keys")
def upsert_api_key(body: APIKeyUpsert, user_id: str = Depends(get_current_user)):
    """Save or update an API key (encrypted)."""
    if not body.key_value.strip():
        raise HTTPException(400, "Key value cannot be empty")
    
    encrypted = encrypt_key(body.key_value.strip())
    preview = body.key_value.strip()[-4:]  # last 4 chars for display

    supabase = get_supabase()
    existing = supabase.table("user_api_keys").select("id").eq("user_id", user_id).eq("service", body.service).execute()
    
    if existing.data:
        supabase.table("user_api_keys").update({
            "key_encrypted": encrypted,
            "key_preview": preview
        }).eq("user_id", user_id).eq("service", body.service).execute()
    else:
        supabase.table("user_api_keys").insert({
            "user_id": user_id,
            "service": body.service,
            "key_encrypted": encrypted,
            "key_preview": preview
        }).execute()
    
    return {"ok": True, "preview": preview}


@router.delete("/api-keys/{service}")
def delete_api_key(service: str, user_id: str = Depends(get_current_user)):
    supabase = get_supabase()
    supabase.table("user_api_keys").delete().eq("user_id", user_id).eq("service", service).execute()
    return {"ok": True}


@router.get("/api-keys/{service}/reveal")
def reveal_api_key(service: str, user_id: str = Depends(get_current_user)):
    """Return the decrypted key — only called when user clicks 'Show'."""
    supabase = get_supabase()
    res = supabase.table("user_api_keys").select("key_encrypted").eq("user_id", user_id).eq("service", service).execute()
    if not res.data:
        raise HTTPException(404, "Key not found")
    decrypted = decrypt_key(res.data[0]["key_encrypted"])
    return {"key": decrypted}


@router.delete("/account")
def delete_account(user_id: str = Depends(get_current_user)):
    """Permanently delete the user account and all data."""
    supabase = get_supabase()
    # Cascade deletes handle user_settings and user_api_keys
    # Also delete user_connections (your existing table)
    supabase.table("user_connections").delete().eq("user_id", user_id).execute()
    supabase.auth.admin.delete_user(user_id)
    return {"ok": True}