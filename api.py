"""
PDB data fetching and parsing.

All functions are pure async — they take a pdb_id string and return data.
Nothing here imports from other project modules.
"""

import asyncio
import json
import urllib.request

# ── GraphQL query ──────────────────────────────────────────────────────────

_RCSB_GQL_QUERY = """
{
  entry(entry_id: "%s") {
    polymer_entities {
      rcsb_polymer_entity { pdbx_description }
      entity_poly { type pdbx_seq_one_letter_code_can }
      polymer_entity_instances {
        rcsb_polymer_entity_instance_container_identifiers { auth_asym_id }
      }
    }
    nonpolymer_entities {
      nonpolymer_comp { chem_comp { name } }
      nonpolymer_entity_instances {
        rcsb_nonpolymer_entity_instance_container_identifiers { auth_asym_id }
      }
    }
  }
}
"""

# ── Parsers ────────────────────────────────────────────────────────────────


def _parse_pdbe_molecules(data: dict, pdb_id: str) -> list[dict]:
    """Parse the PDBe /molecules endpoint response into a flat chain list."""
    molecules = data.get(pdb_id) or data.get(pdb_id.upper()) or []
    chains = []
    for mol in molecules:
        mol_type = mol.get("molecule_type", "unknown")
        names = mol.get("molecule_name") or []
        name = names[0] if names else mol_type
        for auth_id in mol.get("chain_ids", []):
            chains.append(
                {
                    "auth_id": auth_id,
                    "type": mol_type,
                    "name": name,
                    "length": mol.get("length", 0),
                    "sequence": mol.get("sequence", ""),
                }
            )
    return chains


def _parse_rcsb_graphql(data: dict) -> list[dict]:
    """Parse the RCSB GraphQL response into a flat chain list."""
    entry = (data.get("data") or {}).get("entry") or {}
    chains = []
    for entity in entry.get("polymer_entities") or []:
        mol_type = (entity.get("entity_poly") or {}).get("type", "polypeptide(L)")
        name = (entity.get("rcsb_polymer_entity") or {}).get(
            "pdbx_description"
        ) or mol_type
        sequence = (entity.get("entity_poly") or {}).get(
            "pdbx_seq_one_letter_code_can"
        ) or ""
        for inst in entity.get("polymer_entity_instances") or []:
            auth_id = (
                inst.get("rcsb_polymer_entity_instance_container_identifiers") or {}
            ).get("auth_asym_id", "?")
            chains.append(
                {
                    "auth_id": auth_id,
                    "type": mol_type,
                    "name": name,
                    "length": len(sequence),
                    "sequence": sequence,
                }
            )
    for entity in entry.get("nonpolymer_entities") or []:
        name = ((entity.get("nonpolymer_comp") or {}).get("chem_comp") or {}).get(
            "name", "ligand"
        )
        for inst in entity.get("nonpolymer_entity_instances") or []:
            auth_id = (
                inst.get("rcsb_nonpolymer_entity_instance_container_identifiers") or {}
            ).get("auth_asym_id", "?")
            chains.append(
                {
                    "auth_id": auth_id,
                    "type": "bound",
                    "name": name,
                    "length": 0,
                    "sequence": "",
                }
            )
    return chains


# ── Fetch helpers ──────────────────────────────────────────────────────────

_HEADERS = {"User-Agent": "molstar-mcp/1.0"}


def _http_get(url: str) -> tuple[dict, str]:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw), raw[:300]


def _http_post_json(url: str, body: bytes) -> tuple[dict, str]:
    req = urllib.request.Request(
        url, data=body, headers={**_HEADERS, "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw), raw[:300]


# ── Public API ─────────────────────────────────────────────────────────────


async def fetch_seq_starts(pdb_id: str) -> dict[str, int]:
    """
    Return {auth_chain_id: first_auth_seq_id} for all chains via PDBe residue listing.
    Used to map author residue numbers to sequence indices for amino acid lookup.
    Returns {} on failure.
    """
    url = f"https://www.ebi.ac.uk/pdbe/api/pdb/entry/residue_listing/{pdb_id}/"
    try:
        data, _ = await asyncio.to_thread(_http_get, url)
        entry = data.get(pdb_id) or data.get(pdb_id.upper()) or {}
        starts: dict[str, int] = {}
        for mol in entry.get("molecules", []):
            for chain in mol.get("chains", []):
                cid = chain.get("chain_id")
                residues = chain.get("residues", [])
                if residues and cid not in starts:
                    first = residues[0].get("author_residue_number")
                    if first is not None:
                        starts[cid] = first
        return starts
    except Exception:
        return {}


async def fetch_chain_info(pdb_id: str) -> tuple[list[dict], str]:
    """
    Fetch molecule/chain metadata for a PDB entry.

    Tries PDBe REST first, then RCSB GraphQL as fallback.
    Enriches each chain dict with seq_auth_beg (first auth residue number)
    for amino acid label lookup.

    Returns (chains, error_message). chains is [] only on total failure.
    """

    async def _enrich(chains: list[dict]) -> list[dict]:
        seq_starts = await fetch_seq_starts(pdb_id)
        for c in chains:
            c["seq_auth_beg"] = seq_starts.get(c["auth_id"])
        return chains

    # Try PDBe
    pdbe_err = "not attempted"
    try:
        data, preview = await asyncio.to_thread(
            _http_get, f"https://www.ebi.ac.uk/pdbe/api/pdb/entry/molecules/{pdb_id}"
        )
        chains = _parse_pdbe_molecules(data, pdb_id)
        if chains:
            return await _enrich(chains), ""
        pdbe_err = (
            f"no chains parsed — keys={list(data.keys())[:6]} | preview={preview}"
        )
    except Exception as e:
        pdbe_err = str(e)

    # Try RCSB GraphQL
    rcsb_err = "not attempted"
    try:
        body = json.dumps({"query": _RCSB_GQL_QUERY % pdb_id.upper()}).encode()
        data, preview = await asyncio.to_thread(
            _http_post_json, "https://data.rcsb.org/graphql", body
        )
        chains = _parse_rcsb_graphql(data)
        if chains:
            return await _enrich(chains), ""
        rcsb_err = f"no chains parsed — preview={preview}"
    except Exception as e:
        rcsb_err = str(e)

    return [], f"PDBe: {pdbe_err} | RCSB GraphQL: {rcsb_err}"
