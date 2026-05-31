"""
Shared mutable state and helpers.

Every module that needs to read or write the current scene imports STATE and
CLIENTS from here. Nothing in this module imports from other project modules,
so it can never create circular dependencies.
"""

# ── Scene state ────────────────────────────────────────────────────────────

STATE: dict = {
    "pdb_id": None,
    "show_water": True,
    "representation": "cartoon",  # polymer representation type
    "color_scheme": "lightgray",  # CSS color or hex only — MVS v1.8 scheme names not supported by molstar 5.x
    "background": "white",
    "highlights": [],  # [{selector: dict (auth_* keys), color, representation}]
    "distances": [],  # [{chain1, res1, chain2, res2, color, label_size}]
    "labels": [],  # [{chain, residue, text, color}]
    # populated by load_protein via API fetch:
    "chains": [],  # [{auth_id, type, name, length, sequence, seq_auth_beg}]
    "hidden_chains": [],  # auth_asym_id values currently hidden
}

# Connected WebSocket viewer clients
CLIENTS: set = set()

# ── Constants ──────────────────────────────────────────────────────────────

# molecule_type values from PDBe API that represent polymer chains
POLYMER_TYPES: frozenset = frozenset(
    {
        "polypeptide(L)",
        "polypeptide(D)",
        "polyribonucleotide",
        "polydeoxyribonucleotide",
        "polydeoxyribonucleotide/polyribonucleotide hybrid",
        "cyclic-pseudo-peptide",
        "other",
    }
)

# ── Helpers ────────────────────────────────────────────────────────────────


def lookup_aa(chain_id: str, residue: int) -> str:
    """
    Return the one-letter amino acid code for the given auth chain / residue number.
    Returns '' if the chain sequence or seq_auth_beg is not available.
    """
    for c in STATE["chains"]:
        if (
            c["auth_id"] == chain_id
            and c.get("seq_auth_beg") is not None
            and c.get("sequence")
        ):
            idx = residue - c["seq_auth_beg"]
            if 0 <= idx < len(c["sequence"]):
                return c["sequence"][idx]
    return ""
