"""CI must fail, not silently skip, when the connector dependencies are missing.

Set CITEBASE_REQUIRE_CONNECTOR_DEPS=1 (the workflow does for every Python that installs them). Without it the
connector tests that need mcp, pydantic, uvicorn or httpx skip, which is fine on a plain local checkout."""
import importlib
import os
import unittest

REQUIRED = ("mcp", "pydantic", "uvicorn", "httpx")


@unittest.skipUnless(os.environ.get("CITEBASE_REQUIRE_CONNECTOR_DEPS") == "1", "dependencies are optional here")
class ConnectorDependenciesPresent(unittest.TestCase):
    def test_every_connector_dependency_imports(self):
        for name in REQUIRED:
            with self.subTest(package=name):
                importlib.import_module(name)


class WorkflowRequiresThem(unittest.TestCase):
    def test_workflow_sets_the_switch_for_the_job_that_installs_them(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, ".github", "workflows", "ci.yml"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("CITEBASE_REQUIRE_CONNECTOR_DEPS", text)
