"""
Authentication routes for PRISM.
Uses Supabase for user management.
"""

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
import os
import httpx
from typing import Optional

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

        data = response.json()

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
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Login failed: {str(e)}")


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

        data = response.json()

        if response.status_code != 200:
            error_msg = data.get("error_description") or data.get("msg") or "Registration failed"
            raise HTTPException(status_code=400, detail=error_msg)

        return {
            "success": True,
            "message": "Account created! Please check your email to verify your account."
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")


@auth_router.get("/auth/me")
async def get_me(current_user: dict = __import__('fastapi').Depends(get_current_user)):
    return current_user