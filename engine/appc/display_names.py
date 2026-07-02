"""Object display-name registration — the engine's run of the SDK's
MissionLib.SetDisplayNames pattern.

BC gives set objects a localized *display name* distinct from their internal
name: E1M2's colony "Haven" shows as "Vesuvi 6 - Haven", its station "Facility"
as "Haven Facility", and its "Debris1".."Debris6" as "Debris 1".."Debris 6".
Those mappings live in the loaded TGL hierarchy — the campaign
(``Maelstrom.tgl``: Haven/Facility/Moon) and the mission (``E1M2.tgl``: Debris).
Both the Helm→Hail menu (CreateHailButton) and the target list read
``GetDisplayName()``, so without this pass they show raw internal names.

MissionLib.SetSingleDisplayName does ``db.GetString(name)`` then
``if kDisplayName: SetDisplayName(...)`` — relying on GetString returning empty
for an absent key. The engine's GetString returns the *key itself* for absent
keys (a deliberate fallback that keeps FindMenu / TextBanner working on real
strings), so calling SetDisplayNames per-database would clobber every
non-matching object's display name with its raw key. We therefore gate on
``HasString`` (the faithful "does this DB define a display name for this object"
check) and take the first database in the campaign→episode→mission order that
has an entry — matching the SDK's intent without the key-fallback hazard.
"""

import App
import engine.dev_mode as dev_mode


def _display_databases():
    """The campaign → episode → mission localization databases in scope, in
    precedence order. These are exactly the DBs set via SetDatabase at each
    level (Game/Episode/Mission), which is where BC's display-name strings
    live."""
    dbs = []
    game = App.Game_GetCurrentGame()
    if game is None:
        return dbs
    gdb = game.GetDatabase()
    if gdb is not None:
        dbs.append(gdb)
    ep = game.GetCurrentEpisode() if hasattr(game, "GetCurrentEpisode") else None
    if ep is not None:
        edb = ep.GetDatabase()
        if edb is not None:
            dbs.append(edb)
        mission = ep.GetCurrentMission() if hasattr(ep, "GetCurrentMission") else None
        if mission is not None:
            mdb = mission.GetDatabase()
            if mdb is not None:
                dbs.append(mdb)
    return dbs


def apply_display_names() -> None:
    """Set every non-bridge set object's display name from the first in-scope
    TGL that defines one for its internal name. Idempotent and best-effort:
    objects with no display mapping keep their current name; any per-object
    failure is swallowed so one bad handle never aborts the sweep.

    Run once per mission load, after the mission's objects are created and
    before they're sensor-identified (so the Hail button / target row shows the
    localized name)."""
    databases = _display_databases()
    if not databases:
        return
    try:
        sets = App.g_kSetManager.GetAllSets()
    except Exception as _e:
        dev_mode.log_swallowed("display-name GetAllSets", _e)
        return
    for pSet in sets:
        try:
            if pSet.GetName() == "bridge":
                continue
            objects = pSet.GetObjectList()
        except Exception:
            continue
        for obj in objects:
            _apply_one(obj, databases)


def apply_display_name(obj) -> None:
    """Set a single object's display name from the in-scope TGLs. Called by the
    sensor-identification pass the moment a contact is first identified — so
    objects created after the mission-load batch pass (e.g. a system set that
    loads on warp-in) still get their localized name before their Hail button /
    target row is built. Cheap and idempotent."""
    databases = _display_databases()
    if databases:
        _apply_one(obj, databases)


def _apply_one(obj, databases) -> None:
    try:
        name = obj.GetName()
    except Exception:
        return
    if not name:
        return
    for db in databases:
        try:
            if db.HasString(name):
                obj.SetDisplayName(str(db.GetString(name)))
                return
        except Exception as _e:
            dev_mode.log_swallowed("display-name apply", _e)
            return
