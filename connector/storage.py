"""Per-user project storage for history and reports.

Data is saved only when a tool is given a `project`, and only in a named key-value store that belongs to the
account that is running the Actor. Citebase runs single-tenant: when someone connects with their own Apify
sign-in, the run (and therefore this store) is in THEIR account. Nothing is ever written to the author's account.
Without Apify the store refuses to work, unless CITEBASE_ALLOW_MEMORY=1 is set for a throwaway local trial (tests set it).
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any

STORE_NAME = "citebase-projects"
MAX_PROJECTS = 100
MAX_SNAPSHOTS = 160  # about three years of weekly rounds; every round is read for a report, so not unlimited
KEY_PREFIX = "p."


def clean_slug(text: Any) -> str:
    """Project names: 3-40 letters, numbers and dashes, for example 'acme-site'. Raises ValueError otherwise."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    if not (3 <= len(slug) <= 40):
        raise ValueError("A project name needs 3 to 40 letters, numbers or dashes, for example 'acme-site'.")
    return slug


def clean_part(text: Any) -> str:
    """Snapshot or date labels used inside keys, for example 'baseline' or '2026-12'."""
    part = re.sub(r"[^A-Za-z0-9_-]+", "-", str(text or "")).strip("-")
    if not (1 <= len(part) <= 40):
        raise ValueError("A snapshot name needs 1 to 40 letters, numbers or dashes, for example 'baseline' or '2026-12'.")
    return part


def key(project: str, *parts: str) -> str:
    return KEY_PREFIX + ".".join([project, *parts])


MAX_DATASET_ITEMS = 5000
DATASET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9~._-]{4,79}$")
CANNOT_READ_DATASET = ("Citebase could not read the results '{id}' from your Apify account ({why}). Check the dataset "
                       "id from the finished run, or pass the result items themselves as `items` instead.")


def clean_dataset_id(value: Any) -> str:
    """A dataset id as Apify prints it, for example 'aBcD1234efGh5678'. Raises ValueError for anything else,
    so text from a web page can never be turned into a request path."""
    text = str(value or "").strip()
    if not DATASET_ID.match(text):
        raise ValueError("A dataset id looks like 'aBcD1234efGh5678' (letters and numbers from the finished run's "
                         "defaultDatasetId). It is not a web address or a run name.")
    return text


class MemoryBackend:
    """In-memory store for tests and local runs."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.datasets: dict[str, list] = {}  # tests put finished-run results here
        self.dataset_sources: dict[str, str] = {}  # tests: dataset id -> 'owner/name' of the Actor that made it

    async def dataset_source(self, dataset_id: str) -> str | None:
        return self.dataset_sources.get(dataset_id)

    async def dataset_items(self, dataset_id: str, limit: int = MAX_DATASET_ITEMS) -> list:
        if dataset_id not in self.datasets:
            raise ValueError(CANNOT_READ_DATASET.format(id=dataset_id, why="no such dataset"))
        return list(self.datasets[dataset_id][:limit])

    async def get(self, k: str) -> Any:
        return self.data.get(k)

    async def set(self, k: str, value: Any, content_type: str | None = None) -> None:
        self.data[k] = value

    async def keys(self, prefix: str = "") -> list[str]:
        return sorted(k for k in self.data if k.startswith(prefix))

    async def delete(self, k: str) -> None:
        self.data.pop(k, None)

    async def public_url(self, k: str) -> str | None:
        return None


class ApifyBackend:
    """Named key-value store in the account that is running this Actor."""

    def __init__(self, kvs, client=None) -> None:
        self.kvs = kvs
        self.client = client  # Apify API client that carries the running account's own token

    async def dataset_source(self, dataset_id: str) -> str | None:
        """'owner/name' of the Actor whose run made this dataset; None when no Actor made it (a hand-made dataset) or
        when that cannot be read. Used only to refuse results made by another creator's Actor."""
        if self.client is None:
            return None
        try:
            info = await self.client.dataset(dataset_id).get()
            act_id = getattr(info, "act_id", None)
            if not act_id:
                return None
            actor = await self.client.actor(str(act_id)).get()
            owner, name = getattr(actor, "username", None), getattr(actor, "name", None)
            return f"{owner}/{name}".lower() if owner and name else None
        except Exception:  # metadata is a safety check, never a reason to lose a user's results
            return None

    async def dataset_items(self, dataset_id: str, limit: int = MAX_DATASET_ITEMS) -> list:
        """Reads a finished run's results straight from the caller's account, so the assistant does not have to
        copy hundreds of items through the chat. Any failure becomes a plain sentence with the way round it."""
        if self.client is None:
            raise ValueError(CANNOT_READ_DATASET.format(id=dataset_id, why="reading datasets is not available here"))
        try:
            page = await self.client.dataset(dataset_id).list_items(limit=limit, clean=True)
        except Exception as err:  # not found, no permission, network: all need the same advice
            raise ValueError(CANNOT_READ_DATASET.format(id=dataset_id, why=type(err).__name__)) from err
        if page is None:
            raise ValueError(CANNOT_READ_DATASET.format(id=dataset_id, why="no such dataset"))
        return list(page.items)

    async def get(self, k: str) -> Any:
        return await self.kvs.get_value(k)

    async def set(self, k: str, value: Any, content_type: str | None = None) -> None:
        await self.kvs.set_value(k, value, content_type=content_type)

    async def keys(self, prefix: str = "") -> list[str]:
        out: list[str] = []
        start = None
        while True:
            page = await self.kvs.list_keys(exclusive_start_key=start, limit=1000)
            if not page:
                break
            out.extend(item.key for item in page if item.key.startswith(prefix))
            if len(page) < 1000:
                break
            start = page[-1].key
        return sorted(out)

    async def delete(self, k: str) -> None:
        await self.kvs.set_value(k, None)  # setting a record to None removes it

    async def public_url(self, k: str) -> str | None:
        try:
            return await self.kvs.get_public_url(k)
        except Exception:  # sharing links are a nice-to-have; saving must not fail because of them
            return None


_backend: Any = None
_lock = asyncio.Lock()


def set_backend(backend: Any) -> None:
    """Used by tests to choose the backend."""
    global _backend
    _backend = backend


async def get_backend() -> Any:
    global _backend
    if _backend is not None:
        return _backend
    async with _lock:
        if _backend is None:
            if os.environ.get("APIFY_IS_AT_HOME"):
                from apify import Actor  # imported here so tests and plain tools never need the Apify SDK

                _backend = ApifyBackend(await Actor.open_key_value_store(name=STORE_NAME),
                                        getattr(Actor, "apify_client", None))
            elif os.environ.get("CITEBASE_ALLOW_MEMORY") == "1":
                _backend = MemoryBackend()  # tests and local trials only: one shared store, lost on restart
            else:
                raise ValueError("Saving needs to run on Apify, where it is stored in your own account. "
                                 "Run the Actor there, or set CITEBASE_ALLOW_MEMORY=1 for a throwaway local trial.")
    return _backend
