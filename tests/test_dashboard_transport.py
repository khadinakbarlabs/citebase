"""Offline regressions for the dashboard's browser-side requests."""
import subprocess
import unittest
from pathlib import Path


class DashboardTransportTests(unittest.TestCase):
    def test_dashboard_transport(self):
        suite = Path(__file__).parent / "browser" / "dashboard_transport.test.cjs"
        result = subprocess.run(["node", "--test", str(suite)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
