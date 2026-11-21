import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as Ns
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "connector"))


class AccountUsageTests(unittest.IsolatedAsyncioTestCase):
    async def read(self, used, limit, allowance, unavailable=False, interval=None):
        import runner
        user = Ns(plan=Ns(monthly_usage_credits_usd=allowance, force_billing_interval=interval), email="private", proxy="private")
        limits = Ns(current=Ns(monthly_usage_usd=used), limits=Ns(max_monthly_usage_usd=limit),
                    monthly_usage_cycle=Ns(end_at=None))
        resource = Ns(get=AsyncMock(return_value=user), limits=AsyncMock(return_value=limits),
                      monthly_usage=AsyncMock(return_value=Ns(total_usage_credits_usd_after_volume_discount=used)))
        if unavailable:
            resource.limits.side_effect = PermissionError()
        with patch("work_auth.require_caller", AsyncMock(return_value=Ns(user=lambda: resource))):
            return await runner.run_tool("get_account_usage", {})

    async def test_hard_cap_and_included_allowance_have_independent_meanings(self):
        result = await self.read(12.5, 30, 10)
        self.assertEqual(result["estimated_monthly_allowance_left_usd"], 0)
        self.assertEqual(result["room_to_limit_usd"], 17.5)
        self.assertEqual(result["limit_status"], "available")
        self.assertNotIn("private", str(result))
        self.assertEqual((await self.read(0, 0, 0))["limit_status"], "reached")

    async def test_limited_account_does_not_report_an_exhausted_balance(self):
        result = await self.read(4, 5, 10, unavailable=True)
        self.assertEqual(result["limit_status"], "unavailable")
        self.assertIsNone(result["room_to_limit_usd"])
        self.assertEqual(result["usage_usd"], 4)

    async def test_pooled_annual_plan_does_not_declare_its_credits_exhausted(self):
        result = await self.read(110, 500, 100, interval="ANNUAL")
        self.assertIsNone(result["estimated_monthly_allowance_left_usd"])
        self.assertEqual(result["room_to_limit_usd"], 390)

    async def test_known_zero_limit_remains_binding_with_unavailable_usage(self):
        result = await self.read(None, 0, 50)
        self.assertEqual(result["room_to_limit_usd"], 0)
        self.assertEqual(result["limit_status"], "reached")
        self.assertEqual(result["billing_url"], "https://console.apify.com/billing")
