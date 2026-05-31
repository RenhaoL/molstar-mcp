"""
Mol* MCP server — entry point.

Starts two servers on the same asyncio event loop:
  - MCP server (stdio)      — Claude Desktop connects and calls tools
  - WebSocket server (:8765) — index.html connects and receives scene updates

Run standalone (WebSocket only, for browser testing):
    python server.py

In normal use Claude Desktop launches this automatically. See README.md for
Claude Desktop wiring instructions.
"""

import asyncio
import pathlib
import subprocess
import sys

import websockets

from scene import build_scene
from state import CLIENTS
from tools import mcp


# ── Browser launcher ───────────────────────────────────────────────────────


def open_viewer() -> None:
    """Open index.html in the default browser using the OS-level open command.

    webbrowser.open() is unreliable when the process is launched headlessly by
    Claude Desktop, so we call the platform open command directly instead.
    """
    html_path = pathlib.Path(__file__).parent / "index.html"
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(html_path)])
    elif sys.platform == "win32":
        subprocess.Popen(["start", str(html_path)], shell=True)
    else:
        subprocess.Popen(["xdg-open", str(html_path)])


# ── WebSocket handler ──────────────────────────────────────────────────────


async def ws_handler(ws) -> None:
    """Register a new viewer, send it the current scene, and wait for disconnect."""
    CLIENTS.add(ws)
    try:
        await ws.send(build_scene())
        await ws.wait_closed()
    finally:
        CLIENTS.discard(ws)


# ── Main ───────────────────────────────────────────────────────────────────


async def main() -> None:
    async with websockets.serve(ws_handler, "localhost", 8765):
        await mcp.run_stdio_async()


if __name__ == "__main__":
    asyncio.run(main())
