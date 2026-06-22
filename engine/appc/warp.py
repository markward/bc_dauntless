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

# Name of the temporary empty set the player occupies WHILE in warp transit.
# The source system is torn down at burst and the player is parked here (no
# lights, no backdrops, no other ships) until the destination swap lands — so
# during transit nothing from the system left behind keeps simulating, firing,
# or lighting the scene. Mirrors BC's "warp set" (project_warp_mechanism_sdk).
_WARP_TRANSIT_SET_NAME = "_WarpTransit"

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
# K tuned so a mid-galaxy hop (~150 units) lands ≈ 20 s. Unmapped vantage (None
# on either side) => T_BASE (a short transit, no parallax). Scaled 4× over the
# original (T_MIN/T_MAX/T_BASE/K = 2/10/2/0.02) per live tuning — the streak
# phase reads too brief at the base values.
_T_MIN, _T_MAX, _T_BASE, _K = 8.0, 40.0, 8.0, 0.08

# Align/turn phase: the ship slows + swings onto the warp heading before the
# streak transit begins. The duration is derived from the actual turn angle and
# the ship's impulse-engine max angular velocity (so the turn respects the
# ship's real turn-rate limit — a big swing takes longer than a small one),
# clamped so a near-zero turn still has a brief beat and a 180 isn't endless.
_T_ALIGN_MIN, _T_ALIGN_MAX = 0.5, 8.0
_OMEGA_FALLBACK = 0.5   # rad/s (~29 deg/s) when no impulse subsystem reports one

# When the flash/whoosh occurs inside "Enter Warp.wav" (s from the clip start).
# The clip is 2.65s; the old fixed-1.5s align stayed in sync, so the flash sits
# ~1.5s in. The SFX is started t_align - this so the flash lands on the burst.
# Tunable to the real clip.
_SFX_ENTER_FLASH_AT = 1.5


def _align_duration(ship, heading):
    """Seconds to swing onto `heading` at the ship's max angular velocity."""
    try:
        fwd = ship.GetWorldRotation().GetCol(1)
        dot = fwd.x * heading[0] + fwd.y * heading[1] + fwd.z * heading[2]
    except Exception:
        return _T_ALIGN_MIN
    dot = -1.0 if dot < -1.0 else (1.0 if dot > 1.0 else dot)
    angle = math.acos(dot)            # radians, 0..pi
    omega = 0.0
    try:
        ies = ship.GetImpulseEngineSubsystem()
        if ies is not None:
            omega = ies.GetMaxAngularVelocity()
    except Exception:
        omega = 0.0
    if omega <= 1e-4:
        omega = _OMEGA_FALLBACK
    # The manager eases the turn with a smoothstep (peak rate ~1.5x the mean),
    # so stretch the window by 1.5 to keep the PEAK turn rate <= omega.
    t = 1.5 * angle / omega
    return _T_ALIGN_MIN if t < _T_ALIGN_MIN else (_T_ALIGN_MAX if t > _T_ALIGN_MAX else t)

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
    """Normalized galaxy-map direction toward the destination system. The source
    set is often NOT galaxy-mapped (mission sets aren't in the sector model), so
    a None source is treated as the galaxy origin — the ship still turns toward
    the real destination direction. Only a missing/zero destination falls back to
    default ship-forward (0, 1, 0)."""
    if dst_vantage is None:
        return (0.0, 1.0, 0.0)
    sx, sy, sz = src_vantage if src_vantage is not None else (0.0, 0.0, 0.0)
    dx = dst_vantage[0] - sx
    dy = dst_vantage[1] - sy
    dz = dst_vantage[2] - sz
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


def _clear_all_targets(ship) -> None:
    """Drop every target the instant warp engages: the player's current target
    + subsystem lock, and the whole target-list HUD (rows + persistent hint).

    Warping leaves the system — there is nothing to target. Mirrors the SDK's
    own ``ClearTargetList`` + ``ClearPersistentTarget`` pairing
    (Multiplayer/MissionShared.py:353-354). Control is removed for the warp, so
    no CycleTarget can re-populate the list before arrival. Fail-open: a failure
    here never blocks the warp.
    """
    try:
        if ship is not None:
            if hasattr(ship, "SetTarget"):
                ship.SetTarget(None)
            if hasattr(ship, "SetTargetSubsystem"):
                ship.SetTargetSubsystem(None)
    except Exception:
        pass
    try:
        from engine.appc.target_menu import STTargetMenu_GetTargetMenu
        menu = STTargetMenu_GetTargetMenu()
        if menu is not None:
            menu.ClearTargetList()
            menu.ClearPersistentTarget()
    except Exception:
        pass


class _ClearTargetsAction(TGAction):
    """Drop every target at warp engage. Runs on BOTH the flythrough and the
    instant hard-cut path (added first in each), so the target list is empty
    the instant warp begins regardless of the Modern-VFX toggle. Fail-open."""

    def __init__(self, ship):
        super().__init__()
        self._ship = ship

    def _do_play(self):
        _clear_all_targets(self._ship)


class _WarpVfxBeginAction(TGAction):
    """Align start: remove player control, slow the ship to a stop, and start
    the WarpVFX manager on the warp heading. Targets are cleared by the separate
    _ClearTargetsAction (added alongside this one). Every step is fail-open — a
    failure here never blocks the set-swap chain (control is restored on arrival
    by _ArriveFinalizeAction regardless)."""

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
        # Ship motion during warp is driven by the host's _PlayerControl warp
        # override (hold during align, burst during transit) — a ship-level
        # SetSpeed here is inert for the player and is intentionally omitted.
        if _vfx_start is not None:
            try:
                _vfx_start(*self._a)
            except Exception:
                pass
        try:
            import engine.dev_mode as _dev
            if _dev.is_enabled():
                h, ta, tt = self._a
                print("[warp] engaged: heading=(%.2f, %.2f, %.2f) "
                      "align=%.1fs transit=%.1fs" % (h[0], h[1], h[2], ta, tt),
                      flush=True)
        except Exception:
            pass


class _WarpVfxEndAction(TGAction):
    """Defensive late-stop for the WarpVFX manager. The manager self-deactivates
    after its post-arrival decel tail (the host drives the speed glide-down to 0
    over those final seconds); this action is scheduled to fire just after the
    tail as a belt-and-suspenders stop. Fail-open."""

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


class _WarpDepartAction(TGAction):
    """Fires at BURST (transit start): tear down the system being left behind.

    Silences every source-set ship's weapon loops, moves the player into a fresh
    empty transit set, makes that the rendered set (so lighting + backdrops fall
    to neutral — the source sun stops lighting the scene), and deletes the source
    set (render teardown + DeleteSet — its ships stop running AI/combat, so the
    firing the player could hear during transit goes silent). The held
    destination swap still lands at transit-end.

    Fail-open: each step is guarded, and _ArriveFinalizeAction tears the source
    down on arrival anyway (idempotent) if departure didn't complete."""

    def __init__(self, source_set, ship):
        super().__init__()
        self._source = source_set
        self._ship = ship

    def _do_play(self):
        import App
        from engine.appc.sets import SetClass_Create
        src = self._source
        ship = self._ship
        # 1. Silence looping weapon SFX on every source-set ship (incl. the
        #    player) before the set is deleted — otherwise a bank firing at the
        #    moment of warp loops on into transit / the new system.
        if src is not None:
            for obj in list(getattr(src, "_objects", {}).values()):
                _silence_ship_weapons(obj)
        # 2. Park the player in a fresh empty transit set and render that, so the
        #    lighting/backdrop aggregation (which keys off the rendered/player
        #    set) yields neutral defaults instead of the source system's sun.
        try:
            if App.g_kSetManager.GetSet(_WARP_TRANSIT_SET_NAME) is not None:
                App.g_kSetManager.DeleteSet(_WARP_TRANSIT_SET_NAME)
            transit = SetClass_Create()
            App.g_kSetManager.AddSet(transit, _WARP_TRANSIT_SET_NAME)
            if ship is not None:
                for s in list(App.g_kSetManager._sets.values()):
                    if s.GetObject(ship.GetName()) is ship:
                        s.RemoveObjectFromSet(ship.GetName())
                transit.AddObjectToSet(ship, ship.GetName())
            App.g_kSetManager.MakeRenderedSet(_WARP_TRANSIT_SET_NAME)
        except Exception:
            pass
        # 3. Tear the source system down (render teardown + DeleteSet). Guarded:
        #    a failure here leaves it for _ArriveFinalizeAction to finish.
        if src is not None:
            try:
                name = src.GetName()
                if _teardown_hook is not None:
                    _teardown_hook(src)
                App.g_kSetManager.DeleteSet(name)
            except Exception:
                pass


class _ArriveFinalizeAction(TGAction):
    """Silence weapon-fire loops, terminate the source set (render teardown +
    DeleteSet) if it still exists, clean up the warp-transit set, and return
    player control. Idempotent w.r.t. the source set so it is safe whether or not
    _WarpDepartAction already tore it down."""

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
        # Terminate the source set — but ONLY if it still exists (the flythrough
        # path tears it down earlier in _WarpDepartAction; this is the fallback
        # for the instant path and for a departure that failed open).
        if src is not None and App.g_kSetManager.GetSet(src.GetName()) is src:
            if App.g_kSetManager.GetRenderedSet() is not src:
                if _teardown_hook is not None:
                    _teardown_hook(src)
                App.g_kSetManager.DeleteSet(src.GetName())
        # Clean up the temporary warp-transit set (flythrough only; no-op on the
        # instant path). The player has been moved into the destination by
        # _PlacePlayerAction, so the transit set is now empty.
        transit = App.g_kSetManager.GetSet(_WARP_TRANSIT_SET_NAME)
        if transit is not None and App.g_kSetManager.GetRenderedSet() is not transit:
            App.g_kSetManager.DeleteSet(_WARP_TRANSIT_SET_NAME)
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
        t_align = _align_duration(ship, heading)
        total = t_align + t_transit
        # Align start: remove control + start VFX (root @ 0). The "Enter Warp"
        # SFX is a separate root scheduled so its in-file flash (~_SFX_ENTER_
        # FLASH_AT into the clip) lands on the BURST (= t_align), now that the
        # align length is angle-driven (the old fixed-1.5s align kept it in sync
        # by luck). The set-swap is a root HELD by total = t_align + t_transit so
        # it lands when the transit ends (masked by the exit flash); placement +
        # teardown + exit SFX + VFX-end chain after the swap, firing on arrival.
        seq.AddAction(_ClearTargetsAction(ship))
        seq.AddAction(_WarpVfxBeginAction(ship, heading, t_align, t_transit))
        enter_delay = t_align - _SFX_ENTER_FLASH_AT
        if enter_delay < 0.0:
            enter_delay = 0.0
        seq.AddAction(_WarpSoundAction("Enter Warp"), enter_delay)
        # At BURST (t_align): tear down the system being left behind and park the
        # player in an empty transit set, so during the held transit nothing from
        # the source system keeps firing or lighting the scene.
        seq.AddAction(_WarpDepartAction(source, ship), t_align)
        swap = ChangeRenderedSetAction_Create(dest_module)
        seq.AddAction(swap, total)
        seq.AppendAction(_PlacePlayerAction(ship, dest_name, placement))
        seq.AppendAction(_ArriveFinalizeAction(source, ship))
        seq.AppendAction(_WarpSoundAction("Exit Warp"))
        # The manager keeps running for _T_EXIT_DECEL seconds after arrival to
        # glide the ship from in-system warp speed down to 0; schedule the
        # defensive stop just past that tail (the manager also self-deactivates).
        from engine.warp_vfx import _T_EXIT_DECEL
        seq.AppendAction(_WarpVfxEndAction(), _T_EXIT_DECEL + 0.5)
        return seq

    # Falsy destination => no set change/placement/teardown: the whole warp
    # degrades to "nothing happened" (BC's `if pcDestModule != None:` guard).
    # The per-action _do_play guards are the robust floor; skipping placement
    # and source teardown here keeps the player in its current set. Targets are
    # only cleared when a real warp actually happens (real destination).
    if not _module_is_empty(dest_module):
        seq.AddAction(_ClearTargetsAction(ship))
    seq.AddAction(ChangeRenderedSetAction_Create(dest_module))
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
