"""Read the signed-in account's plan and usage without exposing its profile or credentials."""
import asyncio
import math

import work_auth


def amount(value):
    if type(value) in (int, float) and math.isfinite(value) and value >= 0:
        return value
    return None


async def read():
    client = await work_auth.require_caller()
    resource = client.user()
    profile, limits = await asyncio.gather(resource.get(), resource.limits(), return_exceptions=True)
    plan = getattr(profile, "plan", None)
    allowance = amount(getattr(plan, "monthly_usage_credits_usd", None))
    hard_limit = amount(getattr(getattr(limits, "limits", None), "max_monthly_usage_usd", None))
    used = amount(getattr(getattr(limits, "current", None), "monthly_usage_usd", None))
    room = 0 if hard_limit == 0 else None
    if hard_limit is not None and used is not None:
        room = max(0, round(hard_limit - used, 6))
    end = getattr(getattr(limits, "monthly_usage_cycle", None), "end_at", None)
    if used is None:
        try:
            monthly = await resource.monthly_usage()
            used = amount(monthly.total_usage_credits_usd_after_volume_discount)
        except Exception:
            used = None  # Scoped accounts may have access to a plan but neither usage endpoint.
    monthly_left = None
    if getattr(plan, "force_billing_interval", None) != "ANNUAL" and allowance is not None and used is not None:
        monthly_left = max(0, round(allowance - used, 6))
    return {
        "usage_usd": used, "monthly_plan_allowance_usd": allowance,
        "estimated_monthly_allowance_left_usd": monthly_left,
        "hard_limit_usd": hard_limit, "room_to_limit_usd": room,
        "limit_status": "unavailable" if room is None else "available" if room > 0 else "reached",
        "cycle_ends_at": end.isoformat() if end else None,
        "billing_url": "https://console.apify.com/billing",
        "note": "The allowance estimate uses this month's plan and usage. Annual pools and promotional balances may differ. Open Apify Billing for account credit details.",
    }
