"""Which bridge goes with which player ship.

The mode-agnostic answer to "the player is flying <ship>; load which bridge?"
for any game mode that does not dictate one. Campaign and tutorial missions
call LoadBridge.Load("<literal>") themselves and never come here (override
by construction). QuickBattle consults it through install_quickbattle_hook.

Spec: docs/superpowers/specs/2026-09-16-ship-bridge-matrix-design.md

Three derived, never-persisted views -- the bridge registry, the ship
universe, display labels -- and one persisted thing, BridgePins over
bridges.json. Every path is resolved at call time (engine/paths.py rule).
"""
from __future__ import annotations

import re
from collections import namedtuple
from pathlib import Path
from typing import Optional

from engine import dev_mode, mods, paths

BridgeInfo = namedtuple("BridgeInfo", "script_name label")

# BC's own labels: the "Player Bridge" window buttons were the TGL strings
# "Galaxy" and "Sovereign" (data/TGL/QuickBattle/QuickBattle.tgl). The set
# folder names (DBridge / EBridge) never reach the UI.
STOCK_BRIDGES: tuple = (
    BridgeInfo("GalaxyBridge", "Galaxy"),
    BridgeInfo("SovereignBridge", "Sovereign"),
)

_SHIP_KEY_RE = re.compile(r"^ships/([^/]+)\.py$")

_cache: dict = {}
_cache_index = None


def clear_caches() -> None:
    """Tests only. Production memoises for the life of the process: the mod
    index is built once at boot and the SDK tree does not change mid-run."""
    global _cache_index
    _cache.clear()
    _cache_index = None


def _cache_for_current_index() -> dict:
    """The memo dict for the CURRENT mod index. Holding a reference to the
    index (not its id()) is what makes `is` sound: the held object cannot be
    freed, so its address cannot be reused by a new index."""
    global _cache_index
    idx = mods.current()
    if idx is not _cache_index:
        _cache.clear()
        _cache_index = idx
    return _cache


# ── Bridge registry ────────────────────────────────────────────────────────

def _scan_mod_bridges() -> list:
    """Mod-provided bridge config scripts. STUB: the follow-up feature fills
    this in. Contract (spec §1): walk mods.current().files for keys matching
    ^bridge/[^/]+\\.py$ with target == "sdk"; keep a module only if its source
    TEXT contains "def CreateBridgeModel(" (never import it); label via
    bridge_label(); stock script names are dropped (stock wins), logged once.
    """
    return []


def available_bridges() -> list:
    cache = _cache_for_current_index()
    got = cache.get("bridges")
    if got is None:
        stock_names = {b.script_name for b in STOCK_BRIDGES}
        got = list(STOCK_BRIDGES) + [b for b in _scan_mod_bridges()
                                     if b.script_name not in stock_names]
        cache["bridges"] = got
    return list(got)


def is_available(script_name: str) -> bool:
    return any(b.script_name == script_name for b in available_bridges())


def bridge_label(script_name: str) -> str:
    for b in STOCK_BRIDGES:
        if b.script_name == script_name:
            return b.label
    for b in available_bridges():
        if b.script_name == script_name:
            return b.label
    # A bridge we do not know (a removed mod, a hand-edit): strip one
    # trailing "Bridge" so the row still reads as a name.
    if script_name.endswith("Bridge") and len(script_name) > len("Bridge"):
        return script_name[:-len("Bridge")]
    return script_name


# ── Ship universe ──────────────────────────────────────────────────────────

def _stock_ship_stems() -> dict:
    """{folded stem: stem} for every top-level ships/*.py in the SDK."""
    out: dict = {}
    try:
        entries = list((paths.sdk_scripts() / "ships").iterdir())
    except OSError:
        return out
    for p in entries:
        if p.suffix.lower() != ".py" or not p.is_file():
            continue
        if p.stem == "__init__":
            continue
        out[p.stem.lower()] = p.stem
    return out


def _mod_ship_stems() -> dict:
    """{folded stem: author's stem} for every top-level ships/*.py a mod
    provides. Index keys are folded and scripts/-stripped; raw_rel keeps the
    author's spelling, which is what g_sPlayerType / CreatePlayerShip see."""
    out: dict = {}
    for key, mf in mods.current().files.items():
        if mf.target != "sdk":  # paths-guard: kind label
            continue
        m = _SHIP_KEY_RE.match(key)
        if m is None or m.group(1) == "__init__":
            continue
        out[m.group(1)] = Path(mf.raw_rel).stem
    return out


def available_ships() -> list:
    """Script stems of every ship the player could fly, sorted by label.
    A mod override of a stock ship keeps the STOCK spelling (one row)."""
    cache = _cache_for_current_index()
    got = cache.get("ships")
    if got is None:
        stock = _stock_ship_stems()
        merged = dict(stock)
        for folded, stem in _mod_ship_stems().items():
            if folded not in merged:
                merged[folded] = stem
        got = sorted(merged.values(), key=lambda s: (ship_label(s).lower(), s))
        cache["ships"] = got
    return list(got)


def _ship_labels() -> dict:
    cache = _cache_for_current_index()
    got = cache.get("ship_labels")
    if got is None:
        got = {}
        try:
            from engine.missions.tgl_reader import read_tgl
            got = dict(read_tgl(paths.game_asset("data/TGL/Ships.tgl")).strings)
        except Exception as exc:          # missing/corrupt TGL: stems are fine
            dev_mode.log_swallowed("bridge_selection Ships.tgl", exc)
        cache["ship_labels"] = got
    return got


def ship_label(stem: str) -> str:
    """BC's display name for a ship script (Ships.tgl), else the stem."""
    return _ship_labels().get(stem) or stem
