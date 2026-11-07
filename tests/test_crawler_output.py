"""Direct audits write their output even when the folder does not exist yet, and the crawler
identifies itself with the real plugin version."""
import http.server
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_site_audit import ROOT, SCRIPT, ServerCase  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "scripts"))
import site_audit as sa  # noqa: E402

UA_SHAPE = re.compile(r"^Mozilla/5\.0 \(compatible; CitebaseAudit/[0-9A-Za-z.+-]+; \+https://github\.com/khadinakbarlabs/citebase\)$")


def plugin_version():
    with open(os.path.join(ROOT, ".claude-plugin", "plugin.json")) as fh:
        return json.load(fh)["version"]


class OutputFolderTests(ServerCase):
    def run_cli(self, out, cwd=None):
        return subprocess.run([sys.executable, SCRIPT, self.base, "--max-pages", "3", "--delay", "0",
                               "--allow-private", "--out", out], capture_output=True, text=True, cwd=cwd, timeout=120)

    def test_missing_nested_output_folder_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "seo-workspace", "acme.com", "audit.json")
            proc = self.run_cli(out)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            with open(out) as fh:
                data = json.load(fh)
            self.assertIn("summary", data)
            self.assertIn("pages", data)

    def test_bare_filename_in_the_current_directory_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.run_cli("audit.json", cwd=tmp)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(os.path.isfile(os.path.join(tmp, "audit.json")))

    def test_existing_folder_and_existing_file_are_fine(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "audit.json")
            for _ in range(2):
                self.assertEqual(self.run_cli(out).returncode, 0)

    def test_unwritable_output_location_fails_before_the_crawl_with_a_clear_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocker = os.path.join(tmp, "afile")
            with open(blocker, "w") as fh:
                fh.write("x")
            proc = self.run_cli(os.path.join(blocker, "sub", "audit.json"))
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("Cannot create the output folder", proc.stderr)
            self.assertNotIn("Traceback", proc.stderr)
            self.assertEqual(proc.stdout.strip(), "")  # no crawl happened

    def test_output_path_that_is_a_directory_gives_a_clear_message_after_the_crawl_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.run_cli(tmp)
            self.assertNotEqual(proc.returncode, 0)
            self.assertNotIn("Traceback", proc.stderr)
            self.assertIn("Could not write", proc.stderr)
            self.assertIn("summary", proc.stdout)  # the crawl result is not lost

    def test_path_with_dot_dot_segments_resolves_normally(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "a", "..", "b", "audit.json")
            self.assertEqual(self.run_cli(out).returncode, 0)
            self.assertTrue(os.path.isfile(os.path.join(tmp, "b", "audit.json")))


class UserAgentTests(unittest.TestCase):
    def test_user_agent_carries_the_plugin_version(self):
        self.assertIn(f"CitebaseAudit/{plugin_version()}", sa.UA)
        self.assertRegex(sa.UA, UA_SHAPE)
        self.assertNotIn("CitebaseAudit/0.3", sa.UA)

    def test_version_reader_returns_the_manifest_version(self):
        self.assertEqual(sa.plugin_version(), plugin_version())

    def test_version_reader_falls_back_safely(self):
        with tempfile.TemporaryDirectory() as tmp:
            def write(text):
                path = os.path.join(tmp, "plugin.json")
                with open(path, "w") as fh:
                    fh.write(text)
                return path
            cases = [os.path.join(tmp, "missing.json"), write("{not json"), write("[]"), write("{}"),
                     write('{"version": 5}'), write('{"version": ""}'), write('{"version": null}'),
                     write('{"version": "1.0\\r\\nX-Evil: 1"}'), write('{"version": "1.0\\n"}'),
                     write('{"version": "1.0 ; rm"}'),
                     write('{"version": "' + "9" * 500 + '"}'), write('{"version": "1.0)"}'), tmp]
            for path in cases:
                self.assertEqual(sa.plugin_version(path), sa.FALLBACK_VERSION, path)
            self.assertEqual(sa.plugin_version(write('{"version": "1.2.3"}')), "1.2.3")
            self.assertEqual(sa.plugin_version(write('{"version": "1.2.3-rc.1"}')), "1.2.3-rc.1")

    def test_fallback_version_is_a_valid_token(self):
        self.assertRegex(sa.UA_TEMPLATE.format(version=sa.FALLBACK_VERSION), UA_SHAPE)


class UserAgentOnTheWireTests(unittest.TestCase):
    def test_requests_send_the_header(self):
        seen = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                seen.append(self.headers.get("User-Agent"))
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        self.addCleanup(setattr, sa, "ALLOW_PRIVATE", False)
        sa.ALLOW_PRIVATE = True
        with mock.patch.object(sa, "TIMEOUT_S", 3):
            sa.fetch(f"http://127.0.0.1:{server.server_address[1]}/")
        self.assertEqual(seen, [sa.UA])
        self.assertRegex(seen[0], UA_SHAPE)


if __name__ == "__main__":
    unittest.main()
