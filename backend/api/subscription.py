from fastapi import APIRouter, Depends, HTTPException, Request, Header
from pydantic import BaseModel
from typing import Optional
from supabase import Client

from backend.api.auth import get_current_user
from backend.services.subscription_service import (
    create_order,
    verify_and_activate,
    handle_webhook,
    get_user_subscription_status,
)

router = APIRouter()


# ── Request / Response models ────────────────────────────────────────────────

class CreateOrderRequest(BaseModel):
    plan: str = "pro"

class VerifyPaymentRequest(BaseModel):
    razorpay_order_id:   str
    razorpay_payment_id: str
    razorpay_signature:  str


# ── Dependency: get Supabase client ─────────────────────────────────────────

def get_supabase() -> Client:
    from backend.config import settings
    from supabase import create_client
    return create_client(settings.supabase_url, settings.supabase_service_key)  # ← FIXED (lowercase)


# ── Routes ───────────────────────────────────────────────────────────────────

@router.post("/create-order")
async def create_subscription_order(
    body:     CreateOrderRequest,
    user:     dict = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    try:
        order = create_order(
            plan            = body.plan,
            user_id         = user["id"],
            supabase_client = supabase,
        )
        return {"success": True, "order": order}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Order creation failed: {e}")


@router.post("/verify-payment")
async def verify_payment(
    body:     VerifyPaymentRequest,
    user:     dict = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    valid = verify_and_activate(
        razorpay_order_id   = body.razorpay_order_id,
        razorpay_payment_id = body.razorpay_payment_id,
        razorpay_signature  = body.razorpay_signature,
        user_id             = user["id"],
        supabase_client     = supabase,
    )

    if not valid:
        raise HTTPException(status_code=400, detail="Payment signature invalid. Contact support.")

    return {"success": True, "message": "Subscription activated! Welcome to PRISM Pro."}


@router.get("/status")
async def subscription_status(
    user:     dict = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    status = get_user_subscription_status(user["id"], supabase)
    return {"success": True, **status}


@router.post("/webhook")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: Optional[str] = Header(None),
    supabase: Client = Depends(get_supabase),
):
    payload   = await request.body()
    signature = x_razorpay_signature or ""

    result = handle_webhook(payload, signature, supabase)

    if result == "invalid_signature":
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    return {"status": "ok"}