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


def inject_into_menus(qb=_UNSET) -> int:
    """Add a button for every registered ship into the BUILT QuickBattle
    panes -- the half `register()` cannot do (see its own docstring).

    `GenerateShipMenu` (called from `BuildDialog`) builds the ship pane from
    hardcoded per-ship `if (iShipsUnlocked1 & AKIRA)` lines; it never reads
    the five tables `register()` writes. So a ship can be fully registered
    and still be invisible to the player -- this is the second half that
    makes it appear. Our own CEF picker needs no code of its own for this:
    `engine/ui/quick_battle_setup_panel.py`'s `_collect_categories` DFS-walks
    the live pane for `STCharacterMenu` nodes and treats their `STButton`
    children as ships, so attaching a button anywhere that DFS will reach is
    sufficient.

    Returns the number of buttons added (0 when nothing is registered, or
    when no QuickBattle module is present -- the same `qb=_UNSET` /
    explicit-None contract `register()` uses).

    Idempotence is per WIDGET, not per ship id: a button is only added when
    the target category does not already have a same-named child
    (`STMenu.GetButtonW`). That is deliberately more precise than a
    module-level "already injected" set would be: `BuildDialog()` replaces
    both `g_pShipsPane` and `g_pPlayerPane` wholesale on every call --
    `GenerateShipMenu` runs from scratch even for the stock ships -- so a
    second dialog build (a mission swap, or a caller rebuilding the dialog
    directly) produces two brand-new, empty panes. A ship-id-keyed "already
    injected" set would wrongly skip those fresh panes forever, having
    "remembered" injecting into panes that no longer exist. Per-widget
    idempotence gets both cases right: nothing new to add on a bare re-read
    of the SAME pane, and a full re-add into a REPLACED one.

    Because of that same replace-on-every-call behaviour, this also arranges
    for `BuildDialog` itself to re-run the injection after it rebuilds the
    panes, so a rebuild triggered from anywhere (not just the one call site
    in host_loop.py) still carries mod ships forward.
    """
    if not _registered:
        # Nothing to inject -- do not even resolve or touch the QuickBattle
        # module, so a Foundation-less boot is byte-identical.
        return 0
    module = _resolve_qb() if qb is _UNSET else qb
    if module is None:
        return 0
    _ensure_build_dialog_reinjects(module)
    return _inject_registered_ships(module)


def _ensure_build_dialog_reinjects(module) -> None:
    """Wrap `module.BuildDialog` (once) so every future call re-runs the
    injection after the real BuildDialog rebuilds g_pShipsPane/g_pPlayerPane
    from scratch. See `inject_into_menus`'s docstring for why a rebuild
    would otherwise silently drop every mod ship the first build picked up.
    """
    orig = getattr(module, "BuildDialog", None)
    if orig is None or getattr(orig, "_foundation_reinjects", False):
        return

    def _build_dialog_and_reinject(bPreservePane=0, _orig=orig, _module=module):
        _orig(bPreservePane)
        _inject_registered_ships(_module)

    _build_dialog_and_reinject._foundation_reinjects = True
    module.BuildDialog = _build_dialog_and_reinject


def _category_label(module, group):
    """A mod's `menuGroup` is a TGL KEY; the built categories carry the
    RESOLVED text. Translate before matching or creating.

    BC's own QuickBattle.py builds every stock category through the
    mission database -- `STCharacterMenu_CreateW(g_pMissionDatabase.
    GetString("Fed Ships"))` -- and Foundation's StaticDefs.py re-registers
    all 30 stock ships under those same keys, which is why every mod in
    the corpus authors `menuGroup = 'Fed Ships'` rather than the
    "Federation Ships" a player sees. Comparing the raw key against a
    built category's label never matched, so mod ships used to pile into
    a second, duplicate Federation category.

    Appc returns the key unchanged for a key with no TGL entry, so a
    group a mod invents (the Steamrunner pack's "Borg Ships") still gets
    its own category -- the correct outcome, and the same one BC gives.
    Falls back to the raw group when no database is present.
    """
    db = getattr(module, "g_pMissionDatabase", None)
    get_string = getattr(db, "GetString", None) if db is not None else None
    if get_string is None:
        return group
    try:
        resolved = get_string(group)
    except Exception:
        return group
    # TGString subclasses str, so this is already comparable; str() keeps
    # the widget label a plain string either way.
    return str(resolved) if resolved else group


def _inject_registered_ships(module) -> int:
    added = 0
    for name, sid in _registered:
        ship_def = _definition_for_sid(sid)
        if ship_def is None:
            continue
        for pane_attr, group_attr, event_attr in (
                ("g_pShipsPane", "menuGroup", "ET_SELECT_SHIP_TYPE"),
                ("g_pPlayerPane", "playerMenuGroup", "ET_SELECT_PLAYER_SHIP_TYPE")):
            group = getattr(ship_def, group_attr, None)
            if group is None:
                # Unset -- the ship was never RegisterQB{,Player}ShipMenu'd
                # for this pane. Nothing to add here.
                continue
            pane = getattr(module, pane_attr, None)
            if pane is None:
                continue
            label = _category_label(module, group)
            category = _find_category(pane, label)
            if category is None:
                from engine.appc.tg_ui.st_widgets import STCharacterMenu_CreateW
                category = STCharacterMenu_CreateW(label)
                pane.AddChild(category, 0.0, 0.0)
            if category.GetButtonW(name) is not None:
                continue  # already there -- idempotent
            event = getattr(module, event_attr, None)
            xo = getattr(module, "g_pXO", None)
            button = module.CreateBridgeMenuButton(name, event, sid, xo)
            category.AddChild(button)
            added += 1
    return added


def _definition_for_sid(sid):
    """The ShipDefinition `allocate_ship_type` minted `sid` for, or None.

    `_ids` maps ship-definition identity (`id(ship_def)`) to the id it was
    allocated -- the same key `register()` uses -- so this reverses that
    lookup and resolves the identity back to the live object via
    `all_definitions()` (which keeps every definition alive for the run,
    per `shipdef.py`'s own comment on why `id()` reuse cannot happen here).
    """
    from engine.foundation.shipdef import all_definitions
    own_key = None
    for key, value in _ids.items():
        if value == sid:
            own_key = key
            break
    if own_key is None:
        return None
    for d in all_definitions():
        if id(d) == own_key:
            return d
    return None


def _child_widgets(node) -> list:
    """Direct child widgets of any container, normalising the two storage
    conventions (TGPane/STSubPane store (child, x, y) tuples; STMenu and
    _STStylizedWindow store bare widgets). Mirrors
    engine/ui/quick_battle_setup_panel.py's `_child_widgets` static method
    exactly -- kept as a second copy rather than a shared import so
    engine/foundation does not gain a dependency on engine/ui. If one
    changes, check the other."""
    if node is None:
        return []
    kids = node.__dict__.get("_children")
    if not kids:
        return []
    return [k[0] if isinstance(k, tuple) else k for k in kids]


def _find_category(root, label):
    """The same DFS `quick_battle_setup_panel._collect_categories` runs,
    stopped at the first `STCharacterMenu` whose label matches -- so a new
    category lands exactly where that picker's own walk will find it, and
    an existing one (stock or previously-injected) is reused rather than
    duplicated."""
    from engine.appc.tg_ui.st_widgets import STCharacterMenu
    for child in _child_widgets(root):
        if isinstance(child, STCharacterMenu):
            if child.GetLabel() == label:
                return child
        else:
            found = _find_category(child, label)
            if found is not None:
                return found
    return None


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
