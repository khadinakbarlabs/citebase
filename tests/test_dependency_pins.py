"""Connector dependencies stay inside a known major version, CI installs the same ranges, and updates are watched."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def requirements() -> dict[str, str]:
    out = {}
    for line in read("connector", "requirements.txt").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            name = re.match(r"[A-Za-z0-9_.-]+", line).group(0)
            out[name.lower()] = line
    return out


class PinTests(unittest.TestCase):
    def test_every_requirement_has_a_lower_and_an_upper_bound(self):
        for name, line in requirements().items():
            self.assertRegex(line, r">=[\d.]+", name)
            self.assertRegex(line, r"<[\d.]+", name)

    def test_the_known_risky_ones_are_capped_at_the_next_major(self):
        reqs = requirements()
        self.assertIn("pydantic>=2.7,<3", reqs["pydantic"].replace(" ", ""))
        self.assertIn("uvicorn>=0.30,<1", reqs["uvicorn"].replace(" ", ""))

    def test_ci_installs_the_same_ranges(self):
        ci = read(".github", "workflows", "ci.yml")
        for name, line in requirements().items():
            if name == "apify":
                continue  # the Apify SDK is not needed for the tests
            self.assertIn(line.replace(" ", ""), ci.replace(" ", ""), name)

    def test_dependabot_watches_pip_and_github_actions(self):
        text = read(".github", "dependabot.yml")
        self.assertIn("version: 2", text)
        self.assertRegex(text, r"package-ecosystem:\s*pip")
        self.assertRegex(text, r"package-ecosystem:\s*github-actions")
        self.assertIn("/connector", text)  # where requirements.txt lives


if __name__ == "__main__":
    unittest.main()
