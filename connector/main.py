"""Apify entry point: runs the Citebase MCP server in Standby mode."""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn  # noqa: E402
from apify import Actor  # noqa: E402

from server import build_app  # noqa: E402

BATCH_MESSAGE = ("Citebase is an MCP server. Start it in Standby mode and connect your AI assistant to "
                 "<standby URL>/mcp with your Apify token. Nothing to do in a normal run.")


async def main() -> None:
    async with Actor:
        if os.environ.get("APIFY_META_ORIGIN") != "STANDBY":
            Actor.log.info(BATCH_MESSAGE)
            await Actor.set_value("OUTPUT", {"message": BATCH_MESSAGE})
            return
        port = int(os.environ.get("ACTOR_STANDBY_PORT") or os.environ.get("ACTOR_WEB_SERVER_PORT") or 8080)
        Actor.log.info(f"Citebase MCP server listening on port {port}")
        server = uvicorn.Server(uvicorn.Config(build_app(), host="0.0.0.0", port=port, log_level="info",
                                               timeout_graceful_shutdown=5))
        await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
