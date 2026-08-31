import sys
import traceback
from engine.core.ids import TGObject
from engine.core import stub_telemetry

# Event type IDs.  SDK uses int constants from App.py; here we pick a stable
# value that won't collide with the SDK's ET_INPUT_FIRE_* range (those are
# Appc-side constants exposed via App.py:13834+).
ET_KEYBOARD_EVENT: int = 0x1000
# BC's raw per-key window event (sdk/Build/scripts/App.py:13224). Distinct from
# ET_KEYBOARD_EVENT above: that one is our internal broadcast into
# KeyboardBinding; this one is what BC delivers down the window chain and what
# SDK scripts hook via AddPythonFuncHandlerForInstance (E1M1.CrewIntros:1971,
# E1M1.RemoveSkipHandler:2479).
#
# REAL BC value, measured, not invented — read out of the ORIGINAL GAME:
#   tools/probes/results/q13_constants_battle.txt:459
#     App.ET_KEYBOARD = 196610 (0x30002) int
#   tools/probes/results/ghidra_export/stbc_constants.csv:449
#     App.ET_KEYBOARD,module,,ET_KEYBOARD,int,196610,0x30002,196610 (0x30002)
ET_KEYBOARD: int = 0x30002
# REAL BC values, measured, not invented -- q13 dump
# (tools/probes/results/ghidra_export/stbc_constants.csv:653,648):
#   App.ET_WEAPON_HIT,module,,ET_WEAPON_HIT,int,8388708,0x800064
#   App.ET_WARP_BUTTON_PRESSED,module,,ET_WARP_BUTTON_PRESSED,int,8388807,0x8000c7
# Corrected here (not just via App.py's CORRECT_EXISTING table) because
# App.py imports these names FROM this module -- fixing only the App
# namespace copy would leave App.ET_WEAPON_HIT != events.ET_WEAPON_HIT,
# so a handler registered through one module would never receive an event
# posted through the other. Previously invented as 0x1100 / 0x1200.
ET_WEAPON_HIT:     int = 0x800064
ET_WARP_BUTTON_PRESSED: int = 0x8000C7

# ── Torpedo events — REAL BC values, measured, not invented ────────────────
# Both were read out of the ORIGINAL GAME by probe q12
# (tools/probes/results/q12_torpedo_events.txt; runbook
# docs/instrumented_experiments/2026-07-12-torpedo-event-probe.md).  ET_TORPEDO_RELOAD
# previously held an invented 0x1322 because we could not measure the real one.
#
#   ET_TORPEDO_RELOAD  Source = None (BC posts NO source).  Destination = the TUBE.
#   ET_TORPEDO_FIRED   Source = the TORPEDO PROJECTILE.     Destination = the TUBE.
#
# The destination of ET_TORPEDO_FIRED is load-bearing AND dangerous:
# Maelstrom/Episode7/Episode7.py:88-115 DESTROYS pEvent.GetDestination() on a 10%
# roll (the E7M1 phased-plasma story beat).  Post it with the wrong destination and
# the game destroys the wrong subsystem.  q12 also proved it fires for ORDINARY
# photons, so the Phased-Plasma filter is in Episode7's handler, not the engine.
ET_TORPEDO_RELOAD: int = 0x00800065
ET_TORPEDO_FIRED:  int = 0x00800066

# ── Weapon-fire events — ids from decompiled stbc.exe (weapon-firing-
# mechanics.md §1.5/§2.4; RE-tier evidence, not SDK inference).
#   ET_WEAPON_FIRED          posted by TorpedoTube fire (AFTER ET_TORPEDO_FIRED,
#                            BC's order) and by phaser first-shot (beam start).
#                            Bound to (weapon, owner ship). SDK name: App.py:12958.
#   ET_WEAPON_FIRE_FAILED    posted when a targeted torpedo fire fails the
#                            aim-point resolve or the ±30° cone (0x00800037).
#                            No SDK symbol; no shipped script listens — defined
#                            for fidelity + mod surface.
#   ET_TORPEDO_AMMO_CONSUMED 0x00800067, posted on torpedo fire ONLY when the
#                            firing ship is the player ship (BC locality gate).
#                            CONFIRMED 2026-08-31 by the q13 constant sweep:
#                            this RE'd value equals BC's own published
#                            App.ET_PLAYER_TORPEDO_COUNT_CHANGED (also
#                            0x800067) -- independent corroboration that the
#                            player-only gate above is the real behaviour;
#                            only the NAME here was ours.
ET_WEAPON_FIRED:           int = 0x0080007C
# The q13 dump shows BC has no distinct "fire failed" event: 0x00800037 IS
# ET_CANT_FIRE.  Keep the descriptive name as an alias rather than a second
# constant, so the two can never drift apart.
ET_WEAPON_FIRE_FAILED:     int = 0x00800037  # == App.ET_CANT_FIRE
ET_TORPEDO_AMMO_CONSUMED:  int = 0x00800067

# ── Player torpedo-type switch — REAL BC value from the q13 live constant dump
# (tools/probes/results/q13_constants_battle.txt:523,
# `App.ET_PLAYER_TORPEDO_TYPE_CHANGED = 8388712 (0x800068)`).  Note it completes
# the measured torpedo cluster above: ...65 reload, ...66 fired, ...67
# ammo-consumed, ...68 type-changed.
#
#   Source = the TORPEDO SYSTEM (Bridge/TacticalCharacterHandlers.py:270 casts it
#            with TorpedoSystem_Cast and reads GetNumAmmoTypes /
#            GetCurrentAmmoType off it).
#   Destination = the SHIP, because the SDK registers on the player INSTANCE
#            (TacticalCharacterHandlers.py:59, inside AttachMenuToTactical, which
#            Bridge/Characters/Felix.py:187 calls at bridge load).
#
# Posted only for the PLAYER's ship and only on a real change — see
# weapon_subsystems.TorpedoSystem._announce_player_type_change for why both gates
# matter.  Felix's callout is AT_SAY_LINE "LoadingPhoton" / "LoadingQuantum" /
# "LoadingTorps", or "PhotonsOnlyDaunt" on a single-type Galaxy.
ET_PLAYER_TORPEDO_TYPE_CHANGED: int = 0x00800068

# ── Friendly-fire events — REAL BC values from the q13 live constant dump
# (tools/probes/results/q13_constants_menu.txt:364-366).  MissionLib's
# FriendlyFireHandler raises REPORT when the accumulator crosses a warning
# point and GAME_OVER when it crosses the tolerance.
ET_FRIENDLY_FIRE_DAMAGE:    int = 0x00800104
ET_FRIENDLY_FIRE_REPORT:    int = 0x00800105
ET_FRIENDLY_FIRE_GAME_OVER: int = 0x00800107

# SPACE-bar bridge/tactical toggle. App.py re-exports this name (missions
# reference it as App.ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL when registering
# TacticalToggleHandler — E1M1.py:858, E1M2.py:1155).
#
# REAL BC value, measured, not invented -- q13 dump
# (tools/probes/results/ghidra_export/stbc_constants.csv:425):
#   App.ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL,module,,...,int,8389784,0x800498
# The old comment here claimed "must stay in sync with the SDK" as if 1055
# were that synced value -- it was invented and simply never collided with
# anything else in this shim.  Corrected here (not just via App.py's
# CORRECT_EXISTING table) for the same reason as ET_WEAPON_HIT above: App.py
# imports this name FROM this module.
ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL = 0x800498


class TGEvent(TGObject):
    def __init__(self):
        super().__init__()
        self._event_type: int = 0
        self._destination: "TGEventHandlerObject | None" = None
        self._source: "TGObject | None" = None
        self._cstring: str = ""
        # BC's TGIEvent handled flag — see SetHandled below. Eager init so
        # TGObject.__getattr__ can never vend a truthy _Stub for it.
        self._handled: int = 0

    def SetHandled(self) -> None:
        """Mark this event as consumed, BC's TGIEvent.SetHandled
        (sdk/Build/scripts/App.py:1007).

        This is the veto that stops one keystroke being acted on twice. A
        window handler that translates a key through its OWN table calls it
        (InterfaceHandlers.TriggerKeyboardEvents:58), and the callers that come
        after — the global keyboard binding
        (CinematicInterfaceHandlers.HandleKeyboard:117), the next handler in
        the window chain (:121) — skip their work when it is set.

        Lives on TGEvent, not TGKeyboardEvent: BC binds it on TGIEvent, the
        base interface-event class, and the SDK calls it on mouse button
        events too (CinematicInterfaceHandlers:173,
        TacticalControlHandlers:72).

        There is no ClearHandled in BC's surface, and events are per-dispatch
        objects, so the flag is one-way for an event's lifetime.
        """
        self._handled = 1

    def EventHandled(self) -> int:
        """1 if some handler consumed this event, else 0 — BC's
        TGIEvent.EventHandled (sdk/Build/scripts/App.py:1006).

        MUST be a real int. The SDK reads it BOTH ways: `== 0`
        (BridgeHandlers:368, CharacterMenuInterfaceHandlers:76,
        TacticalControlHandlers:86, CinematicInterfaceHandlers:117) and as a
        bare truth test (`if not pEvent.EventHandled():` —
        CinematicInterfaceHandlers:121, MapModeInterfaceHandlers:93,
        MultiplayerInterfaceHandlers:57). A `_Stub` answer is truthy AND
        int()s to 0, so it gets each of those two shapes wrong in the
        OPPOSITE direction — see CLAUDE.md's truthiness/coercion tables.
        """
        return self._handled

    def SetCString(self, value) -> None:
        """String payload carried by the event.

        Load-bearing for music: DynamicMusic.MusicDone (DynamicMusic.py:121)
        gates its queue advance on
        `pEvent.GetCString() == dsMusicTypes[sCurrentMusicType]`. Without a real
        string here, GetCString resolved to a truthy `_Stub`, the comparison was
        never equal, ProcessQueue() never ran and the playlist stalled on its
        first track — silently, with music still audible.
        """
        self._cstring = "" if value is None else str(value)

    def GetCString(self) -> str:
        """Must return a real str, never a `_Stub`: callers compare it to a
        string, and a stub compares unequal to everything."""
        return self._cstring

    def SetEventType(self, event_type: int) -> None:
        self._event_type = event_type

    def GetEventType(self) -> int:
        return self._event_type

    def SetDestination(self, dest: "TGEventHandlerObject") -> None:
        self._destination = dest

    def GetDestination(self) -> "TGEventHandlerObject | None":
        return self._destination

    def SetSource(self, source: "TGObject") -> None:
        self._source = source

    def GetSource(self) -> "TGObject | None":
        return self._source


def TGEvent_Create() -> TGEvent:
    return TGEvent()


class WaypointEvent(TGEvent):
    """Waypoint-arrival event — carries the placement the ship just reached.

    Emitted by SDK script, not by the engine: AI/PlainAI/FollowWaypoints.py:278
    builds one per arrival, sets destination (the ship), type
    (ET_AI_REACHED_WAYPOINT) and placement (the Waypoint), then broadcasts via
    g_kEventManager.AddEvent.

    Consumers read BOTH halves back — Conditions/ConditionReachedWaypoint.py:47
    matches `GetDestination()` against its watched ship and
    `GetPlacement().GetName()` against its watched waypoint name — so the
    placement must round-trip as the real object, not a name.

    Everything except the placement is inherited: TGEvent already carries the
    event type and destination.
    """

    def __init__(self):
        super().__init__()
        self._placement: "TGObject | None" = None

    def SetPlacement(self, placement: "TGObject") -> None:
        self._placement = placement

    def GetPlacement(self) -> "TGObject | None":
        return self._placement


def WaypointEvent_Create() -> WaypointEvent:
    return WaypointEvent()


class TGBoolEvent(TGEvent):
    """Boolean-carrying event subclass.  Used by ET_INPUT_FIRE_* events to
    signal bFiring=1 (start) / bFiring=0 (stop).  See sdk/Build/scripts/
    TacticalInterfaceHandlers.py:391 — FireWeapons reads pEvent.GetBool()."""
    def __init__(self):
        super().__init__()
        self._value: int = 0

    def SetBool(self, v) -> None:
        self._value = 1 if v else 0

    def GetBool(self) -> int:
        return self._value


def TGBoolEvent_Create() -> TGBoolEvent:
    return TGBoolEvent()


class CollisionEvent(TGEvent):
    """Carries the contact points and force of an object collision
    (``ET_OBJECT_COLLISION``).

    Consumers: ``Effects.CollisionEffect`` spawns an explosion at every point
    and plays the collision sound; ``MissionLib.FriendlyFireCollisionHandler``
    ends the game if you ram a friendly; E7M2's ``ShipsCollided`` is a
    per-instance handler.

    Shape is from the clean-room reference (grade reviewed-not-tested, read
    from the binary): ``sizeof 0x44``, an embedded NiTArray of ``NiPoint3*``
    plus a float collision force at +0x40, with ``GetNumPoints`` returning
    ``m_uiESize`` (+0x38). Elements are pointers to separate 0xc-byte
    allocations, so a point handed in is copied rather than aliased.

    **At most two points.** The producer (0x00594840) stores a lone contact as
    itself; with more than one it keeps the pair with the GREATEST SEPARATION
    and discards the rest — manifold reduction, retaining the widest span of
    the contact patch. That reduction is also the evidence BC's collision is
    shape-aware: sphere-vs-sphere yields exactly one contact, so there would be
    no longer list to reduce. Our own detection is still a single sphere pair
    and supplies one point; the rule is implemented now so it stays correct by
    construction once per-mesh bounds land.
    """

    MAX_POINTS = 2

    def __init__(self):
        super().__init__()
        self._points: list = []
        self._force: float = 0.0

    def SetPoints(self, points) -> None:
        """Install the gathered contact set, reduced BC's way."""
        from engine.appc.math import TGPoint3
        pts = [TGPoint3(p.x, p.y, p.z) for p in points]   # copy, never alias
        if len(pts) > self.MAX_POINTS:
            pts = list(self._widest_pair(pts))
        self._points = pts

    @staticmethod
    def _widest_pair(pts):
        """The two points furthest apart. O(n^2) over a contact set that BC
        itself keeps tiny — clarity beats cleverness here."""
        best = (pts[0], pts[1])
        best_d2 = -1.0
        for i in range(len(pts)):
            for k in range(i + 1, len(pts)):
                dx = pts[i].x - pts[k].x
                dy = pts[i].y - pts[k].y
                dz = pts[i].z - pts[k].z
                d2 = dx * dx + dy * dy + dz * dz
                if d2 > best_d2:
                    best_d2 = d2
                    best = (pts[i], pts[k])
        return best

    def GetNumPoints(self) -> int:
        return len(self._points)

    def GetPoint(self, index):
        """Contact point `index` in world space, as a copy.

        BC bounds-checks neither the index nor the slot — an out-of-range read
        is a fault, not an error return. Raising is the faithful analogue; what
        must NOT happen is handing back something truthy that reads as a valid
        point. Every SDK caller iterates ``range(GetNumPoints())``.
        """
        from engine.appc.math import TGPoint3
        p = self._points[int(index)]          # IndexError is the contract
        return TGPoint3(p.x, p.y, p.z)

    def SetCollisionForce(self, f) -> None:
        self._force = float(f)

    def GetCollisionForce(self) -> float:
        return self._force


def CollisionEvent_Create() -> CollisionEvent:
    return CollisionEvent()


class TGKeyboardEvent(TGEvent):
    """Carries a unicode key code + key state (KS_KEYDOWN / KS_KEYUP).
    Generated by g_kInputManager when a registered key transitions; consumed
    by g_kKeyboardBinding which translates it into ET_INPUT_FIRE_* events.
    """
    # q13-measured values (constants_generated.py CLASS_CONSTANTS
    # ["TGKeyboardEvent"]): KS_NORMAL == 0, KS_KEYDOWN == 1, KS_KEYUP == 2.
    # KS_KEYREPEAT is dauntless-only (BC's dump has no such name); it keeps a
    # value outside 0-2 so it cannot collide with a real measured state.
    KS_NORMAL    = 0   # character-input event (e.g. printable keys)
    KS_KEYDOWN   = 1
    KS_KEYUP     = 2
    KS_KEYREPEAT = 3

    def __init__(self):
        super().__init__()
        self._event_type = ET_KEYBOARD_EVENT
        self._unicode_key: int = 0
        self._key_state: int = 0

    def SetUnicodeKey(self, k) -> None:
        self._unicode_key = int(k)

    def GetUnicodeKey(self) -> int:
        return self._unicode_key

    # BC's published names (sdk/Build/scripts/App.py:1062-1063). SDK scripts
    # call the bare forms (E1M1.SkipOpeningSequence, CinematicInterfaceHandlers
    # .HandleKeyboard); our own engine code and tests use the *Key forms. Both
    # must resolve or one side silently gets a _Stub.
    def SetUnicode(self, k) -> None:
        self.SetUnicodeKey(k)

    def GetUnicode(self) -> int:
        return self.GetUnicodeKey()

    def SetKeyState(self, s) -> None:
        self._key_state = int(s)

    def GetKeyState(self) -> int:
        return self._key_state


class WeaponHitEvent(TGEvent):
    """Weapon-impact event.  Broadcast by engine.appc.combat.apply_hit
    after damage is routed.  Mission scripts subscribe to ET_WEAPON_HIT
    (per-ship or broadcast) to react — e.g. MissionLib.FriendlyFireHandler
    triggers XO dialogue when the player damages a friendly NPC.

    Inherits TGEvent's _source / Set/GetSource for the firing ship; the
    weapon-specific surface adds target, damage, hit-point, subsystem,
    surface normal, splash radius (the radius the attribution resolver
    used for this hit), and a hull-vs-shield flag.

    `IsHullHit()` returns 1 when the hit reached the hull and 0 when the
    shield facing absorbed it. SDK conditions Conditions/ConditionAttacked
    and Conditions/ConditionAttackedBy read it to split hull damage from
    shield damage (1 → AddShipDamage, 0 → AddShieldDamage).

    `GetWeaponType()` returns one of PHASER / TORPEDO / TRACTOR_BEAM — the
    three values the real engine exposes, read off the live game by probe q13
    (tools/probes/results/q13_constants_menu.txt:4059-4062).  MissionLib's
    FriendlyFireHandler excludes TRACTOR_BEAM hits from the friendly-fire
    accumulator (you tow friendlies); E3M1.AmagonHit gates a mission beat on
    PHASER and E8M2.WeaponHitMatan on TORPEDO — the latter two off the CLASS
    (App.WeaponHitEvent.PHASER), which is why these are real class attributes.
    """
    # Engine weapon-type enum — exact values from the q13 dump. Do not invent.
    PHASER       = 0
    TORPEDO      = 1
    TRACTOR_BEAM = 2
    # OURS, not BC's: kinetic hits (ship-on-ship collisions, warp-core-breach
    # shockwaves) are not weapon fire and have no engine enum value. They must
    # not masquerade as a phaser — E3M1 advances a mission beat on
    # `GetWeaponType() == PHASER`, so a ram would falsely trip it. A negative
    # sentinel matches none of the three, which also lets MissionLib's
    # `not (type == TRACTOR_BEAM)` friendly-fire check count ram damage.
    NON_WEAPON   = -1

    def __init__(self, is_hull_hit=False):
        super().__init__()
        self._event_type = ET_WEAPON_HIT
        self._target = None
        self._damage: float = 0.0
        self._hit_point = None
        self._subsystem = None
        self._normal = None
        self._radius: float = 0.0
        self._is_hull_hit: int = 1 if is_hull_hit else 0
        self._weapon_type: int = self.NON_WEAPON

    def GetTarget(self):              return self._target
    def SetTarget(self, tgt) -> None: self._target = tgt
    def GetDamage(self) -> float:     return self._damage
    def SetDamage(self, v) -> None:   self._damage = float(v)
    def GetHitPoint(self):            return self._hit_point
    def SetHitPoint(self, p) -> None: self._hit_point = p
    def GetSubsystem(self):           return self._subsystem
    def SetSubsystem(self, s) -> None: self._subsystem = s
    def GetNormal(self):              return self._normal
    def SetNormal(self, n) -> None:   self._normal = n
    def GetRadius(self) -> float:     return self._radius
    def SetRadius(self, r) -> None:   self._radius = float(r)

    def GetWeaponType(self) -> int:
        """PHASER / TORPEDO / TRACTOR_BEAM, or NON_WEAPON for a kinetic hit."""
        return self._weapon_type
    def SetWeaponType(self, t) -> None: self._weapon_type = int(t)

    def IsHullHit(self) -> int:
        """1 if the hit reached the hull, 0 if shields absorbed it.
        Read by Conditions/ConditionAttacked + ConditionAttackedBy."""
        return self._is_hull_hit
    def SetHullHit(self, v) -> None:  self._is_hull_hit = 1 if v else 0

    def GetFiringObject(self):
        """SDK alias for GetSource() — SelectTarget's DamageEvent
        handler reads via GetFiringObject."""
        return self.GetSource()


class ObjectExplodingEvent(TGEvent):
    """Object-started-exploding event.  Broadcast by engine.appc.ship_death
    when a ship begins its death throes (ET_OBJECT_EXPLODING).  Mission scripts
    subscribe (per-mission or broadcast) to detect kills — e.g.
    MissionLib.ObjectStartedExploding reads GetFiringPlayerID() to detect the
    player destroying a friendly and raise ET_FRIENDLY_FIRE_GAME_OVER.

    Mirrors the SDK's ObjectExplodingEvent (sdk/.../App.py:6284+), which — like
    WeaponHitEvent, and unlike the base TGEvent — carries a firing-player-id.
    That id is the killer ship's GetObjID() (BC compares it against
    pPlayer.GetObjID()); NULL_ID (0) means no attributable killer.
    """
    def __init__(self):
        super().__init__()
        self._firing_player_id: int = 0

    def SetFiringPlayerID(self, player_id) -> None:
        self._firing_player_id = int(player_id)

    def GetFiringPlayerID(self) -> int:
        return self._firing_player_id


def ObjectExplodingEvent_Create() -> ObjectExplodingEvent:
    return ObjectExplodingEvent()


def _resolve_handler(qualified_name: str):
    """Resolve 'module.func' to the callable, or None if not found."""
    dot = qualified_name.rfind(".")
    if dot == -1:
        return None
    mod_name, func_name = qualified_name[:dot], qualified_name[dot + 1:]
    mod = sys.modules.get(mod_name)
    if mod is None:
        return None
    return getattr(mod, func_name, None)


# Undefined event-type names already recorded, so a per-frame registration
# cannot spam the log.
_warned_event_types: set[str] = set()

# {event-type name: [distinct qualified handler name, ...]}  (registration order)
#
# Reported once at exit rather than at registration. The per-registration
# warning put ~15 lines on stderr before the first frame of every run, and
# every name in it reappears in the stub-telemetry table at exit anyway. What
# telemetry canNOT say is WHICH handler is dead -- record_attr keys on the
# event-type name alone -- so that detail is what this summary carries.
_undefined_event_types: dict[str, list[str]] = {}
_undefined_atexit_registered = False


def undefined_event_type_summary_lines() -> list[str]:
    """At-exit summary of event types that resolved to a stub.

    Empty when nothing was recorded, so a clean run prints nothing at all.
    """
    if not _undefined_event_types:
        return []
    lines = ["=== undefined event types (handlers may never fire) ==="]
    width = max(len(n) for n in _undefined_event_types)
    for name, handlers in sorted(_undefined_event_types.items()):
        extra = "" if len(handlers) < 2 else "  (+%d more)" % (len(handlers) - 1,)
        lines.append("  %-*s  %s%s" % (width, name, handlers[0], extra))
    lines.append("  Define these in engine/appc/events.py.")
    return lines


def _register_undefined_atexit() -> None:
    global _undefined_atexit_registered
    if _undefined_atexit_registered:
        return
    _undefined_atexit_registered = True
    import atexit

    # print(), not logging: the embedded host installs no logging handler below
    # WARNING, and dev_mode/stub_telemetry report the same way.
    atexit.register(
        lambda: [print(ln) for ln in undefined_event_type_summary_lines()])


def _validate_event_type(event_type, where: str) -> bool:
    """False if `event_type` is not a usable dict key.

    An ET_* constant absent from our App.py resolves through App's module
    __getattr__ (App.py:1935) to a _NamedStub. We key handlers on the raw
    object; _Stub.__hash__ is id(self) and __getattr__ does NOT memoize ET_*
    names, so every access mints a FRESH key -- the handler becomes unreachable
    forever. 120 stub ET_ names across ~270 SDK sites are dead this way.

    We RECORD (surfacing it in docs/stub_heatmap.md) and report once per name in
    an at-exit summary -- see undefined_event_type_summary_lines(). We do NOT
    warn at registration: that fired before the first frame of every run and
    duplicated names the stub-telemetry table already prints. We also do NOT
    refuse: Tactical/Interface/CinematicInterfaceHandlers.py:15 keeps a
    module-level stub as a LIVE same-object dispatch key (registered :229, fired
    :275 through that same global), so refusing would break it.

    Test `not isinstance(x, int)` -- NOT isinstance(x, App._NamedStub). There are
    two unrelated _Stub hierarchies (App._Stub and engine.core.ids._Stub) and a
    class check would miss one.
    """
    if isinstance(event_type, int):
        return True
    # Read the INSTANCE __dict__ directly -- never `getattr(event_type, ...)`
    # for a stub-carried name. Both stub hierarchies vend a fresh truthy stub
    # from __getattr__ for ANY missing attribute (including a wrong guess at
    # the name field), so a `getattr(...) or repr(...)` fallback never reaches
    # `repr`: App._NamedStub stores the name at `_name`; engine.core.ids._Stub
    # stores it at `_stub_name` (no `_name` at all) -- guessing `_name` on the
    # latter silently vends another stub, whose default object.__repr__ embeds
    # the object id, so the "once per name" guard below keys on id() and never
    # collapses (unbounded warnings + telemetry rows keyed on garbage ids).
    d = getattr(event_type, "__dict__", {})
    name = d.get("_name") or d.get("_stub_name") or repr(event_type)
    stub_telemetry.record_attr("EventType", name)
    if name not in _warned_event_types:
        _warned_event_types.add(name)
        _register_undefined_atexit()
    # Distinct handlers only: one handler re-registering every mission swap is
    # still ONE dead handler, and the summary should not grow with swap count.
    handlers = _undefined_event_types.setdefault(name, [])
    if where not in handlers:
        handlers.append(where)
    return False


class TGEventHandlerObject(TGObject):
    def __init__(self):
        super().__init__()
        # {event_type: [qualified_handler_name, ...]}  (registration order)
        self._handlers: dict[int, list[str]] = {}
        # In-flight dispatch frames (one per nested ProcessEvent on this
        # object) so CallNextHandler can advance the handler chain. Eager init
        # so TGObject.__getattr__ never vends a truthy _Stub for it.
        self._dispatch_stack: list = []

    def AddPythonFuncHandlerForInstance(self, event_type: int, qualified_name: str) -> None:
        _validate_event_type(event_type, "AddPythonFuncHandlerForInstance(%s)" % qualified_name)
        self._handlers.setdefault(event_type, []).append(qualified_name)

    def RemoveHandlerForInstance(self, event_type: int, qualified_name: str) -> None:
        handlers = self._handlers.get(event_type, [])
        if qualified_name in handlers:
            handlers.remove(qualified_name)

    def RemoveAllInstanceHandlers(self) -> None:
        self._handlers.clear()

    def ProcessEvent(self, event: TGEvent) -> None:
        """Dispatch through this object's instance-handler chain, BC-faithfully.

        BC's handler chain is LIFO: the MOST-RECENTLY-registered handler runs
        first, and control passes to the next (older) handler ONLY when a
        handler calls ``pObject.CallNextHandler(pEvent)``. A handler that
        returns without calling it STOPS the chain. This is load-bearing: on
        the Helm menu both HelmMenuHandlers.Hail (registered first, at bridge
        load) and E1M2.HailHandler (registered later, at mission init) handle
        ET_HAIL. HailHandler runs first, handles "Haven"/"Facility", and
        returns without CallNextHandler — so the generic Hail "no response"
        never fires and the mission's Soams sequence runs cleanly. Running all
        handlers forward (the old behaviour) let both fire, so hailing the
        colony played "no response" and stepped on the mission dialogue."""
        names = self._handlers.get(event.GetEventType(), [])
        if not names:
            return
        frame = [list(reversed(names)), 0, event]   # [chain, next_index, event]
        self._dispatch_stack.append(frame)
        try:
            self._invoke_next_handler(frame)
        finally:
            self._dispatch_stack.pop()

    def _invoke_next_handler(self, frame) -> None:
        chain, index, event = frame[0], frame[1], frame[2]
        if index >= len(chain):
            return
        frame[1] = index + 1
        fn = _resolve_handler(chain[index])
        if fn is None:
            # Unresolvable handler (module/func gone) — skip to the next rather
            # than silently stalling the chain (which would drop the default).
            self._invoke_next_handler(frame)
            return
        # Exceptions propagate: the gameloop harness relies on a crashing
        # handler surfacing as a loop failure (test_loop_fail_bad_timer), and
        # button-click dispatch swallows+logs at SendActivationEvent.
        fn(self, event)

    def CallNextHandler(self, event=None) -> None:
        """Pass control to the next (older) handler in the chain currently
        dispatching on this object. No-op outside a dispatch — SDK handlers
        call it defensively, and it's the chain terminator when the current
        handler is the oldest."""
        if self._dispatch_stack:
            self._invoke_next_handler(self._dispatch_stack[-1])


class TGPythonInstanceWrapper(TGEventHandlerObject):
    """Bridge between TGEventHandlerObject (the event-manager's destination
    type) and a Python instance's named methods. SDK conditions use this to
    receive events at a wrapper and dispatch to a method on the wrapped
    Python instance.

    Pattern (from sdk/.../Conditions/ConditionExists.py):
        self.pEventHandler = App.TGPythonInstanceWrapper()
        self.pEventHandler.SetPyWrapper(self)
        App.g_kEventManager.AddBroadcastPythonMethodHandler(
            App.ET_DELETE_OBJECT_PUBLIC, self.pEventHandler, "Deleted", obj)
    """
    def __init__(self):
        super().__init__()
        self._py_wrapper = None
        # Dict initialized eagerly because TGObject.__getattr__ returns a
        # _Stub (not None) for missing attrs, so the lazy `getattr(..., None)`
        # idiom would silently mis-route registrations into a throwaway Stub.
        self._method_handlers: dict[int, list[str]] = {}

    def SetPyWrapper(self, instance) -> None:
        self._py_wrapper = instance

    def GetPyWrapper(self):
        return self._py_wrapper

    def AddPythonMethodHandlerForInstance(self, event_type: int, method_name: str) -> None:
        """Register a self-targeted method handler. Used by SDK conditions
        that listen for events sent directly to the wrapper (e.g. timer
        events) rather than broadcast across the bus."""
        _validate_event_type(event_type, "AddPythonMethodHandlerForInstance(%s)" % method_name)
        self._method_handlers.setdefault(event_type, []).append(method_name)

    def ProcessEvent(self, event):
        """Dispatch a direct-to-wrapper event to the registered method on
        the wrapped Python instance. Overrides the parent's qualified-
        function dispatch since this wrapper uses instance methods."""
        names = self._method_handlers.get(event.GetEventType(), [])
        py = self._py_wrapper
        if py is None:
            return
        for name in names:
            fn = getattr(py, name, None)
            if fn is not None:
                fn(event)


class TGEventManager(TGObject):
    def __init__(self):
        super().__init__()
        # {event_type: [(dest_obj, qualified_name, target), ...]}
        self._broadcast_handlers: dict[
            int, list[tuple["TGEventHandlerObject", str, object]]] = {}
        # {event_type: [(wrapper, method_name, target), ...]}; eager init —
        # see TGPythonInstanceWrapper note about TGObject.__getattr__ stubs.
        self._method_handlers: dict[
            int, list[tuple["TGPythonInstanceWrapper", str, object]]
        ] = {}

    def AddBroadcastPythonFuncHandler(
        self, event_type: int, dest: "TGEventHandlerObject", qualified_name: str, *extra
    ) -> None:
        """Register a module-qualified broadcast handler.

        `extra[0]`, when present, is BC's destination FILTER: dispatch is
        restricted to events whose destination IS that object (identity, not
        equality -- `_Stub.__eq__` is type-based, so == would match unrelated
        stubs). 10 SDK sites pass one, including
        Bridge/PowerDisplay.py:337-341, whose tractor and cloak HUD handlers
        re-read state off `pEvent.GetDestination()` and therefore repaint the
        PLAYER's indicator from whatever ship the event names. Dropping the
        filter made every NPC's cloak/tractor repaint the player's HUD.
        Mirrors AddBroadcastPythonMethodHandler, which has always filtered.
        """
        _validate_event_type(event_type, "AddBroadcastPythonFuncHandler(%s)" % qualified_name)
        self._broadcast_handlers.setdefault(event_type, []).append(
            (dest, qualified_name, extra[0] if extra else None))

    def AddBroadcastPythonMethodHandler(
        self, event_type: int, wrapper: "TGPythonInstanceWrapper",
        method_name: str, target=None,
    ) -> None:
        """Method-based broadcast handler. Mirrors AddBroadcastPythonFuncHandler
        but dispatches `getattr(wrapper.GetPyWrapper(), method_name)(evt)`
        instead of a module-qualified function. `target` (if given) restricts
        dispatch to events whose destination matches `target` by identity;
        None matches all events of `event_type`."""
        _validate_event_type(event_type, "AddBroadcastPythonMethodHandler(%s)" % method_name)
        self._method_handlers.setdefault(event_type, []).append(
            (wrapper, method_name, target)
        )

    def RemoveBroadcastHandler(
        self, event_type: int, dest_or_wrapper, qualified_name_or_method: str,
        target=None,
    ) -> None:
        """Remove a previously-added broadcast handler.

        Supports both `(eType, dest, qualified_name)` (func handler, legacy)
        and `(eType, wrapper, method_name[, target])` (method handler, new).
        Falls through to the func-handler list first; if not found there,
        tries the method-handler list."""
        # Func handlers: (dest, qualified_name).  Identity-compare the object.
        # `entry in list` / list.remove() compare with ==, and _Stub.__eq__ is
        # TYPE-based -- any all-stub tuple equals any other, so == would delete
        # the WRONG handler. Only the first element needs to be a stub.
        func_handlers = self._broadcast_handlers.get(event_type, [])
        for i, (d, q, _t) in enumerate(func_handlers):
            if d is dest_or_wrapper and q == qualified_name_or_method:
                del func_handlers[i]
                return
        # Method handlers: (wrapper, method_name, target).
        method_handlers = self._method_handlers.get(event_type, [])
        for i, (w, m, t) in enumerate(method_handlers):
            if w is dest_or_wrapper and m == qualified_name_or_method and t is target:
                del method_handlers[i]
                return

    RemoveBroadcastHandlerForInstance = RemoveBroadcastHandler

    def AddEvent(self, event: TGEvent) -> None:
        # Destination dispatch is deliberately UNguarded: engine-internal
        # actions rely on ProcessEvent exceptions propagating (see
        # test_loop_fail_bad_timer). Broadcast dispatch below is
        # log-and-continue, matching original BC: embedded CPython printed
        # the traceback and the engine kept ticking, so one broken SDK
        # handler never killed the loop.
        dest = event.GetDestination()
        if dest is not None and isinstance(dest, TGEventHandlerObject):
            dest.ProcessEvent(event)
        # Func-broadcast handlers (existing). Iterate a SNAPSHOT of the list:
        # SDK handlers re-register themselves mid-dispatch (PowerDisplay.
        # HandleSetPlayer -> Init -> RemoveEventHandlers/AddEventHandlers);
        # mutating the live list shifts later entries left, so the iterator
        # skips the next sibling (bridge_officers.OnSetPlayer — the QB
        # helm-wiring regression) and revisits the re-appended self instead.
        for bd, name, target in list(
            self._broadcast_handlers.get(event.GetEventType(), [])
        ):
            if target is not None and event.GetDestination() is not target:
                continue
            fn = _resolve_handler(name)
            if fn is not None:
                try:
                    fn(bd, event)
                except Exception:
                    self._log_broadcast_failure(name, event)
        # Method-broadcast handlers (new). Snapshot for the same reason.
        for wrapper, method_name, target in list(
            self._method_handlers.get(event.GetEventType(), [])
        ):
            if target is not None and event.GetDestination() is not target:
                continue
            py = wrapper.GetPyWrapper()
            if py is not None:
                method = getattr(py, method_name, None)
                if method is not None:
                    try:
                        method(event)
                    except Exception:
                        self._log_broadcast_failure(
                            "%s.%s" % (type(py).__name__, method_name), event
                        )

    @staticmethod
    def _log_broadcast_failure(handler_desc: str, event: TGEvent) -> None:
        """Print the active exception's full traceback to stderr, prefixed
        with a line pinpointing the failing handler + event type. Always on
        (never dev-mode-gated): a silently-swallowed handler crash is worse
        than a noisy log."""
        print(
            "[events] broadcast handler %r raised for event type %s "
            "— continuing" % (handler_desc, event.GetEventType()),
            file=sys.stderr,
        )
        traceback.print_exc(file=sys.stderr)
