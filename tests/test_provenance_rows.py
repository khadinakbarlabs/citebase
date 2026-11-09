"""Where an answer came from is kept on the run row: model, country, language, device, retrieval path, time.

The counting rule does not change (metric_version stays 2); old rows simply read as unknown ('').
"""
import asyncio
import csv
import importlib.util
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "connector"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import citation_loop as cl  # noqa: E402
import history as hist  # noqa: E402
import importer  # noqa: E402
import storage as stg  # noqa: E402
import tools  # noqa: E402

PANEL = [{"prompt_id": f"p{i}", "prompt": f"question {i}", "type": t}
         for i, t in enumerate(["awareness", "awareness", "consideration", "consideration", "control", "control"], 1)]
PANEL_ROWS = {p["prompt_id"]: p for p in PANEL}
FIELDS = ("engine_version", "country", "language", "device", "source", "answered_at")


def run(coro):
    return asyncio.run(coro)


def row(**extra):
    return {"prompt_id": "p1", "platform": "chatgpt", "repeat": 1, "recommended": True, **extra}


class RowShapeTests(unittest.TestCase):
    def test_run_columns_end_with_the_provenance_fields(self):
        self.assertEqual(cl.RUN_COLS[-6:], list(FIELDS))
        self.assertEqual(cl.RUN_COLS[:13], ["run_id", "snapshot", "date", "prompt_id", "platform", "repeat", "mentioned",
                                            "cited", "recommended", "position", "competitors", "cited_domains",
                                            "metric_version"])

    def test_a_row_without_them_reads_as_unknown(self):
        out = cl.normalise_run(row(), PANEL_ROWS, "baseline", 1)
        for field in FIELDS:
            self.assertEqual(out[field], "", field)

    def test_values_are_kept_and_tidied(self):
        out = cl.normalise_run(row(engine_version=" GPT-4o ", country="us", language="EN", device="Desktop",
                                   source="SerpAPI", answered_at="2026-11-07T10:00:00Z"), PANEL_ROWS, "baseline", 1)
        self.assertEqual(out["engine_version"], "gpt-4o")
        self.assertEqual(out["country"], "US")  # two-letter codes are upper-case so 'us' and 'US' are the same place
        self.assertEqual(out["language"], "en")
        self.assertEqual(out["device"], "desktop")
        self.assertEqual(out["source"], "serpapi")
        self.assertEqual(out["answered_at"], "2026-11-07T10:00:00Z")

    def test_long_or_odd_values_are_cut_not_refused(self):
        out = cl.normalise_run(row(engine_version="m" * 500, country=None, device=12, answered_at="t" * 200),
                               PANEL_ROWS, "baseline", 1)
        self.assertLessEqual(len(out["engine_version"]), 80)
        self.assertEqual(out["country"], "")
        self.assertEqual(out["device"], "12")
        self.assertLessEqual(len(out["answered_at"]), 40)

    def test_the_date_comes_from_the_full_timestamp_when_no_date_is_given(self):
        out = cl.normalise_run(row(answered_at="2026-11-07T10:00:00Z"), PANEL_ROWS, "baseline", 1)
        self.assertEqual(out["date"], "2026-11-07")
        given = cl.normalise_run(row(date="2026-11-09", answered_at="2026-11-07T10:00:00Z"), PANEL_ROWS, "baseline", 1)
        self.assertEqual(given["date"], "2026-11-09")  # an explicit date wins

    def test_counting_is_unchanged(self):
        self.assertEqual(cl.METRIC_VERSION, 2)
        self.assertEqual(importer.METRIC_VERSION, cl.METRIC_VERSION)
        out = cl.normalise_run(row(country="us"), PANEL_ROWS, "baseline", 1)
        self.assertEqual(out["metric_version"], 2)

    def test_tools_normalise_runs_passes_the_fields_through(self):
        rows = tools.normalise_runs([dict(row(country="de", device="mobile"), snapshot="baseline")], PANEL_ROWS)
        self.assertEqual((rows[0]["country"], rows[0]["device"]), ("DE", "mobile"))


class CsvCompatibilityTests(unittest.TestCase):
    def test_an_old_runs_file_is_upgraded_in_place_when_new_rows_arrive(self):
        old_cols = cl.RUN_COLS[:13]
        with tempfile.TemporaryDirectory() as tmp:
            cl.write_csv(os.path.join(tmp, "panel.csv"), cl.PANEL_COLS, PANEL)
            with open(os.path.join(tmp, "runs.csv"), "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=old_cols)
                w.writeheader()
                w.writerow({"run_id": "r00001", "snapshot": "old", "date": "2026-10-01", "prompt_id": "p1",
                            "platform": "chatgpt", "repeat": 1, "mentioned": 1, "cited": 0, "recommended": 1,
                            "position": "", "competitors": "", "cited_domains": "", "metric_version": 2})
            with open(os.path.join(tmp, "panel.lock.json"), "w") as fh:
                fh.write('{"sha256": "%s", "n_prompts": 6}' % cl.panel_hash(PANEL_ROWS))
            incoming = os.path.join(tmp, "new.json")
            with open(incoming, "w") as fh:
                fh.write('[{"prompt_id": "p1", "platform": "chatgpt", "repeat": 1, "recommended": 1, '
                         '"engine_version": "gpt-4o", "country": "us"}]')
            args = type("A", (), {"dir": tmp, "file": incoming, "snapshot": "new"})()
            self.assertEqual(cl.cmd_ingest(args), 0)
            rows = cl.read_csv(os.path.join(tmp, "runs.csv"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["engine_version"], "")  # the old row reads as unknown
        self.assertEqual(rows[1]["engine_version"], "gpt-4o")
        self.assertEqual(rows[1]["country"], "US")


class SavedRowTests(unittest.TestCase):
    def setUp(self):
        stg.set_backend(stg.MemoryBackend())
        self.addCleanup(stg.set_backend, None)

    def test_saved_and_loaded_rows_keep_the_fields(self):
        run(hist.save_results("acme-site", [dict(row(engine_version="gpt-4o", country="US", language="en", device="desktop",
                                                    source="camoufox", answered_at="2026-11-07T10:00:00Z"),
                                                 snapshot="baseline")], PANEL))
        loaded = run(hist.load_project("acme-site"))["runs"][0]
        self.assertEqual((loaded["engine_version"], loaded["country"], loaded["source"]), ("gpt-4o", "US", "camoufox"))
        self.assertEqual(loaded["answered_at"], "2026-11-07T10:00:00Z")

    def test_rows_saved_before_the_fields_existed_still_load_and_measure(self):
        old = {"run_id": "r00001", "snapshot": "baseline", "date": "2026-10-01", "prompt_id": "p1", "platform": "chatgpt",
               "repeat": 1, "mentioned": 1, "cited": 0, "recommended": 1, "position": "", "competitors": "",
               "cited_domains": "", "metric_version": 2}

        async def go():
            backend = await stg.get_backend()
            await backend.set(stg.key("acme-site", "panel"), list(PANEL_ROWS.values()))
            await backend.set(stg.key("acme-site", "runs", "baseline"), [old])
            await backend.set(stg.key("acme-site", "meta"), {"project": "acme-site", "created": "2026-10-01", "brand": {},
                                                             "snapshots": {"baseline": "2026-10-01"}})
            return await hist.history("acme-site")
        history = run(go())
        self.assertEqual(history["snapshots"][0]["snapshot"], "baseline")  # no crash on a row without the new keys
        self.assertEqual(history["snapshots"][0]["context"], {})  # nothing recorded


@unittest.skipUnless(importlib.util.find_spec("pydantic"), "pydantic is not installed")
class ModelTests(unittest.TestCase):
    def test_run_row_model_documents_and_accepts_the_fields(self):
        import models
        schema = models.RunRow.model_json_schema()
        for field in FIELDS:
            self.assertIn(field, schema["properties"], field)
            self.assertTrue(schema["properties"][field].get("description"), field)
        parsed = models.RunRow(snapshot="baseline", prompt_id="p1", platform="chatgpt", recommended=True,
                               engine_version="gpt-4o", country="US")
        dumped = parsed.model_dump(exclude_none=True)
        self.assertEqual((dumped["engine_version"], dumped["country"]), ("gpt-4o", "US"))
        self.assertNotIn("language", dumped)  # unset stays out of the row


if __name__ == "__main__":
    unittest.main()
