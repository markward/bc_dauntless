"""Warp Stage 1 — the hard-cut warp spine.

WarpSequence_Create builds a TGSequence that (1) loads + switches to the
destination set, (2) moves the player into it at the placement, (3) terminates
the source set and restores player control. Renderer realize/teardown is reached
via module-level hooks the host registers; unset hooks make those steps no-ops
(headless set/placement logic still runs). See
docs/superpowers/specs/2026-06-22-warp-stage1-hard-cut-design.md.
"""
import math

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


# ── Warp-VFX flythrough (Stage 2) ────────────────────────────────────────────
# Distance-based transit duration. T = clamp(T_MIN, T_MAX, T_BASE + K*dist),
# dist in galaxy-map units between the source and destination system vantages.
# K tuned so a mid-galaxy hop (~150 units) lands ≈ 5 s. Unmapped vantage (None
# on either side) => T_BASE (a short transit, no parallax).
_T_MIN, _T_MAX, _T_BASE, _K = 2.0, 10.0, 2.0, 0.02

# Align/turn phase length (s): the ship slows + swings onto the warp heading
# before the streak transit begins. Constant (distance-independent).
_T_ALIGN = 1.5

# Host-registered VFX hooks (None => instant Stage-1 path, headless-safe).
_vfx_start = None         # start(heading, t_align, t_transit)
_vfx_stop = None          # stop()
_vfx_enabled = None       # () -> bool  (toggle AND renderer AND procedural sky)
_vfx_vantage_of = None    # (set_or_module) -> (x, y, z) | None


def configure_warp_vfx(start=None, stop=None, enabled=None, vantage_of=None):
    global _vfx_start, _vfx_stop, _vfx_enabled, _vfx_vantage_of
    _vfx_start, _vfx_stop, _vfx_enabled, _vfx_vantage_of = (
        start, stop, enabled, vantage_of)


def _transit_duration(src_vantage, dst_vantage):
    """Distance-scaled transit length (s). Either vantage None => T_BASE."""
    if src_vantage is None or dst_vantage is None:
        return _T_BASE
    dx = dst_vantage[0] - src_vantage[0]
    dy = dst_vantage[1] - src_vantage[1]
    dz = dst_vantage[2] - src_vantage[2]
    dist = math.sqrt(dx * dx + dy * dy + dz * dz)
    t = _T_BASE + _K * dist
    return _T_MIN if t < _T_MIN else (_T_MAX if t > _T_MAX else t)


def _warp_heading(src_vantage, dst_vantage):
    """Normalized src->dst direction (galaxy-map space). Either vantage None or
    coincident => default ship-forward (0, 1, 0)."""
    if src_vantage is None or dst_vantage is None:
        return (0.0, 1.0, 0.0)
    dx = dst_vantage[0] - src_vantage[0]
    dy = dst_vantage[1] - src_vantage[1]
    dz = dst_vantage[2] - src_vantage[2]
    m = math.sqrt(dx * dx + dy * dy + dz * dz)
    return (0.0, 1.0, 0.0) if m < 1e-6 else (dx / m, dy / m, dz / m)


class _WarpSoundAction(TGAction):
    """Play a registered 2D/3D SFX by name (enter/exit warp). Fail-open: a
    missing sound / absent manager never blocks the warp chain."""

    def __init__(self, name):
        super().__init__()
        self._name = name

    def _do_play(self):
        try:
            import App
            App.g_kSoundManager.PlaySound(self._name)
        except Exception:
            pass


class _WarpVfxBeginAction(TGAction):
    """Align start: remove player control, slow the ship to a stop, and start
    the WarpVFX manager on the warp heading. Every step is fail-open — a failure
    here never blocks the set-swap chain (control is restored on arrival by
    _ArriveFinalizeAction regardless)."""

    def __init__(self, ship, heading, t_align, t_transit):
        super().__init__()
        self._ship = ship
        self._a = (heading, t_align, t_transit)

    def _do_play(self):
        try:
            import MissionLib
            MissionLib.RemoveControl()
        except Exception:
            pass
        try:
            if hasattr(self._ship, "SetSpeed"):
                self._ship.SetSpeed(0.0)
        except Exception:
            pass
        if _vfx_start is not None:
            try:
                _vfx_start(*self._a)
            except Exception:
                pass


class _WarpVfxEndAction(TGAction):
    """Stop the WarpVFX manager on arrival. Fail-open."""

    def _do_play(self):
        if _vfx_stop is not None:
            try:
                _vfx_stop()
            except Exception:
                pass


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


def _silence_ship_weapons(ship):
    """Stop any looping weapon-fire SFX on a ship's weapon banks.

    Energy banks (phaser/pulse) start a looped _PlayingSound on Fire() and stop
    it in StopFiring(). Warping out doesn't go through the normal cease-fire, so
    a mid-fire bank would loop forever in the new system. Walk each weapon
    system's child banks and StopFiring() any that expose it."""
    if ship is None:
        return
    for getter in ("GetPhaserSystem", "GetPulseWeaponSystem",
                   "GetTorpedoSystem", "GetTractorBeamSystem"):
        get = getattr(ship, getter, None)
        if not callable(get):
            continue
        try:
            wsys = get()
        except Exception:
            continue
        if wsys is None or not hasattr(wsys, "GetNumChildSubsystems"):
            continue
        try:
            n = wsys.GetNumChildSubsystems()
        except Exception:
            continue
        for i in range(n):
            bank = wsys.GetChildSubsystem(i)
            stop = getattr(bank, "StopFiring", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass


class _ArriveFinalizeAction(TGAction):
    """Silence weapon-fire loops, terminate the source set (render teardown +
    DeleteSet), and return player control."""

    def __init__(self, source_set, ship=None):
        super().__init__()
        self._source = source_set
        self._ship = ship

    def _do_play(self):
        import App
        src = self._source
        # Silence looping weapon SFX before we leave: the warping ship (which
        # has already moved to the destination) plus every ship left behind in
        # the source set (about to be torn down). Otherwise a phaser fired at
        # the moment of warp loops forever in the new system.
        _silence_ship_weapons(self._ship)
        if src is not None:
            for obj in list(getattr(src, "_objects", {}).values()):
                _silence_ship_weapons(obj)
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
    # Stage 2 timed flythrough: only when the flythrough is live (toggle AND
    # renderer AND procedural sky, via the host predicate) AND there's a real
    # destination to fly to. The set swap is HELD by a game-time delay = the
    # transit duration, so it lands when the transit ends (masked by the exit
    # flash); the begin/end actions drive the WarpVFX manager. Fail-open: the
    # begin/end hook calls are try/excepted, so a VFX failure never blocks the
    # swap chain.
    flythrough = (bool(_vfx_enabled and _vfx_enabled())
                  and not _module_is_empty(dest_module))
    if flythrough:
        src_v = _vfx_vantage_of(source) if (_vfx_vantage_of and source) else None
        dst_v = _vfx_vantage_of(dest_module) if _vfx_vantage_of else None
        heading = _warp_heading(src_v, dst_v)
        t_transit = _transit_duration(src_v, dst_v)
        total = _T_ALIGN + t_transit
        # Align start: remove control + slow + start VFX, then play the enter
        # SFX. The set-swap is HELD by a game-time delay = T_align + T_transit so
        # it lands when the transit ends (masked by the exit flash); placement +
        # teardown + exit SFX + VFX-end chain after it, firing on arrival.
        seq.AddAction(_WarpVfxBeginAction(ship, heading, _T_ALIGN, t_transit))
        seq.AppendAction(_WarpSoundAction("Enter Warp"))
        seq.AppendAction(ChangeRenderedSetAction_Create(dest_module), total)
        seq.AppendAction(_PlacePlayerAction(ship, dest_name, placement))
        seq.AppendAction(_ArriveFinalizeAction(source, ship))
        seq.AppendAction(_WarpSoundAction("Exit Warp"))
        seq.AppendAction(_WarpVfxEndAction())
        return seq

    seq.AddAction(ChangeRenderedSetAction_Create(dest_module))
    # Falsy destination => no set change/placement/teardown: the whole warp
    # degrades to "nothing happened" (BC's `if pcDestModule != None:` guard).
    # The per-action _do_play guards are the robust floor; skipping placement
    # and source teardown here keeps the player in its current set.
    if not _module_is_empty(dest_module):
        seq.AppendAction(_PlacePlayerAction(ship, dest_name, placement))
        seq.AppendAction(_ArriveFinalizeAction(source, ship))
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
