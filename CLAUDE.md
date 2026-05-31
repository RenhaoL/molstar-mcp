# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`molstar-mcp` is a local MCP server that lets Claude Desktop drive a [Mol*](https://molstar.org) 3D protein viewer. One Python process runs two servers on the same asyncio event loop:

- **MCP server (stdio):** Claude Desktop connects here and calls tools
- **WebSocket server (`ws://localhost:8765`):** `index.html` connects here and redraws on each push

Tools mutate `STATE`, which `build_scene()` converts into a complete MolViewSpec (MVSJ) JSON that is broadcast to all connected browser clients.

## Setup

**Python 3.12 required.** Use conda/mamba:

```bash
conda create -n molstar-mcp python=3.12
conda activate molstar-mcp
pip install -e .
```

## Running

```bash
python server.py   # standalone test (WebSocket only; MCP tools won't fire without Claude Desktop)
```

In normal use, Claude Desktop launches `server.py` automatically. Wire it up via Settings → Developer → Edit Config:

```json
{
  "mcpServers": {
    "molstar": {
      "command": "/full/path/to/conda/envs/molstar-mcp/bin/python",
      "args": ["/full/path/to/molstar-mcp/server.py"]
    }
  }
}
```

Then open `index.html` directly in a browser (it connects to `ws://localhost:8765`).

## Architecture Pattern for Adding Tools

Every tool follows this exact pattern — do not deviate:

1. Mutate `STATE` (the shared dict at module level)
2. Call `await broadcast()` — this calls `build_scene()` and pushes MVSJ JSON to all viewers
3. Return a short confirmation string

`build_scene()` always rebuilds the **complete** scene from `STATE` from scratch. There is no diffing or patching. Keep `build_scene()` as the single source of truth for the rendered scene.

## MVS API Gotchas

- Water selector string is `"water"` — verify against molviewspec docs if it stops working
- Residue range selectors use keys: `label_asym_id`, `beg_label_seq_id`, `end_label_seq_id`
- PDB structures are fetched from EBI: `https://www.ebi.ac.uk/pdbe/entry-files/download/{pdb_id}_updated.cif`
- `mcp.run_stdio_async()` may not exist in all `mcp` SDK versions — check SDK docs if it errors

## File Notes

- `index.html` lives at the project root (README says `viewer/index.html` — that's outdated)
- No tests, no CI — this is a prototype; validate manually with a running viewer
