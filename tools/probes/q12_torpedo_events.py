###############################################################################
# q12 -- Torpedo event surface: who posts ET_TORPEDO_FIRED, and what does it carry?
#
# Question(s): docs/instrumented_experiments/2026-07-12-torpedo-event-probe.md
# Needs combat state? YES -- operator must start Quick Battle, acquire a target
#                     (Tab), and FIRE TORPEDOES while this probe is installed.
# Output:      game/BCProbe_q12.cfg, section [BCProbe_q12]
#
# THIS PROBE IS NOT A ONE-SHOT execfile() PROBE.  It is event-driven: it must be
# IMPORTED (so the engine can resolve its handlers by name), then armed, then the
# operator plays, then it is dumped.  See the runbook for the exact console lines.
#
#   import q12_torpedo_events
#   q12_torpedo_events.Install()
#   ... fly, acquire target, fire torpedoes, wait for a reload ...
#   q12_torpedo_events.Dump()
#
###############################################################################
#
# PYTHON 1.5 CONSTRAINTS -- read docs/instrumented_experiments/console-probe-workflow.md
#
# - No "import X as Y"          -> import X; Y = X
# - No f-strings                -> "%s %d" % (s, n)
# - No True/False               -> 1 / 0
# - except SomeError, e:        (comma, NOT "as")
# - print is a STATEMENT        -> print x  (no parens around the whole expr)
# - Only App.g_kConfigMapping writes outside this process.  open() is blocked.
#
# WHY AN IMPORTED MODULE, NOT execfile():
#   AddBroadcastPythonFuncHandler takes a "module.FunctionName" STRING which the
#   engine resolves by importing that module.  Functions defined by execfile()
#   land in the REPL namespace and are NOT importable, so the engine could never
#   find them.  game/ is on sys.path, so a plain `import q12_torpedo_events`
#   makes __name__ == "q12_torpedo_events" and the handler strings resolve.
#
###############################################################################

import App
import sys
import string          # Python 1.5 has NO str.join method -- use string.join(list, sep)

_cfg = App.g_kConfigMapping
_SECTION = "BCProbe_q12"
_CFG_FILE = "BCProbe_q12.cfg"

_log = []
_events = []
_MAX_EVENTS = 250
_armed = 0

# The five torpedo/weapon events the SDK declares.  Names taken from
# sdk/Build/scripts/App.py:12889-12968.  NOTE the reload event is spelled
# ET_TORPEDO_RELOAD (the RE notes in docs/ call it "ET_RELOAD_TORPEDO" -- that
# was the RE author's own label, not the SWIG name).
_WATCH = [
    ("ET_TORPEDO_FIRED", "TorpedoFired"),
    ("ET_TORPEDO_RELOAD", "TorpedoReload"),
    ("ET_WEAPON_FIRED", "WeaponFired"),
    ("ET_CANT_FIRE", "CantFire"),
    ("ET_TORPEDO_START_HOMING", "TorpedoStartHoming"),
]


def _exc_name(e):
    """Exception class name -- safe against Python 1.5 string exceptions."""
    try:
        return e.__class__.__name__
    except AttributeError:
        return str(type(e))


def _record(label, value):
    """Append "label = value" to the result log and echo to the console."""
    line = "%s = %s" % (str(label), str(value))
    _log.append(line)
    print line


def _section(title):
    bar = "-- " + str(title) + " " + ("-" * max(1, 60 - len(str(title))))
    _log.append(bar)
    print bar


def _describe(pObj):
    """Identify an event source/destination by trying every relevant SWIG cast.

    This is the crux of the probe.  We do NOT guess what the object is -- we ask
    the engine, using exactly the casts the SDK itself uses.  Returns a compact
    string listing every cast that succeeded plus any identifying detail.
    """
    if pObj is None:
        return "None"

    hits = []

    # Order matters only for readability; every cast is attempted.
    try:
        p = App.Torpedo_Cast(pObj)
        if p:
            hits.append("Torpedo(parent=%s target=%s)"
                        % (str(p.GetParentID()), str(p.GetTargetID())))
    except:
        hits.append("Torpedo_Cast:EXC")

    try:
        p = App.TorpedoTube_Cast(pObj)
        if p:
            hits.append("TorpedoTube(name='%s' ready=%s)"
                        % (str(p.GetName()), str(p.GetNumReady())))
    except:
        hits.append("TorpedoTube_Cast:EXC")

    try:
        p = App.TorpedoSystem_Cast(pObj)
        if p:
            hits.append("TorpedoSystem(name='%s')" % str(p.GetName()))
    except:
        hits.append("TorpedoSystem_Cast:EXC")

    try:
        p = App.ShipSubsystem_Cast(pObj)
        if p:
            hits.append("ShipSubsystem(name='%s')" % str(p.GetName()))
    except:
        hits.append("ShipSubsystem_Cast:EXC")

    try:
        p = App.ShipClass_Cast(pObj)
        if p:
            hits.append("ShipClass(name='%s')" % str(p.GetName()))
    except:
        hits.append("ShipClass_Cast:EXC")

    try:
        hits.append("objid=%s" % str(pObj.GetObjID()))
    except:
        pass

    if not hits:
        hits.append("UNKNOWN(no cast matched)")
    return string.join(hits, " ")


def _ammo_now():
    """Current torpedo ammo type name on the player, or '?' if unavailable.

    Answers 'does ET_TORPEDO_FIRED fire for ordinary photons, or only for the
    Phased Plasma special ammo?'  Episode7.TorpedoFired filters on this name.
    """
    try:
        import MissionLib
        pPlayer = MissionLib.GetPlayer()
        if not pPlayer:
            return "?"
        pTorpSys = pPlayer.GetTorpedoSystem()
        if not pTorpSys:
            return "?"
        pAmmo = pTorpSys.GetCurrentAmmoType()
        if not pAmmo:
            return "?"
        return str(pAmmo.GetAmmoName())
    except:
        return "?"


def _capture(sEventName, pEvent):
    """Common handler body.  One line per event, in arrival order."""
    if len(_events) >= _MAX_EVENTS:
        return
    try:
        sType = "?"
        sSrc = "?"
        sDst = "?"
        try:
            sType = str(pEvent.GetEventType())
        except:
            pass
        try:
            sSrc = _describe(pEvent.GetSource())
        except:
            sSrc = "GetSource:EXC"
        try:
            sDst = _describe(pEvent.GetDestination())
        except:
            sDst = "GetDestination:EXC"

        _events.append(
            "%s | t=%.3f frame=%s type=%s ammo=%s | SRC %s | DST %s"
            % (sEventName,
               App.g_kUtopiaModule.GetGameTime(),
               str(App.g_kSystemWrapper.GetUpdateNumber()),
               sType,
               _ammo_now(),
               sSrc,
               sDst))
    except:
        _events.append("%s | CAPTURE FAILED exc_type=%s exc_value=%s"
                       % (sEventName, str(sys.exc_type), str(sys.exc_value)))


# --- Handlers.  The engine resolves these by the string "q12_torpedo_events.X" --
# Signature matches the SDK's own broadcast func handlers (see
# Maelstrom/Episode7/Episode7.py:88 -- def TorpedoFired(TGObject, pEvent)).

def TorpedoFired(TGObject, pEvent):
    _capture("ET_TORPEDO_FIRED", pEvent)


def TorpedoReload(TGObject, pEvent):
    _capture("ET_TORPEDO_RELOAD", pEvent)


def WeaponFired(TGObject, pEvent):
    _capture("ET_WEAPON_FIRED", pEvent)


def CantFire(TGObject, pEvent):
    _capture("ET_CANT_FIRE", pEvent)


def TorpedoStartHoming(TGObject, pEvent):
    _capture("ET_TORPEDO_START_HOMING", pEvent)


def _handler_owner():
    """A TGObject to hand the engine as the handler's 'self' argument.

    Episode7.py:37 passes the episode.  We prefer the player ship because it is
    guaranteed to exist in Quick Battle; fall back to the episode.
    """
    try:
        import MissionLib
        pPlayer = MissionLib.GetPlayer()
        if pPlayer:
            return pPlayer
    except:
        pass
    try:
        import MissionLib
        return MissionLib.GetEpisode()
    except:
        return None


def Install():
    """Print the numeric event IDs, then arm every handler.  Idempotent-ish:
    calling twice would double-register, so it refuses on a second call."""
    global _armed
    if _armed:
        print "q12: already armed -- skipping re-registration"
        return

    print "=== q12 torpedo event probe ==="

    # STEP 1 -- the numeric IDs.  This alone answers 'what integer is
    # ET_TORPEDO_FIRED', which we need for our own App.py.  A missing constant
    # would raise here rather than silently stub.
    for sName, sFunc in _WATCH:
        try:
            iVal = getattr(App, sName)
            print "  %-26s = %s (0x%08X)" % (sName, str(iVal), iVal)
        except:
            print "  %-26s = <ABSENT> %s" % (sName, str(sys.exc_value))

    pOwner = _handler_owner()
    if pOwner is None:
        print "q12: FATAL -- no player/episode object to own the handlers."
        print "     Start Quick Battle FIRST, then re-run Install()."
        return

    # STEP 2 -- register a broadcast handler per event.  Broadcast (not
    # destination-filtered) so we see EVERY firing, from any ship.
    for sName, sFunc in _WATCH:
        try:
            iType = getattr(App, sName)
            App.g_kEventManager.AddBroadcastPythonFuncHandler(
                iType, pOwner, __name__ + "." + sFunc)
            print "  armed %s -> %s.%s" % (sName, __name__, sFunc)
        except:
            print "  ARM FAILED %s: exc_type=%s exc_value=%s" % (
                sName, str(sys.exc_type), str(sys.exc_value))

    _armed = 1
    print ""
    print "q12 ARMED.  Now, IN GAME:"
    print "  1. Acquire a target (Tab)."
    print "  2. Fire TORPEDOES repeatedly (not phasers) -- at least 6 shots."
    print "  3. Hold fire ~45s so a full tube reload completes."
    print "  4. Fire 2 more torpedoes."
    print "  5. Back in this console:  q12_torpedo_events.Dump()"


def Dump():
    """Write everything captured so far to game/BCProbe_q12.cfg."""
    _section("environment")
    _record("python_version", sys.version)
    _record("frame", App.g_kSystemWrapper.GetUpdateNumber())
    _record("game_time", App.g_kUtopiaModule.GetGameTime())
    _record("armed", _armed)

    _section("event constant values")
    for sName, sFunc in _WATCH:
        try:
            iVal = getattr(App, sName)
            _record(sName, "%s (0x%08X)" % (str(iVal), iVal))
        except:
            _record(sName, "<ABSENT>")

    _section("player torpedo config")
    try:
        import MissionLib
        pPlayer = MissionLib.GetPlayer()
        if pPlayer:
            _record("player_ship", pPlayer.GetName())
            pTorpSys = pPlayer.GetTorpedoSystem()
            if pTorpSys:
                _record("torp_system", pTorpSys.GetName())
                _record("num_tubes", pTorpSys.GetNumChildSubsystems())
                _record("num_ammo_types", pTorpSys.GetNumAmmoTypes())
                _record("current_ammo", pTorpSys.GetCurrentAmmoType().GetAmmoName())
                iN = pTorpSys.GetNumChildSubsystems()
                for i in range(iN):
                    pTube = App.TorpedoTube_Cast(pTorpSys.GetChildSubsystem(i))
                    if pTube:
                        _record("tube[%d]" % i,
                                "name='%s' maxready=%s numready=%s "
                                "immediate=%s reload=%s lastfire=%s"
                                % (str(pTube.GetName()),
                                   str(pTube.GetMaxReady()),
                                   str(pTube.GetNumReady()),
                                   str(pTube.GetImmediateDelay()),
                                   str(pTube.GetReloadDelay()),
                                   str(pTube.GetLastFireTime())))
                    else:
                        _record("tube[%d]" % i, "CHILD DID NOT CAST TO TorpedoTube")
    except Exception, _e:
        _record("player torpedo config FAILED", "%s: %s" % (_exc_name(_e), str(_e)))

    _section("captured events (%d)" % len(_events))
    if not _events:
        _record("WARNING", "NO EVENTS CAPTURED -- did you fire torpedoes while armed?")
    for i in range(len(_events)):
        _record("e%03d" % i, _events[i])

    _flush()
    print "q12 done -- %d events captured" % len(_events)


def _flush():
    """Write _log to cfg, then scrub the keys so Options.cfg stays clean."""
    n = len(_log)
    for i in range(n):
        _cfg.SetStringValue(_SECTION, "r%d" % i, _log[i])
    _cfg.SetIntValue(_SECTION, "n", n)
    try:
        _cfg.SaveConfigFile(_CFG_FILE)
        print "wrote " + _CFG_FILE + " with %d lines" % n
    except Exception, _e:
        print "save FAILED: " + str(_e)
    for i in range(n):
        _cfg.SetStringValue(_SECTION, "r%d" % i, "")
    _cfg.SetIntValue(_SECTION, "n", 0)
