"""Per-user project storage for history and reports.

Data is saved only when a tool is given a `project`, and only in a named key-value store that belongs to the
account that is running the Actor. Citebase runs single-tenant: when someone connects with their own Apify
sign-in, the run (and therefore this store) is in THEIR account. Nothing is ever written to the author's account.
Without Apify the store refuses to work, unless CITEBASE_ALLOW_MEMORY=1 is set for a throwaway local trial (tests set it).
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
import os
import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

STORE_NAME = "citebase-projects"
PROSPECT_STORE = "citebase-prospect-reports"
PRIVATE_STORE = "citebase-private-answers"
MAX_PROJECTS = 100
MAX_SNAPSHOTS = 160  # about three years of weekly rounds; every round is read for a report, so not unlimited
KEY_PREFIX = "p."


_caller_backend = ContextVar("caller_backend", default=None)
_read_only = ContextVar("citebase_read_only", default=False)
_fixture_backend = None
_project_store = ContextVar("project_store", default=None)


@contextmanager
def project_store_grant(store_id: str | None):
    if store_id is not None and (not isinstance(store_id, str) or not re.fullmatch(r"[A-Za-z0-9]{5,80}", store_id)):
        raise ValueError("Select the existing project storage by its Apify ID.")
    context = _project_store.set(store_id)
    try:
        yield
    finally:
        _project_store.reset(context)


def actor_owned_store_name(name: str) -> str | None:
    actor_id = os.environ.get("ACTOR_ID") or os.environ.get("APIFY_ACTOR_ID") or os.environ.get("APIFY_ACT_ID") or ""
    return f"{name}-v2-{actor_id.lower()}" if re.fullmatch(r"[A-Za-z0-9]{5,30}", actor_id) else None


async def open_named_store(open_store, name: str):
    try:
        return await open_store(name=name)
    except Exception as err:
        owned_name = actor_owned_store_name(name)
        if getattr(err, "status_code", None) != 403 or not owned_name:
            raise
    # Under Limited permissions Apify grants new, Actor-created stores to that Actor in subsequent runs.
    return await open_store(name=owned_name)


async def new_private_project_store(client, owner, username, name):
    """Claim a private name on a fresh store, so a race never changes another store's sharing."""
    fresh = await client.key_value_stores().get_or_create()
    if not fresh or not fresh.id or fresh.user_id != owner or fresh.name:
        raise ValueError("Citebase could not create an empty private project store.")
    resource = client.key_value_store(fresh.id)
    try:
        await resource.update(name=name, general_access="RESTRICTED")
    except Exception as error:
        # A simultaneous creation can claim the name. Use its existing access setting.
        if getattr(error, "status_code", None) not in (400, 409):
            raise
        existing = await client.key_value_store(username + "~" + name).get()
        if not existing or existing.user_id != owner or existing.name != name:
            raise
        return existing
    current = await resource.get()
    if (not current or current.id != fresh.id or current.user_id != owner or current.name != name
            or current.general_access != "RESTRICTED"):
        raise ValueError("Citebase could not verify the new private project store.")
    return current


async def run_project_store(actor):
    owner, client = actor.configuration.user_id, actor.apify_client
    if not owner:
        raise ValueError("Citebase could not identify the account for project storage.")
    name = STORE_NAME
    for candidate in dict.fromkeys((name, actor_owned_store_name(name) or name)):
        name = candidate
        try:
            existing = await client.key_value_store("~" + name).get()
        except Exception as error:
            if getattr(error, "status_code", None) != 403:
                raise
            continue
        if existing:
            if existing.user_id != owner or existing.name != name:
                raise ValueError("The project storage does not belong to this account.")
            return await actor.open_key_value_store(id=existing.id)
        break
    selected = await new_private_project_store(client, owner, "", name)
    return await actor.open_key_value_store(id=selected.id)


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
        self._private = None
        self._prospects = None
        self.datasets: dict[str, list] = {}  # tests put finished-run results here
        self.dataset_sources: dict[str, str] = {}  # tests: dataset id -> 'owner/name' of the Actor that made it

    async def private_store(self):
        if self._private is None:
            if _read_only.get():
                return MemoryBackend()
            self._private = MemoryBackend()
        return self._private

    async def existing_private_store(self):
        return self._private

    async def prospect_store(self):
        if self._prospects is None:
            if _read_only.get():
                return MemoryBackend()
            self._prospects = MemoryBackend()
        return self._prospects

    async def dataset_source(self, dataset_id: str) -> str | None:
        # '' = hand-made dataset (no Actor made it); None = set on purpose in tests to mean "could not be read"
        return self.dataset_sources.get(dataset_id, "")

    async def dataset_items(self, dataset_id: str, limit: int = MAX_DATASET_ITEMS) -> list:
        if dataset_id not in self.datasets:
            raise ValueError(CANNOT_READ_DATASET.format(id=dataset_id, why="no such dataset"))
        return list(self.datasets[dataset_id][:limit])

    async def get(self, k: str) -> Any:
        return self.data.get(k)

    async def set(self, k: str, value: Any, content_type: str | None = None) -> None:
        if _read_only.get():
            raise ValueError("This project operation only reads saved records.")
        self.data[k] = value

    async def keys(self, prefix: str = "") -> list[str]:
        return sorted(k for k in self.data if k.startswith(prefix))

    async def delete(self, k: str) -> None:
        if _read_only.get():
            raise ValueError("This project operation only reads saved records.")
        self.data.pop(k, None)

    async def public_url(self, k: str) -> str | None:
        return None


def account_client(token, **options):
    from apify_client import ApifyClientAsync
    return ApifyClientAsync(token=token, max_retries=0, **options)


class ApifyBackend:
    """Named key-value store in the account that is running this Actor."""

    def __init__(self, kvs, client=None, *, signed_urls=False, project_store_id=None) -> None:
        self.kvs = kvs
        self.signed_urls = signed_urls
        opened_store_id = getattr(kvs, "id", None)
        self.project_store_id = project_store_id or (opened_store_id if isinstance(opened_store_id, str) else None)
        self.client = client  # Apify API client that carries the running account's own token
        self._private = None
        self._prospects = None
        self._store_lock = asyncio.Lock()

    @property
    def child_client(self):
        # A failed or ambiguous paid POST must never be retried by the SDK.
        from apify import Actor

        return account_client(Actor.configuration.token, api_url=Actor.configuration.api_base_url)

    async def _open_restricted(self, name: str):
        from apify import Actor

        if self.client is None:
            raise ValueError("Citebase needs Apify storage access to open this store.")
        try:
            resource = await open_named_store(self.client.key_value_stores().get_or_create, name)
            if resource.general_access == "FOLLOW_USER_SETTING":
                resource = await self.client.key_value_store(resource.id).update(general_access="RESTRICTED")
            if resource.general_access == "RESTRICTED":
                return ApifyBackend(await Actor.open_key_value_store(id=resource.id), signed_urls=True)
        except Exception:
            pass
        raise ValueError("Citebase could not confirm that this Apify store is private. Check access and set the dedicated store to Restricted in Apify.")

    async def private_store(self):
        async with self._store_lock:
            if self._private is None:
                self._private = await self._open_restricted(PRIVATE_STORE)
        return self._private

    async def prospect_store(self):
        async with self._store_lock:
            if self._prospects is None:
                self._prospects = await self._open_restricted(PROSPECT_STORE)
        return self._prospects

    async def dataset_source(self, dataset_id: str) -> str | None:
        """'owner/name' of the Actor whose run made this dataset; '' when no Actor made it (a hand-made dataset);
        None when that cannot be read. Used to refuse results made by another creator's Actor, and results whose
        maker cannot be told."""
        if self.client is None:
            return ""
        try:
            info = await self.client.dataset(dataset_id).get()
            act_id = getattr(info, "act_id", None)
            if not act_id:
                return ""
            actor = await self.client.actor(str(act_id)).get()
            owner, name = getattr(actor, "username", None), getattr(actor, "name", None)
            return f"{owner}/{name}".lower() if owner and name else None
        except Exception:
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
            url = await self.kvs.get_public_url(k)
            if self.signed_urls:
                parsed = urlsplit(url)
                if (parsed.netloc != "api.apify.com" or parsed.scheme != "https"
                        or set(parse_qs(parsed.query)) != {"signature"}):
                    return None
            return url
        except Exception:  # sharing links are a nice-to-have; saving must not fail because of them
            return None


_backend: Any = None
_lock = asyncio.Lock()


def set_backend(backend: Any) -> None:
    """Used by tests to choose the backend."""
    global _backend, _fixture_backend
    _backend = backend
    _fixture_backend = backend if isinstance(backend, MemoryBackend) else None


async def get_backend() -> Any:
    global _backend
    caller = _caller_backend.get()
    if caller is not None:
        return caller
    store_id = _project_store.get()
    if store_id:
        from apify import Actor

        return ApifyBackend(await Actor.open_key_value_store(id=store_id), Actor.apify_client,
                            project_store_id=store_id)
    if _backend is not None:
        return _backend
    async with _lock:
        if _backend is None:
            if os.environ.get("APIFY_IS_AT_HOME"):
                from apify import Actor  # imported here so tests and plain tools never need the Apify SDK

                _backend = ApifyBackend(await run_project_store(Actor), Actor.apify_client)
            elif os.environ.get("CITEBASE_ALLOW_MEMORY") == "1":
                _backend = MemoryBackend()  # tests and local trials only: one shared store, lost on restart
            else:
                raise ValueError("Saving needs to run on Apify, where it is stored in your own account. "
                                 "Run the Actor there, or set CITEBASE_ALLOW_MEMORY=1 for a throwaway local trial.")
    return _backend
