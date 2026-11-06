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
MAX_SNAPSHOTS = 60
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


class MemoryBackend:
    """In-memory store for tests and local runs."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

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

    def __init__(self, kvs) -> None:
        self.kvs = kvs

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

                _backend = ApifyBackend(await Actor.open_key_value_store(name=STORE_NAME))
            elif os.environ.get("CITEBASE_ALLOW_MEMORY") == "1":
                _backend = MemoryBackend()  # tests and local trials only: one shared store, lost on restart
            else:
                raise ValueError("Saving needs to run on Apify, where it is stored in your own account. "
                                 "Run the Actor there, or set CITEBASE_ALLOW_MEMORY=1 for a throwaway local trial.")
    return _backend
