# backend/services/subscription_service.py

import hmac
import hashlib
import razorpay
from datetime import datetime, timedelta
from typing import Optional
from backend.config import get_settings
settings = get_settings()

_client: Optional[razorpay.Client] = None

def get_razorpay_client() -> razorpay.Client:
    global _client
    if _client is None:
        _client = razorpay.Client(
            auth=(settings.razorpay_key_id, settings.razorpay_key_secret)  # ← FIXED
        )
    return _client


PLANS = {
    "pro": {
        "name":        "PRISM Pro",
        "amount":      99900,
        "currency":    "INR",
        "description": "PRISM Pro – Monthly subscription",
    },
    "team": {
        "name":        "PRISM Team",
        "amount":      249900,
        "currency":    "INR",
        "description": "PRISM Team – Monthly subscription (5 seats)",
    },
}


def create_order(plan: str, user_id: str, supabase_client) -> dict:
    if plan not in PLANS:
        raise ValueError(f"Unknown plan: {plan}")

    plan_data = PLANS[plan]
    client    = get_razorpay_client()

    order = client.order.create({
        "amount":   plan_data["amount"],
        "currency": plan_data["currency"],
        "notes": {
            "user_id": user_id,
            "plan":    plan,
        },
    })

    supabase_client.table("subscriptions").insert({
        "user_id":           user_id,
        "razorpay_order_id": order["id"],
        "plan":              plan,
        "amount_paise":      plan_data["amount"],
        "currency":          plan_data["currency"],
        "status":            "created",
    }).execute()

    return {
        "order_id":    order["id"],
        "amount":      plan_data["amount"],
        "currency":    plan_data["currency"],
        "name":        plan_data["name"],
        "description": plan_data["description"],
        "plan":        plan,
    }


def verify_and_activate(
    razorpay_order_id:   str,
    razorpay_payment_id: str,
    razorpay_signature:  str,
    user_id:             str,
    supabase_client,
) -> bool:
    expected = hmac.new(
        settings.razorpay_key_secret.encode(),  # ← FIXED
        f"{razorpay_order_id}|{razorpay_payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, razorpay_signature):
        return False

    now     = datetime.utcnow()
    ends_at = now + timedelta(days=30)

    supabase_client.table("subscriptions").update({
        "razorpay_payment_id": razorpay_payment_id,
        "razorpay_signature":  razorpay_signature,
        "status":              "active",
        "starts_at":           now.isoformat(),
        "ends_at":             ends_at.isoformat(),
        "updated_at":          now.isoformat(),
    }).eq("razorpay_order_id", razorpay_order_id).execute()

    supabase_client.auth.admin.update_user_by_id(
        user_id,
        {"user_metadata": {"is_pro": True, "pro_until": ends_at.isoformat()}},
    )

    return True


def handle_webhook(payload: bytes, signature: str, supabase_client) -> str:
    expected = hmac.new(
        settings.razorpay_webhook_secret.encode(),  # ← FIXED
        payload,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        return "invalid_signature"

    import json
    event      = json.loads(payload)
    event_type = event.get("event")

    if event_type == "payment.captured":
        payment  = event["payload"]["payment"]["entity"]
        order_id = payment.get("order_id")
        if order_id:
            supabase_client.table("subscriptions").update({
                "status":     "active",
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("razorpay_order_id", order_id).execute()

    elif event_type in ("subscription.cancelled", "payment.failed"):
        payment  = event["payload"]["payment"]["entity"]
        order_id = payment.get("order_id")
        if order_id:
            supabase_client.table("subscriptions").update({
                "status":     "cancelled" if "cancelled" in event_type else "failed",
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("razorpay_order_id", order_id).execute()

    return "ok"


def get_user_subscription_status(user_id: str, supabase_client) -> dict:
    result = (
        supabase_client.table("subscriptions")
        .select("*")
        .eq("user_id", user_id)
        .eq("status", "active")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )

    if result.data:
        sub = result.data[0]
        return {
            "is_pro":   True,
            "plan":     sub["plan"],
            "ends_at":  sub["ends_at"],
            "order_id": sub["razorpay_order_id"],
        }

    return {"is_pro": False, "plan": None, "ends_at": None}