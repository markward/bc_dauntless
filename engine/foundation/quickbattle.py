"""Register Foundation ships into QuickBattle's static ship tables.

BC's QuickBattle holds literal dicts keyed by ST_* integers (ST_MARAUDER=0
.. ST_TRANSPORT=30), which is why Foundation replaces the file wholesale --
its readme says it "replaces the static indexes of Bridge Commander with
dynamic structures". We instead extend those same tables, so modded and
stock ships travel one code path and everything that reads them (mission
scripts, the AI named in each row, the destroyed-event wiring) sees modded
ships too.

Our CEF picker needs no change: it walks the live widget tree QuickBattle
builds from these tables, not a list of its own.
"""
from __future__ import annotations

# Stock occupies 0..30. Start far clear of it so no future BC content
# addition could close the gap.
ST_MOD_BASE = 1000

_ids: dict = {}
_registered: list = []
_collisions: list = []


def reset():
    _ids.clear()
    _registered.clear()
    _collisions.clear()


def allocate_ship_type(key) -> int:
    """A stable id for this ship within the run."""
    if key not in _ids:
        _ids[key] = ST_MOD_BASE + len(_ids)
    return _ids[key]


def registered() -> list:
    return list(_registered)


def collisions() -> list:
    """(name, existing_id) pairs a registration would have clobbered.

    Both `g_dShipNameToType` and `g_dShipNameToIconNumber` are keyed by the
    ship's human-authored display name, not a namespaced id -- unlike the
    three id-keyed tables, which are structurally immune (every minted id is
    >= ST_MOD_BASE, stock only occupies 0..30). A mod naming its ship
    "Sovereign" would otherwise silently retarget the stock entry; two mods
    naming a ship the same thing would silently clobber each other. See
    `register()`.
    """
    return list(_collisions)


def _resolve_qb():
    """The live SDK QuickBattle module, or None if not importable."""
    import importlib
    try:
        return importlib.import_module("QuickBattle.QuickBattle")
    except Exception:
        return None


# Distinguishes "caller said nothing" from "caller explicitly said there is
# no QuickBattle module". A plain None default cannot: the tests need to pass
# qb=None meaning "no module", while an omitted qb must resolve the live one.
_UNSET = object()


def register(ship_def, group, player: bool = False, qb=_UNSET) -> int:
    """Inject `ship_def` into QuickBattle's five tables. Returns its id.

    `qb` omitted resolves the live module; pass a module (or a stand-in) to
    inject into it, or an explicit None to record the registration with no
    module present.

    `group` is accepted but unused here: the menu category a mod's ship
    lands in comes from `SubMenu`/`SubSubMenu` on the `ShipDefinition`
    itself, which the caller (the mod) already set directly -- register()
    has nothing to add on top of that.

    `player` is likewise accepted but unused: stock QuickBattle builds its
    player-ship pane from hardcoded `if (iShipsUnlocked1 & AKIRA)` checks,
    not from any of these five tables -- exactly why real Foundation
    replaces QuickBattle.py wholesale instead of extending it. Our own CEF
    picker never reads that pane: `engine/ui/quick_battle_setup_panel.py`
    (~line 302-320) assigns the player ship straight from
    `g_dFriendlyShipTypeToDetails[sel][0]`, and its own comment says a ship
    absent from the friendly table is "not flyable". So writing the
    friendly-table row IS what makes a ship player-selectable here, and
    `RegisterQBShipMenu` / `RegisterQBPlayerShipMenu` doing the same work
    regardless of `player` is correct, not an oversight.
    """
    name = ship_def.name
    module = _resolve_qb() if qb is _UNSET else qb

    # allocate_ship_type is keyed by ship IDENTITY here, not by name. Name
    # alone cannot distinguish "the same ShipDefinition registered twice"
    # (the standard RegisterQBShipMenu-then-RegisterQBPlayerShipMenu
    # pattern every ship in our mod corpus uses) from "two different
    # ShipDefinitions that happen to share a display name" -- both would
    # look identical to a name-keyed cache. Object identity is stable for
    # the run: ShipDefinition.__init__ (shipdef.py) appends every instance
    # to _ALL_DEFINITIONS, so it is never garbage-collected -- and its
    # id() never reused -- before foundation.reset() runs.
    own_key = id(ship_def)

    # Guard the two NAME-keyed tables. The three id-keyed tables below are
    # safe by construction (every minted id is >= ST_MOD_BASE, stock only
    # occupies 0..30), but g_dShipNameToType / g_dShipNameToIconNumber are
    # keyed by this human-authored display name -- a mod naming its ship
    # "Sovereign" would otherwise silently retarget the stock entry, and two
    # mods both naming a ship "Enterprise" would silently clobber each
    # other's rows (the second register() call would overwrite the first's
    # id everywhere). Check the module's own table, since that is the
    # single source of truth for what is already claimed -- stock rows
    # started there, and our own prior registrations land there too.
    if module is not None and name in module.g_dShipNameToType:
        existing_id = module.g_dShipNameToType[name]
        if _ids.get(own_key) == existing_id:
            # This exact ShipDefinition instance already claimed `name` at
            # this id (we minted it below, on an earlier call) -- a
            # re-registration, not a collision. The tables already hold
            # this ship's data from that first call; we chose to leave
            # them as they are rather than rewrite them idempotently,
            # since a rewrite would put back the same values.
            return existing_id
        _collisions.append((name, existing_id))
        return existing_id

    sid = allocate_ship_type(own_key)
    entry = (name, sid)
    if entry not in _registered:
        _registered.append(entry)

    if module is None:
        # No QuickBattle in this context (bridge-only mission, a tool).
        # The intent is recorded; nothing to inject into.
        return sid

    # `icon` is intentionally 0 here: nothing in our UI reads
    # g_dShipNameToIconNumber or g_dShipTypeToIconNumber. Icons resolve by
    # name through engine/ui/ship_icons.py, from data/Icons/Ships/<stem>.tga.
    # These two tables are populated for shape-fidelity with the SDK only;
    # this is a harmless no-op, not a missing wire-up.
    icon = getattr(ship_def, "icon_number", 0)
    module.g_dShipNameToType[name] = sid
    module.g_dShipNameToIconNumber[name] = icon
    module.g_dShipTypeToIconNumber[sid] = icon

    for table_name, side, ai in (
            ("g_dFriendlyShipTypeToDetails", "Friendly", "QuickBattleFriendlyAI"),
            ("g_dEnemyShipTypeToDetails", "Enemy", "QuickBattleEnemyAI")):
        table = getattr(module, table_name)
        table[sid] = [
            ship_def.shipFile,
            name,
            "QB%sGenericShipDestroyed" % side,
            ai,
            side,
        ]
    return sid
