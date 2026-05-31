"""
MCP tool definitions.

All @mcp.tool() functions live here. Each tool mutates STATE and calls
broadcast() to push the updated scene to connected viewers.
"""

import asyncio
import json

from mcp.server.fastmcp import FastMCP

import api
from scene import build_scene
from state import CLIENTS, STATE, lookup_aa

mcp = FastMCP("molstar")


# ── WebSocket helpers ──────────────────────────────────────────────────────


async def broadcast() -> None:
    """Rebuild the scene and push it to all connected viewers."""
    if CLIENTS:
        scene = build_scene()
        await asyncio.gather(*(ws.send(scene) for ws in CLIENTS))


async def send_control(message: dict) -> None:
    """Send a non-scene control message (spin, screenshot, etc.) to all viewers."""
    if CLIENTS:
        data = json.dumps(message)
        await asyncio.gather(*(ws.send(data) for ws in CLIENTS))


# ── Structure loading ──────────────────────────────────────────────────────


@mcp.tool()
async def load_protein(pdb_id: str) -> str:
    """Load a protein structure by PDB ID (e.g. '1cbs'). Auto-opens the viewer."""
    from server import open_viewer

    pid = pdb_id.lower()
    STATE.update(
        pdb_id=pid,
        show_water=True,
        representation="cartoon",
        color_scheme="Chainbow",
        background="white",
        highlights=[],
        distances=[],
        labels=[],
        chains=[],
        hidden_chains=[],
    )
    chains, _ = await api.fetch_chain_info(pid)
    STATE["chains"] = chains

    await broadcast()
    if not CLIENTS:
        open_viewer()
        return f"Loaded {pdb_id}. Opening viewer in your browser — it will connect automatically."
    return f"Loaded {pdb_id}"


# ── Structure info ─────────────────────────────────────────────────────────


@mcp.tool()
async def get_structure_info() -> str:
    """
    Return chain composition and sequence information for the currently loaded structure.
    Use this to answer questions about how many chains there are, what molecules are present,
    sequence lengths, and amino acid sequences.
    """
    if not STATE["pdb_id"]:
        return "No structure loaded."

    chains = STATE["chains"]
    if not chains:
        chains, err = await api.fetch_chain_info(STATE["pdb_id"])
        STATE["chains"] = chains
        if not chains:
            return f"Could not fetch chain info for {STATE['pdb_id'].upper()}.\nDiagnostic: {err}"

    lines = [f"Structure: {STATE['pdb_id'].upper()}", ""]
    for c in chains:
        tag = "  [hidden]" if c["auth_id"] in STATE["hidden_chains"] else ""
        line = f"Chain {c['auth_id']}{tag} — {c['type']}: {c['name']}"
        if c["length"]:
            line += f"  ({c['length']} residues)"
        lines.append(line)
        if c["sequence"]:
            seq = c["sequence"]
            lines.append(f"  {seq[:80]}{'…' if len(seq) > 80 else ''}")

    return "\n".join(lines)


# ── Chain visibility ───────────────────────────────────────────────────────


@mcp.tool()
async def hide_chain(chain_id: str) -> str:
    """
    Hide a chain by its author chain ID (e.g. 'A', 'B').
    Call get_structure_info first to see available chain IDs.
    """
    cid = chain_id.upper()
    if cid not in STATE["hidden_chains"]:
        STATE["hidden_chains"].append(cid)

    # Chain metadata is required for per-chain rendering; fetch if missing.
    if not STATE["chains"] and STATE["pdb_id"]:
        chains, err = await api.fetch_chain_info(STATE["pdb_id"])
        STATE["chains"] = chains
        if not chains:
            return (
                f"Chain {cid} marked hidden, but could not fetch chain list "
                f"so the viewer cannot hide it yet.\nDiagnostic: {err}"
            )

    await broadcast()
    return f"Chain {cid} hidden"


@mcp.tool()
async def show_chain(chain_id: str) -> str:
    """Show a previously hidden chain."""
    cid = chain_id.upper()
    STATE["hidden_chains"] = [c for c in STATE["hidden_chains"] if c != cid]
    await broadcast()
    return f"Chain {cid} shown"


@mcp.tool()
async def show_all_chains() -> str:
    """Show all chains (undo any hide_chain calls)."""
    STATE["hidden_chains"] = []
    await broadcast()
    return "All chains shown"


# ── Representation ─────────────────────────────────────────────────────────


@mcp.tool()
async def set_representation(representation_type: str) -> str:
    """
    Change the polymer representation.
    Valid options: 'cartoon', 'ball_and_stick', 'spacefill', 'surface', 'putty'.
    """
    valid = {"cartoon", "ball_and_stick", "spacefill", "surface", "putty"}
    if representation_type not in valid:
        return f"Invalid type '{representation_type}'. Choose from: {', '.join(sorted(valid))}"
    STATE["representation"] = representation_type
    await broadcast()
    return f"Representation set to '{representation_type}'"


# ── Color ──────────────────────────────────────────────────────────────────


@mcp.tool()
async def color_by(scheme: str) -> str:
    """
    Color the polymer by a named scheme or solid color.

    Built-in schemes: 'ElementSymbol', 'Chainbow', 'SecondaryStructure', 'ResidueName'.
    Or any CSS color name (e.g. 'steelblue') or hex string (e.g. '#ff6600').
    """
    STATE["color_scheme"] = scheme
    await broadcast()
    return f"Coloring by '{scheme}'"


@mcp.tool()
async def set_background(color: str) -> str:
    """Set the viewer background color. Accepts CSS names or hex, e.g. 'black', '#1a1a2e'."""
    STATE["background"] = color
    await broadcast()
    return f"Background set to '{color}'"


# ── Water ──────────────────────────────────────────────────────────────────


@mcp.tool()
async def remove_water() -> str:
    """Hide water molecules."""
    STATE["show_water"] = False
    await broadcast()
    return "Water hidden"


@mcp.tool()
async def show_water() -> str:
    """Show water molecules."""
    STATE["show_water"] = True
    await broadcast()
    return "Water shown"


# ── Highlights ─────────────────────────────────────────────────────────────


@mcp.tool()
async def highlight_residues(
    chain: str,
    start: int,
    end: int,
    color: str = "blue",
    representation: str = "ball_and_stick",
) -> str:
    """
    Highlight a single CONTIGUOUS residue range (e.g. an alpha-helix from 10 to 40).
    Only use this when you have a start and end of a continuous stretch.
    For any list of specific residue numbers — even if they happen to be close together —
    use highlight_residue_list instead (one call, no looping).

    chain: author chain ID, e.g. 'A'
    start/end: author residue sequence numbers (inclusive)
    color: any CSS color name or hex string (default 'blue')
    representation: 'ball_and_stick', 'spacefill', 'cartoon', etc. (default 'ball_and_stick')
    """
    selector: dict = {
        "auth_asym_id": chain.upper(),
        "beg_auth_seq_id": start,
        "end_auth_seq_id": end,
    }
    STATE["highlights"].append(
        {"selector": selector, "color": color, "representation": representation}
    )
    await broadcast()
    return f"Highlighted {chain}:{start}-{end} in {color} ({representation})"


@mcp.tool()
async def highlight_residue_list(
    residues: list[int],
    chain: str = "",
    color: str = "blue",
    representation: str = "ball_and_stick",
) -> str:
    """
    Highlight specific residues by position number. Use this whenever the user gives
    a list of residue numbers (mutations, active site residues, epitopes, etc.).
    All residues are highlighted in a single call — do NOT loop over this tool.

    residues: list of author residue numbers, e.g. [339, 356, 371, 403]
    chain: author chain ID (e.g. 'C'). Leave empty to match across all chains.
    color: any CSS color name or hex string (default 'blue')
    representation: 'ball_and_stick', 'spacefill', 'cartoon', etc. (default 'ball_and_stick')
    """
    for res in residues:
        selector: dict = {"auth_seq_id": res}
        if chain:
            selector["auth_asym_id"] = chain.upper()
        STATE["highlights"].append(
            {"selector": selector, "color": color, "representation": representation}
        )
    await broadcast()
    return f"Highlighted {len(residues)} residues in {color} on chain {chain or 'all'}"


@mcp.tool()
async def clear_highlights() -> str:
    """Remove all residue highlights."""
    STATE["highlights"] = []
    await broadcast()
    return "All highlights cleared"


# ── Distance measurements ──────────────────────────────────────────────────


@mcp.tool()
async def measure_distance(
    chain1: str,
    residue1: int,
    chain2: str,
    residue2: int,
    color: str = "yellow",
    label_size: float = 3.0,
) -> str:
    """
    Draw a dashed distance line between two residues and display the distance.
    Uses the residue centroid as the anchor point.
    Multiple calls stack — each adds a new measurement.

    chain1/chain2: author chain IDs, e.g. 'A'
    residue1/residue2: author residue sequence numbers
    color: line and label color (default 'yellow')
    label_size: font size of the distance label (default 3.0)
    """
    STATE["distances"].append(
        {
            "chain1": chain1,
            "res1": residue1,
            "chain2": chain2,
            "res2": residue2,
            "color": color,
            "label_size": label_size,
        }
    )
    await broadcast()
    return f"Distance measurement added: {chain1}:{residue1} ↔ {chain2}:{residue2}"


@mcp.tool()
async def clear_distances() -> str:
    """Remove all distance measurements."""
    STATE["distances"] = []
    await broadcast()
    return "All distance measurements cleared"


# ── Labels ─────────────────────────────────────────────────────────────────


@mcp.tool()
async def label_residue(
    residue: int,
    text: str = "",
    chain: str = "",
    color: str = "white",
) -> str:
    """
    Add a 3D text label to a residue in the viewer.
    Multiple calls stack — each adds a new label.

    residue: author residue number
    text: label string. If omitted, auto-generated as '{one_letter_aa}_{residue}' (e.g. 'N_501').
    chain: author chain ID (optional — leave empty to label across all chains)
    color: label text color, any CSS color (default 'white')
    """
    if not text:
        aa = lookup_aa(chain.upper(), residue) if chain else ""
        text = f"{aa}_{residue}" if aa else str(residue)
    STATE["labels"].append(
        {
            "chain": chain.upper() if chain else "",
            "residue": residue,
            "text": text,
            "color": color,
        }
    )
    await broadcast()
    return f"Label '{text}' added at residue {chain or '*'}:{residue}"


@mcp.tool()
async def clear_labels() -> str:
    """Remove all residue labels."""
    STATE["labels"] = []
    await broadcast()
    return "All labels cleared"


# ── Save scene ─────────────────────────────────────────────────────────────


@mcp.tool()
async def save_scene() -> str:
    """
    Save the current view — including hidden chains, highlights, labels, and distance
    measurements — as a .mvsj scene file. The browser will download it automatically.
    The file can be reloaded into the Mol* viewer to restore the exact same appearance.
    Use this when the user says 'save the structure', 'save the view', or 'export the scene'.
    """
    if not STATE["pdb_id"]:
        return "No structure loaded."
    filename = f"{STATE['pdb_id']}_scene.mvsj"
    await send_control(
        {
            "type": "control",
            "action": "download_text",
            "content": build_scene(),
            "filename": filename,
        }
    )
    return f"Scene saved as {filename}"


# ── Viewer controls ────────────────────────────────────────────────────────


@mcp.tool()
async def start_spin() -> str:
    """Start continuously rotating the structure in the viewer. Pair with record_video for a movie."""
    await send_control({"type": "control", "action": "spin_start"})
    return "Spinning started"


@mcp.tool()
async def stop_spin() -> str:
    """Stop the spinning rotation."""
    await send_control({"type": "control", "action": "spin_stop"})
    return "Spinning stopped"


@mcp.tool()
async def take_screenshot() -> str:
    """Trigger the viewer to download the current view as a PNG image."""
    await send_control({"type": "control", "action": "screenshot"})
    return "Screenshot download triggered in the browser"


@mcp.tool()
async def record_video(duration_seconds: int = 5) -> str:
    """
    Record the viewer for the given number of seconds and download as a WebM video.
    Call start_spin first for a rotating-structure movie.

    duration_seconds: recording length (default 5, max 60)
    """
    duration_seconds = max(1, min(duration_seconds, 60))
    await send_control(
        {
            "type": "control",
            "action": "record_start",
            "duration_ms": duration_seconds * 1000,
        }
    )
    return (
        f"Recording {duration_seconds}s video — the browser will download it when done"
    )


# ── Debug ──────────────────────────────────────────────────────────────────


@mcp.tool()
async def get_scene_json() -> str:
    """Return the current MVS JSON being sent to the viewer. Use to diagnose rendering issues."""
    return build_scene()


# ── Reset ──────────────────────────────────────────────────────────────────


@mcp.tool()
async def reset_view() -> str:
    """Reset representation, colors, highlights, distances, and labels to defaults (keeps loaded structure)."""
    STATE.update(
        show_water=True,
        representation="cartoon",
        color_scheme="Chainbow",
        background="white",
        highlights=[],
        distances=[],
        labels=[],
        hidden_chains=[],
    )
    await broadcast()
    return "View reset to defaults"
