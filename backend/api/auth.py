"""
Authentication routes for PRISM.
Uses Supabase for user management.
"""

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
import os
import logging
import httpx
from typing import Optional

logger = logging.getLogger(__name__)

auth_router = APIRouter()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")


# ── Request Models ────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    name: str
    company: str = ""
    email: str
    password: str


# ── Helpers (NEW) ─────────────────────────────────────────────────────────────

def _safe_json(response: httpx.Response, context: str) -> dict:
    """
    Parse a Supabase response as JSON, without crashing if Supabase returns
    something else (HTML gateway/error page, empty body, plain text) — which
    happens when the Supabase project itself is degraded/overloaded (e.g.
    Disk IO budget exhausted) rather than a normal auth error.

    On parse failure, logs the raw response for debugging and raises a clear
    502 (upstream problem) instead of letting a raw JSONDecodeError bubble up
    into an opaque 500.
    """
    try:
        return response.json()
    except ValueError:
        body_preview = (response.text or "")[:300]
        logger.error(
            f"[PRISM Auth] Supabase returned non-JSON during {context} "
            f"(status={response.status_code}): {body_preview!r}"
        )
        raise HTTPException(
            status_code=502,
            detail=(
                "Supabase is currently unavailable or degraded, so we couldn't "
                "complete the request. This is usually temporary — please try "
                "again in a minute. If it persists, check your Supabase "
                "project's status/Disk IO dashboard."
            ),
        )


# ── Auth Dependency ───────────────────────────────────────────────────────────

async def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    """Extract and verify user from Bearer token."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = authorization.replace("Bearer ", "")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{SUPABASE_URL}/auth/v1/user",
                headers={
                    "apikey": SUPABASE_ANON_KEY,
                    "Authorization": f"Bearer {token}"
                },
                timeout=10.0
            )

        if response.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        user = response.json()
        return {
            "id": user.get("id"),
            "email": user.get("email"),
            "name": user.get("user_metadata", {}).get("full_name", ""),
            "token": token,  # ✅ include token so routes can pass it to db_manager
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail="Authentication failed")


# ── Auth Endpoints ────────────────────────────────────────────────────────────

@auth_router.post("/auth/login")
async def login(request: LoginRequest):
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise HTTPException(status_code=500, detail="Supabase not configured")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
                headers={
                    "apikey": SUPABASE_ANON_KEY,
                    "Content-Type": "application/json"
                },
                json={"email": request.email, "password": request.password},
                timeout=10.0
            )

        data = _safe_json(response, "login")  # NEW: was response.json()

        if response.status_code != 200:
            error_msg = data.get("error_description") or data.get("msg") or "Invalid email or password"
            raise HTTPException(status_code=401, detail=error_msg)

        user = data.get("user", {})
        return {
            "success": True,
            "access_token": data.get("access_token"),
            "user": {
                "id": user.get("id"),
                "email": user.get("email"),
                "name": user.get("user_metadata", {}).get("full_name", ""),
            }
        }

    except HTTPException:
        raise
    except httpx.TimeoutException:
        # NEW: Supabase not responding in time (common during degradation)
        logger.error("[PRISM Auth] Login request to Supabase timed out")
        raise HTTPException(
            status_code=504,
            detail="Supabase didn't respond in time. It may be degraded right now — please try again shortly."
        )
    except Exception as e:
        logger.error(f"[PRISM Auth] Login failed with unexpected error: {e}")
        raise HTTPException(status_code=500, detail=f"Login failed: {str(e) or type(e).__name__}")


@auth_router.post("/auth/register")
async def register(request: RegisterRequest):
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise HTTPException(status_code=500, detail="Supabase not configured")

    if len(request.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{SUPABASE_URL}/auth/v1/signup",
                headers={
                    "apikey": SUPABASE_ANON_KEY,
                    "Content-Type": "application/json"
                },
                json={
                    "email": request.email,
                    "password": request.password,
                    "data": {
                        "full_name": request.name,
                        "company": request.company
                    }
                },
                timeout=10.0
            )

        data = _safe_json(response, "register")  # NEW: was response.json()

        if response.status_code != 200:
            error_msg = data.get("error_description") or data.get("msg") or "Registration failed"
            raise HTTPException(status_code=400, detail=error_msg)

        return {
            "success": True,
            "message": "Account created! Please check your email to verify your account."
        }

    except HTTPException:
        raise
    except httpx.TimeoutException:
        # NEW
        logger.error("[PRISM Auth] Register request to Supabase timed out")
        raise HTTPException(
            status_code=504,
            detail="Supabase didn't respond in time. It may be degraded right now — please try again shortly."
        )
    except Exception as e:
        logger.error(f"[PRISM Auth] Registration failed with unexpected error: {e}")
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e) or type(e).__name__}")


@auth_router.get("/auth/me")
async def get_me(current_user: dict = __import__('fastapi').Depends(get_current_user)):
    return current_user