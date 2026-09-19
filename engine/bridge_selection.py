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

# BC's own "Player and Region" picker: the hulls GeneratePlayerShipMenu
# offers (sdk QuickBattle.py:1622-1703), by the script stem SelectPlayerShip
# assigns to g_sPlayerType (g_dFriendlyShipTypeToDetails[type][0]). The
# ships/ directory is NOT the player universe -- stations, asteroids, probes
# and the campaign one-offs are friend/enemy catalog entries only. The unlock
# bitfields that gate the menu default to everything-unlocked (:1181) and
# nothing in this tree narrows them, so they are ignored here. Mods extend
# the menu through Foundation's RegisterQBPlayerShipMenu.
STOCK_PLAYER_SHIPS: tuple = (
    "Akira", "Ambassador", "Galaxy", "Nebula", "Sovereign",      # Fed
    "BirdOfPrey", "Vorcha",                                      # Klingon
    "Marauder",                                                  # Ferengi
    "Warbird",                                                   # Romulan
    "Galor", "Keldon", "CardHybrid",                             # Cardassian
    "KessokLight", "KessokHeavy",                                # Kessok
    "Shuttle", "Transport",                                      # Other
)

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


def _mod_player_ship_files() -> list:
    """shipFile of every Foundation definition registered on the player
    menu (RegisterQBPlayerShipMenu), in registration order. A definition
    registered only for the friend/enemy catalog is not a player hull."""
    from engine.foundation.shipdef import all_definitions
    out = []
    for d in all_definitions():
        if getattr(d, "playerMenuGroup", None) is None:
            continue
        ship_file = getattr(d, "shipFile", None)
        if ship_file:
            out.append(str(ship_file))
    return out


def available_ships() -> list:
    """Script stems of every ship BC's player picker would offer, sorted by
    label: STOCK_PLAYER_SHIPS plus Foundation player-menu registrations,
    each kept only if its ships/<stem>.py exists (stock tree or mod
    overlay). A mod override of a stock ship keeps the STOCK spelling (one
    row); a mod registration's spelling folds onto its script's."""
    cache = _cache_for_current_index()
    got = cache.get("ships")
    if got is None:
        installed = dict(_stock_ship_stems())
        for folded, stem in _mod_ship_stems().items():
            installed.setdefault(folded, stem)
        wanted = list(STOCK_PLAYER_SHIPS) + _mod_player_ship_files()
        merged: dict = {}
        for name in wanted:
            stem = installed.get(name.lower())
            if stem is not None:
                merged.setdefault(name.lower(), stem)
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


# ── Pins (persisted: bridges.json) ─────────────────────────────────────────

DEFAULT_PINS: dict = {
    "Galaxy": "GalaxyBridge",
    "Sovereign": "SovereignBridge",
    "Akira": "SovereignBridge",
}
DEFAULT_BRIDGE = "GalaxyBridge"
_PINS_SECTION = "pins"
_DEFAULT_SECTION = "default"        # {"bridge": "<script>"}; absent => DEFAULT_BRIDGE
_DEFAULT_KEY = "bridge"
DefaultRow = namedtuple("DefaultRow", "bridge bridge_label bridge_missing")

PinRow = namedtuple("PinRow",
                    "ship ship_label bridge bridge_label ship_missing bridge_missing")


class DuplicateShip(ValueError):
    """add(): the ship already has a pin (edit = remove + add)."""


class UnmappedShip(ValueError):
    """set_bridge(): the ship has no mapping to change (use add)."""


class UnknownBridge(ValueError):
    """add(): the bridge is not in available_bridges()."""


def default_bridges_path() -> Path:
    """Beside settings.json. Its own file so a player can back up / restore
    bridge pins without dragging graphics settings along (spec decision 6).
    A function, not a constant: the single seam to move for a read-only
    install dir, like settings_store.default_settings_path()."""
    from engine import settings_store
    return settings_store.default_settings_path().parent / "bridges.json"


class BridgePins:
    """The ship->bridge map over a SettingsStore at bridges.json.

    File absent  => a copy of DEFAULT_PINS.
    File present => its "pins" section, authoritative even when {}.
    The bridge for an unmapped ship is the "default" section's "bridge"
    (absent => DEFAULT_BRIDGE); it is the one row the panel cannot remove.
    Keys compare exactly as written: the panel always writes canonical
    script stems, so a restored file behaves as it did when saved.
    """

    def __init__(self, store):
        self.store = store
        self._warned: set = set()

    # -- read --
    def pins(self) -> dict:
        if not self.store.has_section(_PINS_SECTION):
            return dict(DEFAULT_PINS)
        raw = self.store._section(_PINS_SECTION)
        return {str(k): str(v) for k, v in raw.items() if isinstance(v, str)}

    def default_bridge(self) -> str:
        """The stored default as written (it may be unavailable -- the row
        shows it missing); DEFAULT_BRIDGE when nothing is stored."""
        got = self.store.get(_DEFAULT_SECTION, _DEFAULT_KEY)
        return got if isinstance(got, str) and got else DEFAULT_BRIDGE

    def _loadable_default(self) -> str:
        """default_bridge() if it can be loaded, else the stock DEFAULT_BRIDGE
        (always present), logged once."""
        bridge = self.default_bridge()
        if is_available(bridge):
            return bridge
        tag = ("*default*", bridge)
        if tag not in self._warned:
            self._warned.add(tag)
            print("[bridge_selection] default bridge %s is not available; "
                  "using %s" % (bridge, DEFAULT_BRIDGE), flush=True)
        return DEFAULT_BRIDGE

    def resolve(self, ship_name) -> str:
        """The bridge config script to load for `ship_name`. Never raises."""
        if not ship_name:
            return self._loadable_default()
        bridge = self.pins().get(ship_name)
        if bridge is None:
            return self._loadable_default()
        if not is_available(bridge):
            fallback = self._loadable_default()
            tag = (ship_name, bridge)
            if tag not in self._warned:
                self._warned.add(tag)
                print("[bridge_selection] pin %s -> %s is not available; "
                      "using %s" % (ship_name, bridge, fallback),
                      flush=True)
            return fallback
        return bridge

    def default_row(self) -> DefaultRow:
        bridge = self.default_bridge()
        return DefaultRow(bridge, bridge_label(bridge), not is_available(bridge))

    def rows(self) -> list:
        """Panel rows in file order, with labels and missing flags. Nothing
        is pruned: a ship outside available_ships() (absent, or installed
        but not a player hull) or an unavailable bridge is shown, not
        hidden (the file is backed up, restored and hand-edited)."""
        ships = set(available_ships())
        return [PinRow(ship, ship_label(ship), bridge, bridge_label(bridge),
                       ship not in ships, not is_available(bridge))
                for ship, bridge in self.pins().items()]

    def unpinned_ships(self) -> list:
        pinned = set(self.pins())
        return [s for s in available_ships() if s not in pinned]

    # -- write --
    def _write_all(self, mapping: dict) -> None:
        """Write the WHOLE map. The first edit of a fresh install materialises
        the defaults into the file, which is what lets a removed default
        stay removed on the next launch. set_section (not per-key set) so an
        empty map leaves a PRESENT empty section: authoritative "no pins"."""
        self.store.set_section(_PINS_SECTION, dict(mapping))

    def add(self, ship: str, bridge: str) -> None:
        current = self.pins()
        if ship in current:
            raise DuplicateShip(ship)
        if not is_available(bridge):
            raise UnknownBridge(bridge)
        current[ship] = bridge
        self._write_all(current)

    def set_bridge(self, ship: str, bridge: str) -> None:
        """Re-point an existing mapping. File order is kept (the row stays
        where it was); the bridge must be available, the old one need not be."""
        current = self.pins()
        if ship not in current:
            raise UnmappedShip(ship)
        if not is_available(bridge):
            raise UnknownBridge(bridge)
        current[ship] = bridge
        self._write_all(current)

    def set_default_bridge(self, bridge: str) -> None:
        if not is_available(bridge):
            raise UnknownBridge(bridge)
        self.store.set(_DEFAULT_SECTION, _DEFAULT_KEY, bridge)

    def remove(self, ship: str) -> None:
        current = self.pins()
        if ship not in current:
            return
        del current[ship]
        self._write_all(current)

    def reset(self) -> None:
        """Delete the file: back to genuine first-launch (the defaults)."""
        self.store.delete_file()


def load_bridge_pins(path=None) -> BridgePins:
    from engine.settings_store import SettingsStore
    store = SettingsStore(path if path is not None else default_bridges_path())
    store.load()
    return BridgePins(store)


# ── QuickBattle consumer ───────────────────────────────────────────────────

def install_quickbattle_hook(qb_module, pins) -> bool:
    """Wrap QuickBattle.RecreatePlayer so g_sBridgeType is resolved from the
    matrix at the moment of use.

    RecreatePlayer is the ONE chokepoint every QuickBattle player creation
    funnels through -- Initialize, StartSimulation2, EndSimulation,
    ShipDestroyed -- and it ends with LoadBridge.Load(g_sBridgeType)
    (QuickBattle.py:2928). The SDK calls it as a module global, so replacing
    the attribute reaches the two callers the host never sees. Precedent:
    engine/foundation/quickbattle._ensure_build_dialog_reinjects.

    Three cases, keyed off whatever `RecreatePlayer` currently is:
      - no pins (`pins is None`): this controller has no matrix, so the
        SDK's own g_sBridgeType default must stand. If RecreatePlayer is
        currently wrapped (a STALE hook from some earlier controller in this
        process -- see below), unwrap it back to the true original. Always
        returns False: nothing of ours is installed afterward.
      - same pins as the current wrapper: no-op, returns False.
      - different (or no) existing wrap, real pins: (re)wrap around the true
        original, returns True.

    Rewraps/unwraps rather than no-ops when RecreatePlayer is already
    wrapped for a DIFFERENT pins object (including None): `sys.modules
    ['QuickBattle.QuickBattle']` is never actually re-imported on a mission
    swap in this engine (importlib.import_module just returns the cached
    module -- verified, not assumed; see reset_sdk_globals/_init_mission,
    neither pops it from sys.modules), so a fresh HostController reaching an
    already-hooked module (headless tests build one per test; a real second
    HostController in the same process would too) would otherwise stay
    bound to the FIRST controller's pins forever -- or, if the second
    controller has no matrix at all, silently inherit the first one's real
    pins instead of the SDK's own default. Rewrapping/unwrapping targets the
    stored TRUE original (`_dauntless_bridge_orig`), never the previous
    wrapper -- wrapping a wrapper would run the stale g_sBridgeType write
    right after ours and clobber it before RecreatePlayer's own body
    executes.
    """
    current = getattr(qb_module, "RecreatePlayer", None)
    if current is None:
        return False
    is_hooked = getattr(current, "_dauntless_bridge_hook", False)
    if pins is None:
        if is_hooked:
            qb_module.RecreatePlayer = current._dauntless_bridge_orig
        return False
    if is_hooked:
        if getattr(current, "_dauntless_bridge_pins", None) is pins:
            return False
        true_orig = current._dauntless_bridge_orig
    else:
        true_orig = current

    def _recreate_player_with_matrix_bridge(_orig=true_orig, _qb=qb_module, _pins=pins):
        _qb.g_sBridgeType = _pins.resolve(getattr(_qb, "g_sPlayerType", None))
        return _orig()

    _recreate_player_with_matrix_bridge._dauntless_bridge_hook = True
    _recreate_player_with_matrix_bridge._dauntless_bridge_pins = pins
    _recreate_player_with_matrix_bridge._dauntless_bridge_orig = true_orig
    qb_module.RecreatePlayer = _recreate_player_with_matrix_bridge
    return True
