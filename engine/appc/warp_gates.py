"""Warp gating — point-in-time checks mirroring SDK WarpPressed.

warp_gate(ship) runs the same checks in the same order as
sdk/Build/scripts/Bridge/HelmMenuHandlers.py:WarpPressed and returns a
GateResult. on_warp_engage calls it before execute_warp; a denial speaks the
authentic CantWarp*/XO line (Helm AT_SAY_LINE, else subtitle). Nothing here
ever raises — an un-evaluable check is treated as not-blocking.

Spec: docs/superpowers/specs/2026-06-22-warp-gating-design.md
"""

# Host-supplied segment-vs-mesh test for the starbase check (Task 4).
# fn(starbase_ship, from_xyz_point, to_xyz_point) -> bool (True if the segment
# hits the starbase mesh). None => starbase check can't run (don't block).
_ray_collide_hook = None


def configure_gate_hooks(ray_collide=None):
    global _ray_collide_hook
    _ray_collide_hook = ray_collide


class GateResult:
    __slots__ = ("allowed", "deny_line", "silent")

    def __init__(self, allowed, deny_line=None, silent=False):
        self.allowed = allowed
        self.deny_line = deny_line
        self.silent = silent


def _safe(fn, ship):
    """Evaluate a predicate, treating any error as 'not blocking'."""
    try:
        return bool(fn(ship))
    except Exception:
        return False


def _impulse_off(ship):
    imp = ship.GetImpulseEngineSubsystem()
    return imp is not None and imp.GetPowerPercentageWanted() == 0.0


def _warp_disabled(ship):
    warp = ship.GetWarpEngineSubsystem()
    return warp is not None and bool(warp.IsDisabled())


def _warp_off(ship):
    warp = ship.GetWarpEngineSubsystem()
    return warp is not None and not warp.IsOn()


def _in_nebula(ship):
    return False  # Task 2


def _in_asteroid_field(ship):
    return False  # Task 3


def _near_starbase(ship):
    return False  # Task 4


def warp_gate(ship):
    """Return a GateResult for whether `ship` may warp, in WarpPressed order."""
    if ship is None:
        return GateResult(False, None, silent=True)
    # Impulse subsystem missing -> SDK CallNextHandler (proceed; not a block).
    if ship.GetImpulseEngineSubsystem() is None:
        pass
    elif _safe(_impulse_off, ship):
        return GateResult(False, "EngineeringNeedPowerToEngines")
    # Warp subsystem missing -> SDK silent return.
    if ship.GetWarpEngineSubsystem() is None:
        return GateResult(False, None, silent=True)
    if _safe(_warp_disabled, ship):
        return GateResult(False, "CantWarp1")
    if _safe(_warp_off, ship):
        return GateResult(False, "CantWarp5")
    if _safe(_in_nebula, ship):
        return GateResult(False, "CantWarp2")
    if _safe(_in_asteroid_field, ship):
        return GateResult(False, "CantWarp4")
    if _safe(_near_starbase, ship):
        return GateResult(False, "CantWarp3")
    return GateResult(True, None)


def speak_deny(ship, line_key):
    """Speak the deny line via the Helm officer (AT_SAY_LINE), falling back to a
    3s subtitle. Mirrors WarpPressed's dual path; never raises."""
    import App
    try:
        bridge = App.g_kSetManager.GetSet("bridge")
        helm = App.CharacterClass_GetObject(bridge, "Helm") if bridge else None
        if helm is not None:
            App.CharacterAction_Create(
                helm, App.CharacterAction.AT_SAY_LINE, line_key, None, 1).Play()
            return
    except Exception:
        pass
    try:
        db = App.g_kLocalizationManager.Load("data/TGL/Bridge Crew General.tgl")
        if db:
            seq = App.TGSequence_Create()
            sub = App.SubtitleAction_Create(db, line_key)
            sub.SetDuration(3.0)
            seq.AddAction(sub)
            seq.Play()
            App.g_kLocalizationManager.Unload(db)
    except Exception:
        pass
