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


def reset():
    _ids.clear()
    _registered.clear()


def allocate_ship_type(key) -> int:
    """A stable id for this ship within the run."""
    if key not in _ids:
        _ids[key] = ST_MOD_BASE + len(_ids)
    return _ids[key]


def registered() -> list:
    return list(_registered)


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
    """
    sid = allocate_ship_type(ship_def.name)
    entry = (ship_def.name, sid)
    if entry not in _registered:
        _registered.append(entry)

    module = _resolve_qb() if qb is _UNSET else qb
    if module is None:
        # No QuickBattle in this context (bridge-only mission, a tool).
        # The intent is recorded; nothing to inject into.
        return sid

    icon = getattr(ship_def, "icon_number", 0)
    module.g_dShipNameToType[ship_def.name] = sid
    module.g_dShipNameToIconNumber[ship_def.name] = icon
    module.g_dShipTypeToIconNumber[sid] = icon

    for table_name, side, ai in (
            ("g_dFriendlyShipTypeToDetails", "Friendly", "QuickBattleFriendlyAI"),
            ("g_dEnemyShipTypeToDetails", "Enemy", "QuickBattleEnemyAI")):
        table = getattr(module, table_name)
        table[sid] = [
            ship_def.shipFile,
            ship_def.name,
            "QB%sGenericShipDestroyed" % side,
            ai,
            side,
        ]
    return sid
