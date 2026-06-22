"""Warp Stage 1 — the hard-cut warp spine.

WarpSequence_Create builds a TGSequence that (1) loads + switches to the
destination set, (2) moves the player into it at the placement, (3) terminates
the source set and restores player control. Renderer realize/teardown is reached
via module-level hooks the host registers; unset hooks make those steps no-ops
(headless set/placement logic still runs). See
docs/superpowers/specs/2026-06-22-warp-stage1-hard-cut-design.md.
"""
from engine.appc.actions import TGAction, TGSequence

# Host-registered render hooks: fn(pSet) -> None. None => skip (headless).
_realize_hook = None
_teardown_hook = None
# Optional current-player fallback when App.Game_GetCurrentPlayer() is None.
_player_hook = None


def configure_warp_hooks(realize=None, teardown=None, current_player=None):
    global _realize_hook, _teardown_hook, _player_hook
    _realize_hook = realize
    _teardown_hook = teardown
    _player_hook = current_player


def _module_is_empty(module):
    """True when there's no destination module to load (None / empty /
    whitespace). Mirrors BC's `if pcDestModule != None:` guard in
    WarpSequence.SetupSequence — a falsy destination means 'no set change'."""
    return module is None or not str(module).strip()


def _set_name_from_module(module):
    """'Systems.Vesuvi.Vesuvi4' -> 'Vesuvi4' (mirrors WarpSequence.py)."""
    if _module_is_empty(module):
        return None
    s = str(module).strip()
    return s[s.rfind(".") + 1:] if "." in s else s


class ChangeRenderedSetAction(TGAction):
    """Load (if needed) and switch the rendered set. Faithful to BC's
    ChangeRenderedSetAction_Create(module) / _CreateFromSet(set)."""

    def __init__(self, module=None, pSet=None):
        super().__init__()
        self._module = module
        self._set = pSet

    def _do_play(self):
        import App
        pSet = self._set
        if pSet is None:
            # No explicit set AND no module to load => no set change (no-op).
            # Mirrors BC's `if pcDestModule != None:` guard. A non-empty module
            # that fails to import/register still raises below (fail loud).
            if _module_is_empty(self._module):
                return
            name = _set_name_from_module(self._module)
            pSet = App.g_kSetManager.GetSet(name)
            if pSet is None:
                # Lazy-load: import the region module and Initialize() it.
                # Fail loud — a bad module raises here.
                import importlib
                mod = importlib.import_module(self._module)
                mod.Initialize()
                pSet = App.g_kSetManager.GetSet(name)
                if pSet is None:
                    raise RuntimeError(
                        "warp: module %r Initialize() did not register set %r"
                        % (self._module, name))
        App.g_kSetManager.MakeRenderedSet(pSet.GetName())
        if _realize_hook is not None:
            _realize_hook(pSet)


def ChangeRenderedSetAction_Create(module):
    return ChangeRenderedSetAction(module=module)


def ChangeRenderedSetAction_CreateFromSet(pSet):
    return ChangeRenderedSetAction(pSet=pSet)


class _PlacePlayerAction(TGAction):
    """Move the player ship from its source set into the destination set and
    position it at the named placement."""

    def __init__(self, ship, dest_name, placement):
        super().__init__()
        self._ship = ship
        self._dest_name = dest_name
        self._placement = placement

    def _do_play(self):
        import App
        ship = self._ship
        # No destination set (e.g. None warp destination) => nothing to move
        # the player into. Degrade to a no-op: leave the ship where it is.
        if not self._dest_name:
            return
        dest = App.g_kSetManager.GetSet(self._dest_name)
        if dest is None:
            return
        # Remove from whatever set currently holds it.
        for s in list(App.g_kSetManager._sets.values()):
            if s.GetObject(ship.GetName()) is ship:
                s.RemoveObjectFromSet(ship.GetName())
        dest.AddObjectToSet(ship, ship.GetName())
        ship.PlaceObjectByName(self._placement)


class _ArriveFinalizeAction(TGAction):
    """Terminate the source set (render teardown + DeleteSet) and return
    player control."""

    def __init__(self, source_set):
        super().__init__()
        self._source = source_set

    def _do_play(self):
        import App
        src = self._source
        # No source set captured (e.g. the warp degraded to a no-op) => nothing
        # to tear down; leave everything as-is.
        if src is not None:
            name = src.GetName()
            # Only terminate if it isn't the destination (defensive).
            if App.g_kSetManager.GetRenderedSet() is not src:
                if _teardown_hook is not None:
                    _teardown_hook(src)
                App.g_kSetManager.DeleteSet(name)
        # Undo SDK WarpPressed's RemoveControl (no-op if MissionLib absent).
        try:
            import MissionLib
            MissionLib.ReturnControl()
        except Exception:
            pass


class WarpSequence(TGSequence):
    def __init__(self, ship, dest_module, warp_time, placement):
        super().__init__()
        self._ship = ship
        self._dest_module = dest_module
        self._warp_time = float(warp_time)
        self._placement = placement

    def GetShip(self):          return self._ship
    def GetDestination(self):   return self._dest_module
    def GetPlacementName(self):  return self._placement


def WarpSequence_Create(ship, dest_module, warp_time=0.0, placement="Player Start"):
    import App
    seq = WarpSequence(ship, dest_module, warp_time, placement)
    dest_name = _set_name_from_module(dest_module)
    # Capture the source set NOW (before the player is moved).
    source = None
    for s in App.g_kSetManager._sets.values():
        if s.GetObject(ship.GetName()) is ship:
            source = s
            break
    seq.AddAction(ChangeRenderedSetAction_Create(dest_module))
    # Falsy destination => no set change/placement/teardown: the whole warp
    # degrades to "nothing happened" (BC's `if pcDestModule != None:` guard).
    # The per-action _do_play guards are the robust floor; skipping placement
    # and source teardown here keeps the player in its current set.
    if not _module_is_empty(dest_module):
        seq.AppendAction(_PlacePlayerAction(ship, dest_name, placement))
        seq.AppendAction(_ArriveFinalizeAction(source))
    return seq


def execute_warp(button, event=None):
    """ET_WARP_BUTTON_PRESSED handler (registered second, after SDK WarpPressed)
    — builds and plays the warp spine for the button's destination."""
    import App
    dest = button.GetDestination()
    if not dest:
        return
    player = App.Game_GetCurrentPlayer()
    if player is None and _player_hook is not None:
        player = _player_hook()
    if player is None:
        return
    WarpSequence_Create(player, dest, button.GetWarpTime(), "Player Start").Play()
