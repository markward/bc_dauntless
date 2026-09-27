"""The player's Set Course dash within one system (in-system-warp spec §2).

A Set Course whose destination region lies in the player's own mapped
system, and which names no mission or episode, does not take the tunnel:
the player flies the real system on a ``WarpFlight`` (engine/appc/
warp_flight.py) and drops out at the destination's arrival placement, at
rest, facing its travel direction; the arrival turn then swings it onto the
placement's rotation at its impulse turn rate (see the section at the end).
``warp.execute_warp`` forks here; everything else (rule C) keeps the tunnel.

Warp on Heading (``start_heading``) is the other dash: no destination and no
align -- it engages at once along the nose at HEADING_DASH_GUPS and runs
until a body ahead drops it out (at the body's region-arrival range, keeping
the impulse speed engaged at) or 0 / All Stop drops it out at rest.

Phases, all driven from ``tick`` once per frame:

* **align** -- the ship is held where it is and swung onto the path's first
  direction over ``warp._align_duration`` (the tunnel's own turn length);
* **engage** -- weapon loops silenced, ``WES_WARPING``, the flight begins,
  the button's queues start (``_on_engage_fx`` is the flash/sound hook);
* **flight** -- the flight moves the ship (~10 s: ``set_course_speed``);
* **drop-out** -- ``drop_out``, run once for a flight that ended for ANY
  reason (arrival, the 0 key, All Stop, or an AI order, which ends it
  through ``ShipClass._end_in_system_warp``).

A dash stopped during its align, or whose player dies (dying or dead, the
``ship_death._out_of_action`` test) at any point, is **cancelled** instead:
no hand-off, no ET_EXITED_WARP, no queue played -- and a dash that never
engaged hands the button's queues back, since none of them started.

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
                 queues, button=None):
        import App
        self.button = button            # takes the queues back if never engaged
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
#
# Weapon-loop silencing already happened at engage (warp._silence_ship_
# weapons, called from _engage() -- ruling R3 says Task 6 must not duplicate
# it). These two hooks own only the screen flash / dust-smear / nacelle-glow
# clock (engine.dash_vfx) and the departure/arrival sound, exactly as the
# tunnel's own _WarpSoundAction plays "Enter Warp" / "Exit Warp". Gated on
# warp._is_current_player like every other player-scene effect in warp.py --
# the dash is player-only today (spec §4 "NPCs: Player only for now"), so
# this is a defensive match to that convention rather than a live branch.

def _on_engage_fx(player) -> None:
    """Engage flash + "Enter Warp" (Task 6)."""
    from engine.appc import warp
    if not warp._is_current_player(player):
        return
    import App
    from engine import dash_vfx
    dash_vfx.get().engage(App.g_kUtopiaModule.GetGameTime())
    try:
        App.g_kSoundManager.PlaySound("Enter Warp")
    except Exception:
        pass


def _on_drop_out_fx(player) -> None:
    """Drop-out flash + "Exit Warp" (Task 6)."""
    from engine.appc import warp
    if not warp._is_current_player(player):
        return
    import App
    from engine import dash_vfx
    dash_vfx.get().drop_out(App.g_kUtopiaModule.GetGameTime())
    try:
        App.g_kSoundManager.PlaySound("Exit Warp")
    except Exception:
        pass


def _on_cancel_fx() -> None:
    """A dash that ends with no drop-out (cancelled; the player swapped
    away) drops its VFX at once: nothing else would ramp the dust smear cap
    and the nacelle glow back down. Not gated on the current player -- the
    clock only ever runs for the player's dash, and after a player swap the
    ship being cancelled is no longer the current player."""
    from engine import dash_vfx
    dash_vfx.reset()


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

def start_set_course(player, dest_set, placement_name, queues,
                     button=None) -> bool:
    """Plan the dash to ``dest_set``'s placement and begin its align.

    ``button`` is the warp button the queues were taken from: a dash
    cancelled before it engages hands them back to it (they never started).

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
    # No end_dir (Mark, live 2026-09-27): the path does not curve onto the
    # placement's forward -- the ship drops out facing its travel direction
    # and turns onto the placement at impulse afterwards (the arrival turn).
    path = plan_path(tuple(start[1:]), end, warp_flight.obstacles_for(player))
    if path.enters_body:
        _log_body_fallback(dest_set)
        return False

    cancel_arrival_turn(player)
    st = _Dash(dest_set, placement, wp, end, forward, path,
               {k: list((queues or {}).get(k, ())) for k in _QUEUE_KEYS},
               button)
    first = path.tangent_at(0.0)
    st.t_align = warp._align_duration(player, first)
    st.pos0 = player.GetTranslate()
    st.rot0 = player.GetWorldRotation()
    st.axis, st.angle = _turn_to(st.rot0.GetCol(1), first, st.rot0.GetCol(2))
    player.__dict__["_dash"] = st

    # The Helm has the conn (ruling R12): drop the targets and stand the
    # player's AI down exactly as the tunnel's _ClearTargetsAction does at
    # the start of its sequence -- clear FIRST, then stand down (see
    # warp._stand_down_player_ai for why the order matters) -- and drop any
    # stale motion setpoints, so nothing but the dash moves the ship from
    # here to the drop-out.
    warp._clear_all_targets(player)
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


def start_heading(player, queues, button=None) -> bool:
    """Warp on Heading: engage at once (no align) along the nose at
    HEADING_DASH_GUPS until a body ahead drops the flight out, keeping the
    impulse speed engaged at, or 0 / All Stop drops it out at rest.

    Works in any space set, mapped or not (Mark, 2026-09-27: features are
    consistent everywhere). An unmapped set flies on its own Planet/Sun
    objects (warp_flight.obstacles_for) with no regions, so no hand-off.
    Returns False -- nothing started, the queues go back on ``button`` --
    only when the player is in no set."""
    from engine.appc.warp_flight import WarpFlight
    from engine.systems import frames
    src = frames.containing_set(player) if player is not None else None
    if src is None:
        if button is not None:
            button.put_back_queues(queues or {})
        return False
    f = player.GetWorldRotation().GetCol(1)
    heading = (f.x, f.y, f.z)
    v = player.GetVelocity()
    engaged = v.x * f.x + v.y * f.y + v.z * f.z   # the forward impulse speed

    # Everything that can raise is built BEFORE the dash is stored on the
    # player, so a failure leaves no half-built dash behind.
    flight = WarpFlight(heading=heading, speed_policy="heading",
                        exit_policy="engaged_impulse", engaged_speed=engaged,
                        standoff_of=_heading_standoffs(player, heading))
    st = _Dash(None, None, None, None, heading, None,
               {k: list((queues or {}).get(k, ())) for k in _QUEUE_KEYS},
               button)
    cancel_arrival_turn(player)
    player.__dict__["_dash"] = st
    # Ruling R12, as at a Set Course press.
    from engine.appc import warp
    warp._clear_all_targets(player)
    warp._stand_down_player_ai(player)
    player._speed_setpoint = None
    player._target_angular_velocity_setpoint = None

    # (No enable_helm_menu here: unlike a Set Course press, the heading
    # press never greyed the Helm menu -- warp_button.engage.)
    from engine.appc import dash_helm
    dash_helm.sync(player)
    _engage(player, st, flight)
    return True


# R14: a cut-down standoff aims this far inside the region's sphere, so the
# drop point is not on its rim (where float rounding could put it outside).
SPHERE_INWARD_MARGIN_GU = 100.0


def _heading_standoffs(player, heading):
    """``standoff_of`` for the player's heading flight (rulings R1, R9, R14):
    from a body's centre, the distance to its owning region's arrival point
    (the region set's "Player Start", system coordinates) -- where the
    tunnel would frame it; else one radius above the surface (a star, a body
    whose region is not loaded). A body whose arrival range already holds the
    ship at engage (it starts there) uses radius + clearance instead, so the
    dash neither ends on its first tick nor passes through the body.
    Otherwise the arrival range is cut, when it has to be, so the drop point
    on this heading lands inside the region's sphere (``_sphere_standoff``).

    Computed once, at engage: the flight's ray never changes, so each drop
    point measured from the centre is the same from every point along it."""
    import App
    from engine.systems import frames, resolve
    from engine.systems.warp_path import clearance_gu
    f = frames.frame_of(frames.containing_set(player))
    m = (resolve.map_of(f.key[1])
         if f is not None and f.key[0] == "system" else None)
    here = frames.system_position(player)
    here = tuple(here[1:]) if here is not None else None
    table = {}
    for b in (m.bodies if m is not None else ()):
        if not b.owner_region:
            continue
        pSet = App.g_kSetManager.GetSet(b.owner_region)
        wp = pSet.GetObject(_FALLBACK_PLACEMENT) if pSet is not None else None
        arrival = frames.system_position(wp) if wp is not None else None
        if arrival is None:
            continue
        centre = tuple(float(c) for c in b.position_gu)
        sd = math.dist(centre, tuple(arrival[1:]))
        region = m.region(b.owner_region)
        if here is not None and sd >= math.dist(here, centre):
            sd = b.radius_gu + clearance_gu(b.radius_gu)
        elif here is not None and region is not None:
            sd = _sphere_standoff(here, heading, centre, b.radius_gu, sd,
                                  tuple(region.anchor_gu), region.radius_gu)
        table[b.name] = sd

    def standoff_of(obstacle):
        sd = table.get(obstacle.name)
        return 2.0 * obstacle.radius_gu if sd is None else sd
    return standoff_of


def _sphere_standoff(here, heading, centre, radius, arrival, anchor,
                     sphere_radius) -> float:
    """Ruling R14: the standoff for a body with the ray ``here + t*heading``
    fixed. The arrival range if its drop point is inside the region's sphere
    (shrunk by SPHERE_INWARD_MARGIN_GU); otherwise the LARGEST standoff below
    it, and >= radius + clearance, whose drop point is inside -- the drop
    point where the ray enters the shrunk sphere; otherwise (the ray misses
    the sphere, or enters it only nearer the body than radius + clearance)
    the arrival range, which then gets no hand-off. A body off the ray is
    never dropped at (warp_path.drop_out), so it keeps the arrival range."""
    from engine.systems.warp_path import clearance_gu
    h = heading
    v = [centre[i] - here[i] for i in range(3)]
    along = sum(v[i] * h[i] for i in range(3))
    lat2 = max(sum(c * c for c in v) - along * along, 0.0)
    if lat2 >= radius * radius:
        return arrival
    r = sphere_radius - SPHERE_INWARD_MARGIN_GU
    if r <= 0.0:
        return arrival

    def t_of(sd):                   # the drop point's distance along the ray
        return along - math.sqrt(max(sd * sd - lat2, 0.0))

    wv = [anchor[i] - here[i] for i in range(3)]
    b = sum(wv[i] * h[i] for i in range(3))
    c2 = sum(c * c for c in wv) - b * b
    if c2 > r * r:
        return arrival              # the ray misses the sphere
    half = math.sqrt(r * r - c2)
    t1, t2 = b - half, b + half
    t_arr = t_of(arrival)
    if t1 <= t_arr <= t2:
        return arrival              # already inside
    # A smaller standoff drops FURTHER along the ray; only a drop point short
    # of the sphere (t_arr < t1) can be moved into it, to its entry t1 --
    # and only while t1 is still before the centre.
    if t_arr > t2 or t1 > along:
        return arrival
    sd = math.sqrt((along - t1) ** 2 + lat2)
    if sd < radius + clearance_gu(radius):
        return arrival
    return sd


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
    drop-out once for a flight that has ended, whatever ended it; after a
    Set Course arrival, step the arrival turn."""
    st = _state(player)
    if st is None:
        _step_arrival_turn(player, dt)
        return
    from engine.appc import ship_death
    if ship_death._out_of_action(player):
        _cancel(player, st)
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


def _cancel(player, st) -> None:
    """End the dash with no drop-out: the player died (or a drop-out came
    during the align). No hand-off, no ET_EXITED_WARP, no flash, no queue
    played; a dash that never engaged hands its queues back to the button."""
    from engine.appc import dash_helm, warp_state
    from engine.appc.subsystems import WarpEngineSubsystem
    del player.__dict__["_dash"]
    if st.flight is None:
        if st.button is not None:
            st.button.put_back_queues(st.queues)
    else:
        if player._insystem_warp_transit is st.flight:
            player._end_in_system_warp("aborted")
        warp_state.set_state(player, WarpEngineSubsystem.WES_NOT_WARPING)
        _on_cancel_fx()
    dash_helm.sync(player)


def abandon(ship) -> None:
    """``ship`` stopped being the player mid-dash (RecreatePlayer, a
    QuickBattle ship swap): cancel its dash (``_cancel`` -- no hand-off, no
    ET_EXITED_WARP, queues back if it never engaged) and leave it at rest.
    Nothing else would end it: the host ticks only the current player's
    dash, and a heading flight in open space never ends on its own. An
    arrival turn in progress is dropped too."""
    cancel_arrival_turn(ship)
    st = _state(ship)
    if st is None:
        return
    _cancel(ship, st)
    ship._current_speed = 0.0
    ship.SetVelocity(TGPoint3(0.0, 0.0, 0.0))


def _engage(player, st, flight=None) -> None:
    """Begin the flight: the Set Course path at the end of its align, or the
    ``flight`` given (a heading dash, which has no align)."""
    from engine.appc import warp, warp_state
    from engine.appc.subsystems import WarpEngineSubsystem
    from engine.appc.warp_flight import WarpFlight
    if flight is None:
        turn = TGMatrix3().MakeRotation(st.angle, st.axis)
        player.SetMatrixRotation(turn.MultMatrix(st.rot0))
        flight = WarpFlight(target=(st.end, None),
                            speed_policy="set_course", exit_policy="rest")
        # The ship was held at the planned start through the align: fly the
        # path already planned rather than planning it a second time.
        flight._path = st.path
    warp._silence_ship_weapons(player)
    warp_state.set_state(player, WarpEngineSubsystem.WES_WARPING)
    st.flight = flight
    player.begin_warp_flight(flight)
    _play_engage_queues(st.queues)
    _on_engage_fx(player)


def _play_engage_queues(queues) -> None:
    import App
    from engine.appc import warp
    seq = App.TGSequence_Create()
    warp.queue_before(seq, queues)
    warp.queue_transit(seq, queues, None)
    seq.Play()


# ── drop-out ───────────────────────────────────────────────────────────────

def drop_out(player, reason) -> None:
    """End the dash where the ship is (or at the placement, on arrival):
    at rest; hand off to the region it stopped in (or post ET_EXITED_WARP
    alone); WES_NOT_WARPING; the Helm entries back; the "after" queue.
    A dash stopped during its align never engaged: it is cancelled
    (``_cancel``) and its queues go back on the button."""
    st = _state(player)
    if st is None:
        return
    if st.flight is None:
        _cancel(player, st)
        return
    del player.__dict__["_dash"]
    from engine.appc import dash_helm, warp_state
    from engine.appc.subsystems import WarpEngineSubsystem
    from engine.systems import frames, handoff
    if player._insystem_warp_transit is st.flight:
        player._end_in_system_warp(reason)
    # Exit at rest (a Set Course arrival, and every manual drop-out) -- except
    # a heading dash's body drop-out, where the flight has already left the
    # ship at its engaged impulse speed along the heading.
    if st.flight.ended_reason != "body":
        player._current_speed = 0.0
        player.SetVelocity(TGPoint3(0.0, 0.0, 0.0))

    src = frames.containing_set(player)
    if st.flight.ended_reason == "arrived":
        dest = st.dest_set
        # Onto the placement before any set event fires, so handlers read
        # the arrival pose; then exact in the destination's own frame.
        # The rotation is NOT snapped (Mark, live 2026-09-27): the ship keeps
        # its travel direction and turns onto the placement at impulse
        # afterwards (_begin_arrival_turn, below).
        local = frames.local_in(src, st.waypoint)
        if local is not None:
            player.SetTranslateXYZ(*local)
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

    if st.flight.ended_reason == "arrived":
        _begin_arrival_turn(player, st.waypoint)
    _on_drop_out_fx(player)
    warp_state.set_state(player, WarpEngineSubsystem.WES_NOT_WARPING)
    dash_helm.sync(player)
    if st.queues.get("after"):
        import App
        from engine.appc import warp
        seq = App.TGSequence_Create()
        warp.queue_after(seq, st.queues)
        seq.Play()


# ── the arrival turn ───────────────────────────────────────────────────────
#
# Mark, live 2026-09-27: "I would prefer the ship to exit warp and then turn
# to that spot at impulse so it doesnt look wierd. the player can chose to
# shake out of it if they wish by overriding the turn." A Set Course arrival
# drops out facing its travel direction; from the next frame the ship turns,
# at rest, onto the placement's rotation (forward GetCol(1), up GetCol(2))
# at its impulse turn rate -- the cap _PlayerControl flies manual turns at.
# Any steering or throttle input (_PlayerControl.apply), an AI order, a new
# dash, a warp, death or a player swap ends it. State on the player
# (``_arrival_turn``), like ``_dash``.

ARRIVAL_ALIGNED_RAD = math.radians(0.5)


def is_arrival_turning(player) -> bool:
    d = getattr(player, "__dict__", None) if player is not None else None
    return d is not None and d.get("_arrival_turn") is not None


def cancel_arrival_turn(player) -> None:
    """End the arrival turn where the ship is, if one is running."""
    d = getattr(player, "__dict__", None) if player is not None else None
    if d is not None:
        d.pop("_arrival_turn", None)


def _begin_arrival_turn(player, waypoint) -> None:
    target = waypoint.GetWorldRotation()
    if _rotation_to(player.GetWorldRotation(), target)[1] <= \
            ARRIVAL_ALIGNED_RAD:
        player.SetMatrixRotation(target)
        return
    player.__dict__["_arrival_turn"] = (target, player.GetContainingSet())


def _turn_rate(player) -> float:
    """The max angular rate _PlayerControl.apply turns the player at: the
    impulse engines' live max angular velocity, else (no authored angular
    limits) its fallback TURN_RATE_RAD_PER_S."""
    from engine.appc.ship_motion import _effective_motion
    em = _effective_motion(player)
    if em.has_angular:
        return em.max_ang_vel
    from engine.host_loop import _PlayerControl
    return _PlayerControl.TURN_RATE_RAD_PER_S


def _rotation_to(R, target):
    """(axis, angle) of the world-frame rotation D with D . R = target."""
    D = target.MultMatrix(R.Transpose())
    c = max(-1.0, min(1.0, (D.m00 + D.m11 + D.m22 - 1.0) / 2.0))
    angle = math.acos(c)
    axis = TGPoint3(D.m21 - D.m12, D.m02 - D.m20, D.m10 - D.m01)
    n = axis.Length()
    if n < 1e-6 and angle > math.pi / 2.0:
        # A half-turn: the axis is the column of (D + I)/2 with the largest
        # diagonal (D is symmetric there).
        k = max(range(3), key=lambda i: D.GetEntry(i, i))
        col = D.GetCol(k)
        v = [col.x, col.y, col.z]
        v[k] += 1.0
        axis = TGPoint3(*v)
        n = axis.Length()
    if n < 1e-12:
        return TGPoint3(0.0, 0.0, 1.0), 0.0
    return TGPoint3(axis.x / n, axis.y / n, axis.z / n), angle


def _step_arrival_turn(player, dt: float) -> None:
    turn = player.__dict__.get("_arrival_turn")
    if turn is None:
        return
    target, turn_set = turn
    from engine.appc import ship_death, warp_state
    from engine.appc.subsystems import WarpEngineSubsystem
    if (ship_death._out_of_action(player)
            or player.GetContainingSet() is not turn_set
            or (hasattr(player, "GetAI") and player.GetAI() is not None)
            or warp_state.get_state(player)
            != WarpEngineSubsystem.WES_NOT_WARPING):
        cancel_arrival_turn(player)
        return
    R = player.GetWorldRotation()
    axis, angle = _rotation_to(R, target)
    step = _turn_rate(player) * dt
    if angle <= step:
        player.SetMatrixRotation(target)
        cancel_arrival_turn(player)
    elif step > 0.0:
        player.SetMatrixRotation(
            TGMatrix3().MakeRotation(step, axis).MultMatrix(R))
    player.SetVelocity(TGPoint3(0.0, 0.0, 0.0))
