"""Apify entry point: runs the Citebase MCP server in Standby mode."""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn  # noqa: E402
from apify import Actor  # noqa: E402

import tools  # noqa: E402
from server import build_app  # noqa: E402


async def run_once() -> None:
    """Normal run: execute one Citebase tool and return its result (this is what mcp.apify.com calls)."""
    data = await Actor.get_input() or {}
    tool = str(data.get("tool") or "get_playbook")
    args = data.get("arguments") if isinstance(data.get("arguments"), dict) else {}
    try:
        result = await asyncio.to_thread(tools.dispatch, tool, args)
    except ValueError as err:  # bad input: say what to fix, and end the run honestly as failed
        await Actor.push_data({"tool": tool, "ok": False, "result": None, "error": str(err)})
        await Actor.fail(status_message=str(err)[:200])
        return
    await Actor.push_data({"tool": tool, "ok": True, "result": result, "error": None})
    await Actor.set_value("OUTPUT", result)
    await Actor.set_status_message(f"{tool}: done")


async def main() -> None:
    async with Actor:
        if os.environ.get("APIFY_META_ORIGIN") != "STANDBY":
            await run_once()
            return
        port = int(os.environ.get("ACTOR_STANDBY_PORT") or os.environ.get("ACTOR_WEB_SERVER_PORT") or 8080)
        Actor.log.info(f"Citebase MCP server listening on port {port}")
        server = uvicorn.Server(uvicorn.Config(build_app(), host="0.0.0.0", port=port, log_level="info",
                                               timeout_graceful_shutdown=5))
        await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
