"""
MVS scene builder.

build_scene() reads STATE and produces a complete MolViewSpec JSON string
that is broadcast to connected viewers on every state change.
"""

from molviewspec import create_builder

from state import POLYMER_TYPES, STATE

# Distinct CSS colors assigned to polymer chains when rendered individually.
# All are valid in MVS v1 (plain CSS named colors — no scheme names).
_CHAIN_PALETTE = [
    "cornflowerblue",
    "salmon",
    "mediumseagreen",
    "goldenrod",
    "orchid",
    "tomato",
    "steelblue",
    "sandybrown",
    "mediumturquoise",
    "indianred",
]


def build_scene() -> str:
    """Rebuild the complete MVS scene from STATE and return it as a JSON string."""
    b = create_builder()
    b.canvas(background_color=STATE["background"])

    if not STATE["pdb_id"]:
        return b.get_state().model_dump_json(exclude_none=True)

    url = (
        f"https://www.ebi.ac.uk/pdbe/entry-files/download/{STATE['pdb_id']}_updated.cif"
    )
    s = b.download(url=url).parse(format="mmcif").model_structure()

    hidden = set(STATE["hidden_chains"])
    chains = STATE["chains"]

    # Determine the base polymer color:
    #   None       → use per-chain palette (distinct colors, no highlights active)
    #   "lightgray" → gray base (highlights are active, so only highlights carry color)
    #   other str  → explicit color chosen by the user via color_by()
    if STATE["highlights"]:
        base_color: str | None = "lightgray"
    elif STATE["color_scheme"] == "lightgray":
        base_color = None  # sentinel: assign palette colors per chain
    else:
        base_color = STATE["color_scheme"]

    if chains:
        # Per-chain rendering: distinct palette colors per chain, enables hide_chain.
        # Falls back to bulk only when chain metadata is unavailable.
        _render_per_chain(s, chains, hidden, base_color)
    else:
        _render_bulk(s, base_color or "lightgray")

    _render_highlights(s)
    _render_primitives(s)

    return b.get_state().model_dump_json(exclude_none=True)


# ── Private rendering helpers ──────────────────────────────────────────────


def _render_per_chain(s, chains: list, hidden: set, base_color: str) -> None:
    """Render each visible chain individually (used when chains are hidden)."""
    rendered: set = set()
    polymer_chain_ids = {c["auth_id"] for c in chains if c["type"] in POLYMER_TYPES}
    palette_idx = 0  # cycles through _CHAIN_PALETTE for polymer chains

    for c in chains:
        cid = c["auth_id"]
        if cid in hidden or cid in rendered:
            continue
        # Skip non-polymer entries for chains already covered as polymer
        # (avoids duplicate ball-and-stick overlay on the same chain).
        if c["type"] not in POLYMER_TYPES and cid in polymer_chain_ids:
            continue

        rendered.add(cid)
        sel = {"auth_asym_id": cid}
        mol_type = c["type"]

        if mol_type in POLYMER_TYPES:
            # None sentinel → assign palette color; any string → use it directly
            color = (
                _CHAIN_PALETTE[palette_idx % len(_CHAIN_PALETTE)]
                if base_color is None
                else base_color
            )
            palette_idx += 1
            s.component(selector=sel).representation(
                type=STATE["representation"]
            ).color(color=color)
        elif mol_type == "water":
            if STATE["show_water"]:
                s.component(selector=sel).representation(type="ball_and_stick")
        else:
            s.component(selector=sel).representation(type="ball_and_stick")


def _render_bulk(s, base_color: str) -> None:
    """Render using MVS bulk selectors (faster; used when no chains are hidden)."""
    s.component(selector="polymer").representation(type=STATE["representation"]).color(
        color=base_color
    )
    s.component(selector="ligand").representation(type="ball_and_stick")
    if STATE["show_water"]:
        s.component(selector="water").representation(type="ball_and_stick")


def _render_highlights(s) -> None:
    for h in STATE["highlights"]:
        try:
            (
                s.component(selector=h["selector"])
                .representation(type=h.get("representation", "ball_and_stick"))
                .color(color=h["color"])
            )
        except Exception:
            pass  # malformed selector — skip silently


def _render_primitives(s) -> None:
    if not STATE["distances"] and not STATE["labels"]:
        return

    # Must be s.primitives() (child of the structure node) so that
    # ComponentExpression selectors can resolve to actual atoms.
    prims = s.primitives()

    for d in STATE["distances"]:
        prims.distance(
            start={"auth_asym_id": d["chain1"], "auth_seq_id": d["res1"]},
            end={"auth_asym_id": d["chain2"], "auth_seq_id": d["res2"]},
            color=d.get("color", "yellow"),
            label_size=d.get("label_size", 3.0),
        )

    for lbl in STATE["labels"]:
        pos: dict = {"auth_seq_id": lbl["residue"]}
        if lbl.get("chain"):
            pos["auth_asym_id"] = lbl["chain"]
        prims.label(
            position=pos,
            text=lbl["text"],
            label_color=lbl.get("color", "white"),
        )
