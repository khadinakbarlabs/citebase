"""Account-bound project work for Apify's managed MCP input interface."""
import re

import runner
import storage
import work_auth

PRIVATE_TOOLS = {"project_work", "get_history", "save_results"}
SCHEDULE_WRITES = {"schedule_apply", "schedule_pause", "schedule_resume"}
INTERACTIVE_ORIGINS = {"MCP", "API", "WEB", "CLI"}
GRANTS = {"private_store_id": storage.PRIVATE_STORE, "revisions_queue_id": "citebase-work-revisions-v1"}
INPUT_HELP = "Use call-actor with the tool and its argument object in the encrypted private_request field. Leave arguments empty."
ACCOUNT_HELP = "Start this private request from your signed-in Apify account."
STORAGE_HELP = "Citebase could not verify private result storage. Check access and set the dedicated result store to Restricted in Apify."
RESULT_HELP = "Read the private_result record with the signed-in get-key-value-store-record tool."
REVIEW_HELP = "Check the saved project and private result before retrying. The previous attempt may have made a change."


async def verified_run(actor, data):
    config = actor.configuration
    tool = data.get("tool")
    if (not isinstance(tool, str) or tool not in PRIVATE_TOOLS or not isinstance(data.get("private_request"), dict)
            or data.get("arguments") not in (None, {}) or set(data) - {"tool", "private_request", "arguments", "project_store_id", *GRANTS}):
        raise ValueError(INPUT_HELP)
    for field in GRANTS:
        if field in data and (not isinstance(data[field], str) or not re.fullmatch(r"[a-zA-Z0-9]{5,80}", data[field])):
            raise ValueError(INPUT_HELP)
    if not actor.is_at_home() or not all((config.actor_id, config.actor_run_id, config.user_id, config.token)):
        raise ValueError(ACCOUNT_HELP)
    raw = await actor.get_value(config.input_key)
    ciphertext = raw.get("private_request") if isinstance(raw, dict) else None
    if not isinstance(ciphertext, str) or not ciphertext.startswith("ENCRYPTED_JSON:"):
        raise ValueError(INPUT_HELP)
    client = work_auth.new_client(config.token, api_url=config.api_base_url)
    run = await client.run(config.actor_run_id).get()
    if (not run or run.id != config.actor_run_id or run.act_id != config.actor_id or run.user_id != config.user_id
            or run.default_key_value_store_id != config.default_key_value_store_id or run.meta.origin not in INTERACTIVE_ORIGINS):
        raise ValueError(ACCOUNT_HELP)
    return client, run


async def result_store(client, run):
    # A named store is independent of the run's default stores and their sharing settings.
    if not re.fullmatch(r"[a-zA-Z0-9]{5,30}", run.act_id):
        raise ValueError(STORAGE_HELP)
    name = "citebase-mcp-results-" + run.act_id.lower()
    info = await client.key_value_stores().get_or_create(name=name)
    if not info or not info.id or info.id == run.default_key_value_store_id or info.user_id != run.user_id or info.name != name:
        raise ValueError(STORAGE_HELP)
    resource = client.key_value_store(info.id)
    if info.general_access == "FOLLOW_USER_SETTING":
        await resource.update(general_access="RESTRICTED")
    elif info.general_access != "RESTRICTED":
        raise ValueError(STORAGE_HELP)
    current = await resource.get()
    if (not current or current.id != info.id or current.user_id != run.user_id
            or current.name != name or current.general_access != "RESTRICTED"):
        raise ValueError(STORAGE_HELP)
    return resource, current


async def dispatch(client, tool, args, data, receipt_store):
    if tool == "project_work" and args.get("operation") in SCHEDULE_WRITES:
        raise ValueError("Use the signed-in dashboard to apply, pause or resume this schedule with your schedule permissions.")
    grants = {name: data[field] for field, name in GRANTS.items() if data.get(field)}
    with work_auth.batch_caller(client, owner=receipt_store.user_id, grants=grants), storage.project_store_grant(data.get("project_store_id")):
        async with work_auth.legacy_scope(tool, args):
            if tool == "save_results" and not args.get("check_only"):
                from work_storage import require_private_project_store
                await require_private_project_store(await storage.get_backend())
            return await runner.run_tool(tool, args)


async def private_record(client, run, data):
    resource, info = await result_store(client, run)
    key = "result." + run.id
    pointer = {"private_result": {"store_id": info.id, "key": key}}
    existing = await resource.get_record(key)
    if existing is not None:
        record = existing.get("value")
        if isinstance(record, dict) and type(record.get("ok")) is bool:
            return pointer, record["ok"]
        return pointer, False
    # A resumed process must never repeat a write with an unknown outcome.
    await resource.set_record(key, {"status": "started", "advice": REVIEW_HELP})
    try:
        result = await dispatch(client, data["tool"], data["private_request"], data, info)
        record = {"ok": True, "result": result}
    except ValueError as error:
        record = {"ok": False, "error": str(error)}
    except Exception as error:
        reason = ("This run lacks the storage or account permissions for that operation. Use the signed-in dashboard."
                  if getattr(error, "status_code", None) in (401, 403) else REVIEW_HELP)
        record = {"ok": False, "error": reason}
    await resource.set_record(key, record)
    return pointer, record["ok"]


async def run_once(actor, data):
    """Only immutable platform start metadata admits work here. Default outputs contain a locator."""
    public_error = None
    pointer = None
    try:
        client, run = await verified_run(actor, data)
        pointer, ok = await private_record(client, run, data)
        if not ok:
            public_error = RESULT_HELP + " " + REVIEW_HELP
    except ValueError as error:
        public_error = str(error) if str(error) in (INPUT_HELP, ACCOUNT_HELP, STORAGE_HELP) else REVIEW_HELP
    except Exception:
        public_error = STORAGE_HELP + " " + REVIEW_HELP
    # Unknown tool names and private validation messages must never enter the public run log.
    selected = data.get("tool")
    tool = selected if isinstance(selected, str) and selected in PRIVATE_TOOLS else "project_work"
    if pointer is not None:
        await actor.set_value("OUTPUT", pointer)
    await actor.push_data({"tool": tool, "ok": public_error is None, "result": pointer, "error": public_error})
    if public_error:
        await actor.fail(status_message=public_error[:200])
        return
    await actor.set_status_message(RESULT_HELP)
