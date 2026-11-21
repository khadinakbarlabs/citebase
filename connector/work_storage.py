"""Use the signed-in token for every data operation in a verified request."""
from __future__ import annotations

from contextlib import asynccontextmanager
import re

import storage
import work_auth


def runtime_identity():
    from apify import Actor
    return Actor.configuration.user_id, Actor.apify_client


def runtime_actor_id():
    from apify import Actor
    return Actor.configuration.actor_id


class Selection:
    """Resolve the same resource as the Limited Actor using metadata only.

    Creating containers, changing access, reading content, and writing content always use the bearer.
    In particular, a caller denial on the chosen ID cannot silently open a different store.
    """
    def __init__(self, owner, username, runtime, caller, batch=None):
        self.owner, self.username = owner, username
        self.runtime, self.caller = runtime, caller
        self.batch = batch

    def owned(self, item, *, expected_id=None):
        if not item or item.user_id != self.owner or not item.id or (expected_id and item.id != expected_id):
            raise ValueError("This storage resource does not belong to the signed-in project account.")
        return item

    async def resolve(self, kind, name, *, selected_id=None, create=True):
        caller_resource = getattr(self.caller, kind)
        grant = (self.batch or {}).get("grants", {}).get(name)
        if grant:
            resource = caller_resource(grant)
            item = self.owned(await resource.get(), expected_id=grant)
            if item.name not in (name, storage.actor_owned_store_name(name)):
                raise ValueError("Select the existing Citebase storage for this operation.")
            return resource, item
        if selected_id:
            resource = caller_resource(selected_id)
            return resource, self.owned(await resource.get(), expected_id=selected_id)
        runtime_resource = getattr(self.runtime, kind)
        # Legacy accounts may have both the original name and its Limited-permissions replacement.
        fallback = storage.actor_owned_store_name(name)
        chosen_name = name
        try:
            candidate = await runtime_resource(self.username + "~" + name).get()
        except Exception as err:
            if getattr(err, "status_code", None) != 403 or not fallback:
                raise
            chosen_name = fallback
            try:
                candidate = await runtime_resource(self.username + "~" + fallback).get()
            except Exception as fallback_error:
                if getattr(fallback_error, "status_code", None) != 403:
                    raise
                # A new resource or an older caller-created fallback may not yet be granted
                # to the Actor. The caller must have its own grant on that exact name.
                candidate = None
        if candidate is None:
            # A resource absent from the Actor's view can still exist in the caller's account.
            # Select it with caller GET first so an existing read-only grant needs no creation.
            resource = caller_resource(self.username + "~" + chosen_name)
            try:
                candidate = await resource.get()
            except Exception as error:
                if not self.batch or getattr(error, "status_code", None) != 403:
                    raise
                if not create:
                    raise ValueError("This private record requires a storage grant. Select the existing Citebase storage in the Actor input.") from None
                # The platform can deny an ungranted by-name GET even when the allowed
                # create operation can initialize an Actor-owned store or revision queue.
                candidate = None
            if candidate is None:
                if not create:
                    return None, None
                if kind == "key_value_store" and name == storage.STORE_NAME:
                    candidate = await storage.new_private_project_store(self.caller, self.owner, self.username, chosen_name)
                else:
                    collection = getattr(self.caller, kind + "s")()
                    candidate = await collection.get_or_create(name=chosen_name)
        ident = self.owned(candidate).id
        resource = caller_resource(ident)
        return resource, self.owned(await resource.get(), expected_id=ident)


async def runtime_opens_project_store(backend):
    if isinstance(backend, storage.MemoryBackend):
        return True
    selection = backend.selection
    actor_id = runtime_actor_id()
    if not actor_id:
        return False
    for name in dict.fromkeys((storage.STORE_NAME, storage.actor_owned_store_name(storage.STORE_NAME))):
        if not name:
            continue
        try:
            info = await selection.runtime.key_value_store(selection.username + "~" + name).get()
        except Exception as error:
            if getattr(error, "status_code", None) == 403:
                continue
            raise
        if info is not None:
            return (info.user_id == selection.owner and info.id == backend.project_store_id
                    and getattr(info, "act_id", None) == actor_id)
        return False
    return False


async def require_private_project_store(backend):
    if isinstance(backend, storage.MemoryBackend):
        return True
    info = await backend.resource.get() if getattr(backend, "resource", None) else None
    if (not info or info.id != backend.project_store_id or info.user_id != backend.selection.owner
            or info.general_access != "RESTRICTED"):
        raise ValueError("This operation needs a Restricted project store. Review its sharing in Apify before continuing.")
    return True


QUEUE_CONFLICT = ("This project has conflicting revision queue grants. Pause project writes and use the account "
                  "owner's verified original queue. If both namespace reservations exist, verify which queue "
                  "contains the project's original receipts before removing the unused reservation.")


async def queue_binding(backend, name):
    import asyncio
    keys = [f"citebase-queue-binding.{name}.{slot}" for slot in ("original", "replacement")]
    confirmed = await backend.get(f"citebase-queue-binding.{name}.confirmed")
    if confirmed is not None:
        if (not isinstance(confirmed, dict) or type(confirmed.get("slot")) is not int or
                confirmed["slot"] not in (0, 1) or not isinstance(confirmed.get("id"), str) or
                not re.fullmatch(r"[a-zA-Z0-9]{5,80}", confirmed["id"])):
            raise ValueError(QUEUE_CONFLICT)
        ids = [None, None]
        ids[confirmed["slot"]] = confirmed["id"]
        return keys, ids, True
    ids = await asyncio.gather(*(backend.get(key) for key in keys))
    if any(value is not None and (not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9]{5,80}", value))
           for value in ids) or all(ids):
        raise ValueError(QUEUE_CONFLICT)
    return keys, ids, False


async def reserve_queue(backend, name, item, read_only):
    """A caller cannot start work on one alias while another starts work on its sibling."""
    keys, ids, confirmed = await queue_binding(backend, name)
    slot = 0 if item.name == name else 1
    if ids[1-slot] or (ids[slot] and ids[slot] != item.id):
        raise ValueError(QUEUE_CONFLICT)
    if not read_only and not confirmed:
        if not ids[slot]:
            await backend.set(keys[slot], item.id)
        _, after, _ = await queue_binding(backend, name)
        if after[slot] != item.id:
            raise ValueError(QUEUE_CONFLICT)
        # At most one slot can see its sibling absent after writing its own permanent claim.
        await backend.set(f"citebase-queue-binding.{name}.confirmed", {"slot": slot, "id": item.id})


async def visible_revision_queue(client, username, name, fallback):
    for alias in (name, fallback):
        try:
            info = await client.request_queue(username + "~" + alias).get()
        except Exception as error:
            if getattr(error, "status_code", None) != 403:
                raise
            continue
        if info:
            if info.name != alias:
                raise ValueError(QUEUE_CONFLICT)
            return info
    return None


async def run_revision_queue(backend, name):
    """Use the same binding when a normal Actor run writes its first legacy panel."""
    fallback = storage.actor_owned_store_name(name)
    bound = next((v for v in (await queue_binding(backend, name))[1] if v), None) if fallback else None
    if bound:
        queue = backend.client.request_queue(bound)
        item = await queue.get()
        if not item or item.id != bound or item.name not in (name, fallback):
            raise ValueError(QUEUE_CONFLICT)
    else:
        item = await visible_revision_queue(backend.client, "", name, fallback) if fallback else None
        if not item:
            item = await storage.open_named_store(backend.client.request_queues().get_or_create, name)
        queue = backend.client.request_queue(item.id)
    if fallback:
        await reserve_queue(backend, name, item, storage._read_only.get())
    return queue


class CallerBackend(storage.ApifyBackend):
    def __init__(self, selection, resource, ident, *, signed=False, read_only=False):
        super().__init__(None, selection.caller, signed_urls=signed, project_store_id=ident)
        self.selection = selection
        self.resource = resource
        self.read_only = read_only

    @property
    def child_client(self):
        return self.client

    async def _open_restricted(self, name):
        resource, info = await self.selection.resolve("key_value_store", name, create=not self.read_only)
        if info is None:
            return CallerBackend(self.selection, None, None, signed=True, read_only=True)
        if info.general_access == "FOLLOW_USER_SETTING" and not self.read_only:
            info = self.selection.owned(await resource.update(general_access="RESTRICTED"), expected_id=info.id)
        if info.general_access != "RESTRICTED":
            raise ValueError("Private storage access could not be verified. Set the dedicated store to Restricted in Apify.")
        return CallerBackend(self.selection, resource, info.id, signed=True, read_only=self.read_only)

    async def existing_private_store(self):
        if not self.read_only:
            raise ValueError("Reading existing private records requires a read-only project connection.")
        private = await self.private_store()
        return private if private.resource is not None else None

    async def revision_queue(self, name):
        fallback = storage.actor_owned_store_name(name)
        grant = (self.selection.batch or {}).get("grants", {}).get(name)
        bound = next((v for v in (await queue_binding(self, name))[1] if v), None) if fallback else None
        if bound:
            if grant and grant != bound:
                raise ValueError(QUEUE_CONFLICT)
            resource, item = await self.selection.resolve("request_queue", name, selected_id=bound,
                                                         create=not self.read_only)
            if item.name not in (name, fallback):
                raise ValueError(QUEUE_CONFLICT)
            await reserve_queue(self, name, item, self.read_only)
            return resource
        visible = await visible_revision_queue(self.selection.runtime, self.selection.username,
                                               name, fallback) if fallback else None
        if visible and grant and self.selection.owned(visible).id != grant:
            raise ValueError(QUEUE_CONFLICT)
        resource, item = await self.selection.resolve("request_queue", name,
                                                      selected_id=visible.id if visible else None,
                                                      create=not self.read_only)
        if item and fallback:
            await reserve_queue(self, name, item, self.read_only)
        return resource

    async def get(self, key):
        if self.resource is None:
            return None
        record = await self.resource.get_record(key)
        return record["value"] if record is not None else None

    async def set(self, key, value, content_type=None):
        if self.read_only:
            raise ValueError("This project operation only reads saved records.")
        if value is None:
            await self.delete(key)
        else:
            await self.resource.set_record(key, value, content_type=content_type)

    async def delete(self, key):
        if self.read_only:
            raise ValueError("This project operation only reads saved records.")
        await self.resource.delete_record(key)

    async def keys(self, prefix=""):
        if self.resource is None:
            return []
        start, keys = None, []
        while True:
            page = await self.resource.list_keys(limit=1000, exclusive_start_key=start, prefix=prefix or None)
            keys.extend(row.key for row in page.items if row.key.startswith(prefix))
            if not page.is_truncated:
                return keys
            if not page.next_exclusive_start_key or start == page.next_exclusive_start_key:
                raise ValueError("The account storage returned an incomplete key list.")
            start = page.next_exclusive_start_key

    async def public_url(self, key):
        from urllib.parse import parse_qs, urlsplit
        if self.resource is None:
            return None
        try:
            url = await self.resource.get_record_public_url(key)
            parts = urlsplit(url)
            if parts.scheme == "https" and parts.netloc == "api.apify.com":
                if not self.signed_urls or set(parse_qs(parts.query)) == {"signature"}:
                    return url
        except Exception:
            pass
        return None


@asynccontextmanager
async def for_caller(client, *, read_only=False):
    fixture = storage._fixture_backend
    if fixture is not None:
        backend = fixture
    else:
        owner, runtime = runtime_identity()
        batch = work_auth.batch_context()
        if not owner or (batch and batch["batch_owner"] != owner):
            raise ValueError("Citebase could not verify the signed-in project account.")
        # A verified Actor run opens its own named resources as "~name" under the Limited token.
        username = ""
        if not batch:
            user = await client.user().get()
            username = user.username if user and user.id == owner else None
            if not isinstance(username, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]+", username):
                raise ValueError("Citebase could not verify the signed-in project account.")
        selection = Selection(owner, username, runtime, client, batch)
        resource, info = await selection.resolve("key_value_store", storage.STORE_NAME,
                                                 selected_id=storage._project_store.get(), create=not read_only)
        if info is None and not read_only:
            raise ValueError("Choose an existing project in this account.")
        backend = CallerBackend(selection, resource, info.id if info else None, read_only=read_only)
    token = storage._caller_backend.set(backend)
    mode = storage._read_only.set(read_only)
    try:
        yield backend
    finally:
        storage._read_only.reset(mode)
        storage._caller_backend.reset(token)
