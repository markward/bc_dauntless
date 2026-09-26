"""The player's Set Course dash within one system (in-system-warp spec §2).

A Set Course whose destination region lies in the player's own mapped
system, and which names no mission or episode, does not take the tunnel:
the player flies the real system on a ``WarpFlight`` (engine/appc/
warp_flight.py) and drops out at the destination's arrival placement, at
rest, facing where the tunnel would have left it. ``warp.execute_warp``
forks here; everything else (rule C) keeps the tunnel.

Phases, all driven from ``tick`` once per frame:

* **align** -- the ship is held where it is and swung onto the path's first
  direction over ``warp._align_duration`` (the tunnel's own turn length);
* **engage** -- weapon loops silenced, ``WES_WARPING``, the flight begins,
  the button's queues start (``_on_engage_fx`` is the flash/sound hook);
* **flight** -- the flight moves the ship (~10 s: ``set_course_speed``);
* **drop-out** -- ``drop_out``, run once for a flight that ended for ANY
  reason (arrival, the 0 key, All Stop, an AI order or death, which end it
  through ``ShipClass._end_in_system_warp``).

Hand-offs are deferred for the whole dash (engine/systems/handoff.py) and
done here at the drop-out, so the order is ET_EXITED_SET, ET_ENTERED_SET,
then ET_EXITED_WARP (spec §3).

Where the button's queues play (spec §2): "before" at engage; "before_during"
-> "during" -> "after_during" chained from engage with no hold (a dash has no
transit to hold); "after" at drop-out.

The dash's state lives on the player (``player.__dict__["_dash"]``), never
in a module global, so nothing outlives the ship.
"""
from __future__ import annotations

import math

from engine.appc.math import TGMatrix3, TGPoint3

_QUEUE_KEYS = ("before", "before_during", "during", "after_during", "after")
_FALLBACK_PLACEMENT = "Player Start"
_logged_body_fallback = False


class _Dash:
    """One dash in progress."""

    def __init__(self, dest_set, placement, waypoint, end, forward, path,
                 queues):
        import App
        self.dest_set = dest_set
        self.placement = placement
        self.waypoint = waypoint
        self.end = end                  # system coordinates
        self.forward = forward
        self.path = path
        self.queues = queues
        self.flight = None              # set at engage
        self.t0 = App.g_kUtopiaModule.GetGameTime()
        self.t_align = 0.0
        self.pos0 = None
        self.rot0 = None
        self.axis = None
        self.angle = 0.0


# ── hooks Task 6 fills (ruling R3) ─────────────────────────────────────────

def _on_engage_fx(player) -> None:
    """Engage flash + "Enter Warp" (Task 6)."""


def _on_drop_out_fx(player) -> None:
    """Drop-out flash + "Exit Warp" (Task 6)."""


# ── queries ────────────────────────────────────────────────────────────────

def _state(player):
    d = getattr(player, "__dict__", None)
    return d.get("_dash") if d is not None else None


def is_dashing(player) -> bool:
    """True from the Set Course press (align included) until the drop-out."""
    return player is not None and _state(player) is not None


def is_same_system_dash(player, dest_module, mission, episode) -> bool:
    """Whether a Set Course to ``dest_module`` dashes instead of tunnelling:
    the player is in a mapped region, the destination set is loaded and in
    the same system, and the course names no mission or episode (a mission
    change needs the transit -- rule C)."""
    if mission or episode or player is None:
        return False
    import App
    from engine.appc import warp
    from engine.systems import frames, region_hooks, resolve
    src = frames.containing_set(player)
    if src is None or not region_hooks.is_mapped(src):
        return False
    system = resolve.system_of(src.GetName())
    dest_name = warp._set_name_from_module(dest_module)
    if system is None or dest_name is None:
        return False
    if resolve.system_of(dest_name) != system:
        return False
    return App.g_kSetManager.GetSet(dest_name) is not None


# ── start ──────────────────────────────────────────────────────────────────

def start_set_course(player, dest_set, placement_name, queues) -> bool:
    """Plan the dash to ``dest_set``'s placement and begin its align.

    Returns False -- nothing started, the caller takes the tunnel -- when
    there is no placement to arrive at or the planner could only return a
    path that enters a body (``WarpPath.enters_body``)."""
    from engine.appc import warp, warp_flight
    from engine.systems import frames
    from engine.systems.warp_path import plan_path
    if dest_set is None:
        return False
    placement = placement_name or _FALLBACK_PLACEMENT
    wp = dest_set.GetObject(placement)
    if wp is None:
        placement = _FALLBACK_PLACEMENT
        wp = dest_set.GetObject(placement)
    wp_sys = frames.system_position(wp) if wp is not None else None
    start = frames.system_position(player)
    if wp_sys is None or start is None:
        return False
    end = tuple(wp_sys[1:])
    f = wp.GetWorldRotation().GetCol(1)
    forward = (f.x, f.y, f.z)
    path = plan_path(tuple(start[1:]), end, warp_flight.obstacles_for(player),
                     end_dir=forward)
    if path.enters_body:
        _log_body_fallback(dest_set)
        return False

    st = _Dash(dest_set, placement, wp, end, forward, path,
               {k: list((queues or {}).get(k, ())) for k in _QUEUE_KEYS})
    first = path.tangent_at(0.0)
    st.t_align = warp._align_duration(player, first)
    st.pos0 = player.GetTranslate()
    st.rot0 = player.GetWorldRotation()
    st.axis, st.angle = _turn_to(st.rot0.GetCol(1), first, st.rot0.GetCol(2))
    player.__dict__["_dash"] = st

    # The Helm has the conn: stand the player's AI down (the tunnel does the
    # same at engage) and drop any stale motion setpoints, so nothing but
    # the dash moves the ship from here to the drop-out.
    warp._stand_down_player_ai(player)
    player._speed_setpoint = None
    player._target_angular_velocity_setpoint = None
    player.SetVelocity(TGPoint3(0.0, 0.0, 0.0))

    # warp_button.engage greyed the whole Helm menu (WarpPressed's
    # SetDisabled); a dash disables only its entries (dash_helm).
    from engine import bridge_officers
    from engine.appc import dash_helm
    bridge_officers.enable_helm_menu()
    dash_helm.sync(player)
    return True


def _log_body_fallback(dest_set) -> None:
    global _logged_body_fallback
    from engine import dev_mode
    if dev_mode.is_enabled() and not _logged_body_fallback:
        _logged_body_fallback = True
        print("[dash] no body-free path to %s; taking the tunnel"
              % dest_set.GetName(), flush=True)


def _turn_to(fwd, target, up):
    """(axis, angle) of the world-frame rotation taking ``fwd`` onto
    ``target``; a half-turn pivots about the ship's up."""
    t = TGPoint3(*target)
    dot = max(-1.0, min(1.0, fwd.x * t.x + fwd.y * t.y + fwd.z * t.z))
    angle = math.acos(dot)
    axis = TGPoint3(fwd.y * t.z - fwd.z * t.y, fwd.z * t.x - fwd.x * t.z,
                    fwd.x * t.y - fwd.y * t.x)
    n = axis.Length()
    if n < 1e-9:
        axis = TGPoint3(up.x, up.y, up.z)
        n = axis.Length()
    return TGPoint3(axis.x / n, axis.y / n, axis.z / n), angle


# ── per frame ──────────────────────────────────────────────────────────────

def tick(player, dt: float) -> None:
    """Advance the align (game time), engage when it completes, and run the
    drop-out once for a flight that has ended, whatever ended it."""
    st = _state(player)
    if st is None:
        return
    if st.flight is None:
        import App
        s = (App.g_kUtopiaModule.GetGameTime() - st.t0) / max(st.t_align, 1e-9)
        if s >= 1.0:
            _engage(player, st)
        else:
            _align(player, st, s)
        return
    if st.flight.ended_reason is not None or \
            player._insystem_warp_transit is not st.flight:
        drop_out(player, st.flight.ended_reason or "aborted")


def _align(player, st, s) -> None:
    """Hold position; swing onto the path's first direction, eased with the
    same smoothstep the tunnel's turn uses."""
    e = s * s * (3.0 - 2.0 * s)
    turn = TGMatrix3().MakeRotation(st.angle * e, st.axis)
    player.SetMatrixRotation(turn.MultMatrix(st.rot0))
    p = st.pos0
    player.SetTranslateXYZ(p.x, p.y, p.z)
    player.SetVelocity(TGPoint3(0.0, 0.0, 0.0))


def _engage(player, st) -> None:
    from engine.appc import warp, warp_state
    from engine.appc.subsystems import WarpEngineSubsystem
    from engine.appc.warp_flight import WarpFlight
    turn = TGMatrix3().MakeRotation(st.angle, st.axis)
    player.SetMatrixRotation(turn.MultMatrix(st.rot0))
    warp._silence_ship_weapons(player)
    warp_state.set_state(player, WarpEngineSubsystem.WES_WARPING)
    flight = WarpFlight(target=(st.end, st.forward), speed_policy="set_course",
                        exit_policy="rest")
    # The ship was held at the planned start through the align: fly the
    # path already planned rather than planning it a second time.
    flight._path = st.path
    st.flight = flight
    player.begin_warp_flight(flight)
    _play_engage_queues(st.queues)
    _on_engage_fx(player)


def _play_engage_queues(queues) -> None:
    import App
    seq = App.TGSequence_Create()
    for action, delay in queues.get("before", ()):
        seq.AddAction(action, delay)
    prev = None
    for key in ("before_during", "during", "after_during"):
        for action, delay in queues.get(key, ()):
            if prev is None:
                seq.AddAction(action, delay)
            else:
                seq.AddAction(action, prev, delay)
            prev = action
    seq.Play()


# ── drop-out ───────────────────────────────────────────────────────────────

def drop_out(player, reason) -> None:
    """End the dash where the ship is (or at the placement, on arrival):
    at rest; hand off to the region it stopped in (or post ET_EXITED_WARP
    alone); WES_NOT_WARPING; the Helm entries back; the "after" queue.
    A dash cancelled during its align never engaged: it only restores."""
    st = _state(player)
    if st is None:
        return
    del player.__dict__["_dash"]
    from engine.appc import dash_helm, warp_state
    from engine.appc.subsystems import WarpEngineSubsystem
    from engine.systems import frames, handoff
    if st.flight is None:
        dash_helm.sync(player)
        return
    if player._insystem_warp_transit is st.flight:
        player._end_in_system_warp(reason)
    # Exit at rest (this flight's exit policy, and the manual drop-out's).
    player._current_speed = 0.0
    player.SetVelocity(TGPoint3(0.0, 0.0, 0.0))

    src = frames.containing_set(player)
    if st.flight.ended_reason == "arrived":
        dest = st.dest_set
        # Onto the placement before any set event fires, so handlers read
        # the arrival pose; then exact in the destination's own frame.
        local = frames.local_in(src, st.waypoint)
        if local is not None:
            player.SetTranslateXYZ(*local)
        player.SetMatrixRotation(st.waypoint.GetWorldRotation())
        if dest is not src:
            handoff.hand_off(player, dest)
            q = st.waypoint.GetWorldLocation()
            player.SetTranslateXYZ(q.x, q.y, q.z)
        else:
            handoff.post_exited_warp(player)
    else:
        region = handoff.region_at(player)
        if region is not None and region is not src:
            handoff.hand_off(player, region)
        else:
            handoff.post_exited_warp(player)

    _on_drop_out_fx(player)
    warp_state.set_state(player, WarpEngineSubsystem.WES_NOT_WARPING)
    dash_helm.sync(player)
    after = st.queues.get("after", ())
    if after:
        import App
        seq = App.TGSequence_Create()
        for action, delay in after:
            seq.AppendAction(action, delay)
        seq.Play()
