"""The tools the MCP server offers and the arguments the /run endpoint accepts must be the same.

A tool that takes an argument over MCP but refuses it on /run (or the other way round) is a bug the user meets as
"does not take X". This reads server.py without importing it (so it runs where the `mcp` package is missing); the
served-schema version of the same check lives in test_connector_server.py.
"""
import ast
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "connector"))
import runner  # noqa: E402


def declared_tools() -> dict[str, set[str]]:
    """{tool name: argument names} for every function in server.py registered with @tool("name", ...)."""
    with open(os.path.join(ROOT, "connector", "server.py"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    build = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "build_server")
    found: dict[str, set[str]] = {}
    for fn in ast.walk(build):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in fn.decorator_list:
            if (isinstance(deco, ast.Call) and getattr(deco.func, "id", "") == "tool" and deco.args
                    and isinstance(deco.args[0], ast.Constant)):
                args = fn.args
                names = [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]
                found[deco.args[0].value] = set(names)
    return found


class ParityTests(unittest.TestCase):
    def test_server_declares_every_tool_except_the_schedule_only_one(self):
        self.assertEqual(set(declared_tools()), set(runner.TOOL_NAMES) - runner.ONE_SHOT_ONLY)

    def test_each_tools_arguments_match_what_run_accepts(self):
        for name, args in declared_tools().items():
            self.assertEqual(args, runner.ALLOWED_ARGS[name], f"{name}: server.py arguments differ from runner.ALLOWED_ARGS")

    def test_every_tool_has_an_allowed_args_entry(self):
        self.assertEqual(set(runner.ALLOWED_ARGS), set(runner.TOOL_NAMES))

    def test_stateless_dispatch_arguments_are_a_subset_of_run_arguments(self):
        import tools
        for name, args in tools.ALLOWED_ARGS.items():
            self.assertLessEqual(args, runner.ALLOWED_ARGS[name], name)

    def test_the_parser_sees_real_functions(self):
        found = declared_tools()
        self.assertEqual(found["quote_cost"], {"pack", "items"})
        self.assertGreaterEqual(len(found), 11)


if __name__ == "__main__":
    unittest.main()
