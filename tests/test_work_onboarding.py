import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "connector"))
import storage
import work_onboarding as onboarding


class SetupTests(unittest.IsolatedAsyncioTestCase):
    async def test_save_custom_choices_and_retry(self):
        backend = storage.MemoryBackend()
        storage.set_backend(backend)
        self.addCleanup(storage.set_backend, None)
        key = storage.key("shop", "meta")
        await backend.set(key, {"brand": {"name": "Shop", "domain": "shop.example"}})
        async def call(op, **data):
            return await onboarding.execute("shop", "onboarding_" + op, data)
        self.assertEqual((await call("get"))["stage"], "competitors")
        await call("save", step="competitors", competitors=[], revision=0)
        data = dict(step="terms", terms=["leather boots"], revision=1)
        result = await call("save", **data)
        self.assertEqual(await call("save", **data), result)
        self.assertEqual(result["stage"], "research")
        self.assertEqual((await backend.get(storage.key("shop", "panel")))[0]["topic"], "leather boots")
        with self.assertRaises(ValueError):
            await call("save", **{**data, "terms": ["different"]})

    async def test_site_comparison_and_gsc_terms_are_grounded(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch
        backend = storage.MemoryBackend()
        storage.set_backend(backend)
        self.addCleanup(storage.set_backend, None)
        await backend.set(storage.key("shop", "meta"), {"brand": {"name": "Shop", "domain": "shop.example"}})
        await backend.set(storage.key("shop", "signal", "search", "2026-10-01"),
                          {"gaps": [{"query": "winter boots", "impressions": 213}]})
        async def review(project, evidence, data):
            return evidence
        pages = [{"title": "Shop vs Other", "url": "https://shop.example/compare",
                  "description": "", "h1": ["Handmade winter boots"]}]
        with patch.object(onboarding, "site_pages", return_value=pages) as public_read, patch.dict(
                sys.modules, onboarding_ai=SimpleNamespace(review=AsyncMock(side_effect=review))):
            state = await onboarding.execute("shop", "onboarding_suggest", {"revision": 0})
            self.assertEqual(state["competitors"][0]["name"], "Other")
            self.assertEqual(state["terms"][0]["impressions"], 213)
            self.assertEqual(await onboarding.execute("shop", "onboarding_get", {}), state)
            public_read.assert_called_once()

    async def test_interrupted_projection_recovers_and_preserves_historical_panel(self):
        from unittest.mock import AsyncMock, patch
        backend = storage.MemoryBackend()
        storage.set_backend(backend)
        self.addCleanup(storage.set_backend, None)
        meta = storage.key("shop", "meta")
        await backend.set(meta, {"brand": {"name": "Shop", "domain": "shop.example"}})
        panel = [{"topic": "boots", "prompt_id": "manual", "type": "consideration", "prompt": "Which boots last?"}]
        await backend.set(storage.key("shop", "panel"), panel)
        data = dict(revision=0, step="competitors", competitors=["Other"])
        with patch.object(onboarding, "project_choices", AsyncMock(side_effect=OSError("unavailable"))):
            with self.assertRaises(OSError):
                await onboarding.execute("shop", "onboarding_save", data)
        await onboarding.execute("shop", "onboarding_save", data)
        self.assertEqual((await onboarding.history.load_meta("shop"))["brand"]["competitors"], ["Other"])
        ready = await onboarding.execute("shop", "onboarding_save",
                                         {"revision": 1, "step": "terms", "use_recommended": True})
        self.assertEqual(ready["questions"], panel)
        self.assertEqual(await backend.get(storage.key("shop", "panel")), panel)

    async def test_finished_project_can_correct_terms_without_replacing_questions(self):
        be = storage.MemoryBackend()
        storage.set_backend(be)
        self.addCleanup(storage.set_backend, None)
        await be.set(storage.key("shop", "meta"), {"brand": {"name": "Shop", "domain": "shop.example"}})
        for revision, step, values in [(0, "competitors", []), (1, "terms", ["boots"]),
                                        (2, "terms", ["shoes"]), (3, "competitors", ["Rival"])]:
            result = await onboarding.execute("shop", "onboarding_save",
                                              {"revision": revision, "step": step, step: values})
        self.assertEqual(result["stage"], "research")
        self.assertEqual([r["term"] for r in result["terms"] if r["selected"]], ["shoes"])
        self.assertEqual(result["questions"][0]["topic"], "boots")

    async def test_refresh_preserves_confirmed_choices_and_distinguishes_search_competitors(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        be = storage.MemoryBackend()
        storage.set_backend(be)
        self.addCleanup(storage.set_backend, None)
        await be.set(storage.key("shop", "meta"), {"brand": {"name": "Shop", "domain": "shop.example"}})
        for revision, (step, choices) in enumerate([("competitors", []), ("terms", ["existing topic"])]):
            await onboarding.execute("shop", "onboarding_save", {"revision": revision, "step": step, step: choices})
        store = await onboarding.work.RevisionStore.open(be, await be.private_store(), "research")
        await store.set(onboarding.work.prefix(be, "shop") + ".research", {"revision": 1, "pages": [
            {"url": "https://editor.example/buy", "domain": "editor.example", "term": "boots", "position": 4}]})
        async def review(project, evidence, data):
            return evidence
        pages = [{"title": "Product", "url": "https://shop.example/new", "h1": [],
                  "h2": ["Switch from Acme"], "description": ""}]
        with patch.object(onboarding, "site_pages", return_value=pages), patch.dict(
                sys.modules, onboarding_ai=SimpleNamespace(review=review)):
            state = await onboarding.execute("shop", "onboarding_suggest", {"revision": 2})
        self.assertEqual(state["stage"], "research")
        self.assertEqual({x["name"] for x in state["competitors"]}, {"editor.example", "Acme"})
        self.assertFalse(any(x["selected"] for x in state["competitors"]))
        self.assertEqual(state["questions"][0]["topic"], "existing topic")

    def test_site_topics_use_product_and_service_evidence(self):
        fixtures = [("Forge", "services", "emergency-boiler-repair", "Emergency boiler repair"),
                    ("Trek", "products", "waterproof-hiking-boots", "Waterproof hiking boots")]
        for brand, folder, slug, topic in fixtures:
            page = {"url": f"https://example.org/{folder}/{slug}", "title": f"About {brand}",
                    "h1": ["Built for your future"], "description": f"We offer {topic.lower()} in our store."}
            terms = [r["term"].lower() for r in onboarding.site_topics(page, brand)]
            self.assertIn(topic.lower(), terms)
            self.assertNotIn("built for your future", terms)
        page = {"url": "https://iana.org/about", "title": "About IANA", "h1": ["The Organization"],
                "description": "Welcome to our official website."}
        self.assertEqual(list(onboarding.site_topics(page, "IANA")), [])

    async def test_delayed_old_projection_cannot_replace_new_choices_or_unrelated_metadata(self):
        import asyncio
        be = storage.MemoryBackend()
        storage.set_backend(be)
        self.addCleanup(storage.set_backend, None)
        key = storage.key("shop", "meta")
        await be.set(key, {"brand": {"name": "Shop"}, "settings": {}})
        old = {"competitors_revision": 1, "competitors": [{"name": "Old", "selected": True}], "stage": "terms"}
        new = {**old, "competitors_revision": 3, "competitors": [{"name": "New", "selected": True}]}
        started, release = asyncio.Event(), asyncio.Event()
        original = be.set
        async def delayed(k, value):
            if k.endswith("000000000001"):
                started.set()
                await release.wait()
            await original(k, value)
        be.set = delayed
        task = asyncio.create_task(onboarding.project_choices(be, "shop", old))
        await started.wait()
        await onboarding.project_choices(be, "shop", new)
        await be.set(key, {"brand": {"name": "Changed"}, "settings": {"language": "fr"}})
        release.set()
        await task
        meta = await onboarding.history.load_meta("shop")
        self.assertEqual(meta["brand"], {"name": "Changed", "competitors": ["New"]})
        self.assertEqual(meta["settings"], {"language": "fr"})

    async def test_interleaved_first_panels_materialize_only_the_elected_questions(self):
        import asyncio
        be = storage.MemoryBackend()
        key = storage.key("shop", "panel")
        started, release = asyncio.Event(), asyncio.Event()
        original = be.set
        async def delayed(k, value):
            if k == key and not started.is_set():
                started.set()
                await release.wait()
            await original(k, value)
        be.set = delayed
        first = [onboarding.tracking_question("boots")]
        old = asyncio.create_task(onboarding.history.first_panel(be, "shop", first))
        await started.wait()
        actual = await onboarding.history.first_panel(be, "shop", [onboarding.tracking_question("soap")])
        release.set()
        self.assertEqual(await old, actual)
        self.assertEqual(await be.get(key), first)

    def test_custom_competitor_domains_belong_to_selected_names_and_survive_refresh(self):
        state = {"stage": "competitors", "website": "https://mybrand.com", "competitors": []}
        data = {"revision": 0, "step": "competitors", "competitors": ["Rival"], "competitor_domains": {"Rival": "www.acme.com"}}
        rows = onboarding.choose(state, data, [])["competitors"]
        self.assertEqual(onboarding.preserve_choices(rows, [{**rows[0], "domain": "bad.com"}], "name")[0]["domain"], "acme.com")
        for value in ["localhost", "10.0.0.1", "other.com:443", "me@other.com", "mybrand.com", "x.mybrand.com", "x.local"]:
            with self.assertRaises(ValueError):
                onboarding.choose(state, {**data, "competitor_domains": {"Rival": value}}, [])
        with self.assertRaises(ValueError):
            onboarding.choose(state, {**data, "competitor_domains": {"Another": "acme.com"}}, [])

    def test_using_recommended_after_manual_selection_restores_model_defaults(self):
        state = {"stage": "research", "terms": [
            {"term": "boilers", "selected": False, "ai_checked": True, "recommended": True},
            {"term": "custom term", "selected": True}], "questions": []}
        saved = onboarding.choose(state, {"revision": 2, "step": "terms", "use_recommended": True}, [])
        self.assertEqual([r["term"] for r in saved["terms"] if r["selected"]], ["boilers"])

    async def test_native_gsc_uses_current_site_and_excludes_previous_site_mirror(self):
        from unittest.mock import patch
        be = storage.MemoryBackend()
        storage.set_backend(be)
        self.addCleanup(storage.set_backend, None)
        key = storage.key("clinic", "meta")
        await be.set(key, {"brand": {"name": "Clinic", "site": "https://new.example"}})
        day = "2026-11-01"
        native = {"service": "gsc", "website": "https://old.example", "source": "Google Search Console",
                  "property": "sc-domain:old.example", "end_date": day,
                  "rows": [{"term": "retired dental query", "impressions": 2000}]}
        await be.set(storage.key("clinic", "google", "gsc", day), native)
        await be.set(storage.key("clinic", "signal", "search", day),
                     {"gaps": [{"query": "retired dental query", "impressions": 2000}]})
        with patch.object(onboarding, "site_pages", return_value=[]):
            first = await onboarding.execute("clinic", "onboarding_suggest", {"revision": 0})
            self.assertEqual(first["terms"], [])
            rows = [{"term": f"hearing aid fitting {n}", "clicks": n, "impressions": n*10, "position": 2.5}
                    for n in range(25)]
            await be.set(storage.key("clinic", "google", "gsc", day),
                         {**native, "website": "https://new.example", "property": "sc-domain:new.example", "rows": rows})
            result = await onboarding.execute("clinic", "onboarding_suggest", {"revision": 1})
        top = result["terms"][0]
        self.assertEqual((top["term"], top["source"], top["clicks"], top["impressions"], top["position"]),
                         ("hearing aid fitting 24", "Google Search Console", 24, 240, 2.5))
        self.assertLessEqual(len(result["terms"]), 20)
        await be.set(key, {"brand": {"name": "Optics", "site": "https://optics.example"}})
        with patch.object(onboarding, "site_pages", return_value=[]):
            moved = await onboarding.execute("clinic", "onboarding_suggest", {"revision": 2})
        self.assertEqual(moved["terms"], [])
        self.assertEqual(moved["website"], "https://optics.example")
