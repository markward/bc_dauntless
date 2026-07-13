###############################################################################
# probe_harness -- shared helpers for the live-state probes (q14+).
#
# This is NOT a probe. It records nothing on its own. Import it from a probe
# (game/ is on sys.path, so both execfile() and imported probes can reach it):
#
#     import probe_harness
#     _h = probe_harness                 # NB: no "import X as Y" in Python 1.5
#     _h.configure("BCProbe_qNN_menu", "BCProbe_qNN_menu.cfg")   # call FIRST
#     _h.section("provenance")
#     for _ln in _h.provenance():
#         _h.emit(_ln)
#     ... _h.record(label, value) / _h.emit(line) ...
#     _h.flush()                         # or _h.flush_chunked() for big dumps
#
# Ships with q14 (docs/instrumented_experiments/2026-07-13-env-and-harness-probe.md)
# and is consumed by q15 (firehose), q16 (object graph), q17 (bridge graph).
#
# PYTHON 1.5 CONSTRAINTS -- see console-probe-workflow.md
#   No "import X as Y" / no f-strings / no True/False (use 1/0) /
#   "except E, e:" (comma) / print is a STATEMENT / dict.has_key() not "in" /
#   only App.g_kConfigMapping writes to disk (open() is blocked).
#
# CONSOLE OUTPUT DISCIPLINE (the q13 friction lesson): print() to the -TestMode
# console is synchronous and dominates runtime -- a ~2000-line dump cost ~30 min
# of console spam vs ~10s buffered. record/emit/section are therefore
# BUFFER-ONLY; only echo() prints, and only status/summary lines. NEVER print
# inside a data loop.
###############################################################################

import App
import sys
import string          # Python 1.5 has no str.join method -- use string.join

_cfg = App.g_kConfigMapping

# --- output state (reset per run via configure) -----------------------------
_log = []
_SECTION = "BCProbe"
_CFG_FILE = "BCProbe.cfg"

# --- knobs ------------------------------------------------------------------
VERBOSE    = 0        # 1 = also echo every buffered line (SLOW; small runs only)
CHUNK_SIZE = 400      # rows per file in chunked mode
MAX_CHUNKS = 50       # hard cap; overflow is reported, never silently dropped


def configure(section, cfg_file):
    """Reset the buffer and set the section / output file for this run.
    Call this FIRST -- the module persists across execfile() runs in one REPL
    session, so a stale _log would otherwise accumulate."""
    global _SECTION, _CFG_FILE, _log
    _SECTION = section
    _CFG_FILE = cfg_file
    _log = []


# --- console + buffering ----------------------------------------------------

def echo(msg):
    """The ONLY unconditional console print. Reserve for status/summary lines
    (armed / wrote / save FAILED / done / FATAL). NEVER call inside a data loop."""
    print msg


MAX_LINE = 180        # hard cap on a buffered line's length -- see below

def emit(line):
    """Buffer a pre-formatted line. BUFFER-ONLY (see the discipline note above).

    SAFETY CAP: BC's SaveConfigFile crashes the game on an over-long value --
    q15 lost a run to a single ~6000-char line (a string.join over ~300 event
    names). We hard-truncate here so no probe can trip the writer. 180 is well
    above a normal line (~120 seen in practice) and far below the danger zone."""
    if len(line) > MAX_LINE:
        line = line[:MAX_LINE] + "..(cut)"
    _log.append(line)
    if VERBOSE:
        print line


def record(label, value):
    """Buffer 'label = value'. BUFFER-ONLY."""
    emit("%s = %s" % (str(label), str(value)))


def section(title):
    """Buffer a heading line. BUFFER-ONLY."""
    emit("-- " + str(title) + " " + ("-" * max(1, 60 - len(str(title)))))


def line_count():
    return len(_log)


def exc_name(e):
    """Exception class name -- safe against Python 1.5 string exceptions."""
    try:
        return e.__class__.__name__
    except AttributeError:
        return str(type(e))


# --- flush: single-file (primary) -------------------------------------------

def flush():
    """Write the buffer to one cfg section, then scrub the keys so Options.cfg
    is not polluted (single-threaded -- no race with the game loop)."""
    n = len(_log)
    for i in range(n):
        _cfg.SetStringValue(_SECTION, "r%d" % i, _log[i])
    _cfg.SetIntValue(_SECTION, "n", n)
    try:
        _cfg.SaveConfigFile(_CFG_FILE)
        echo("wrote %s with %d lines" % (_CFG_FILE, n))
    except Exception, _e:
        echo("save FAILED: " + str(_e))
    for i in range(n):
        _cfg.SetStringValue(_SECTION, "r%d" % i, "")
    _cfg.SetIntValue(_SECTION, "n", 0)


# --- flush: chunked multi-file (fallback for large dumps) --------------------

def flush_chunked():
    """Split the buffer into CHUNK_SIZE-row files. Chunk 0 -> _CFG_FILE;
    chunk k>=1 -> <stem>_k.cfg. Scrub each chunk's keys before the next so no
    single section ever holds more than one chunk of live values."""
    base = _CFG_FILE
    if len(base) >= 4 and base[-4:] == ".cfg":
        stem = base[:-4]
    else:
        stem = base
    n = len(_log)
    nchunks = 0
    i = 0
    while i < n and nchunks < MAX_CHUNKS:
        chunk = _log[i:i + CHUNK_SIZE]
        m = len(chunk)
        if nchunks == 0:
            fname = base
        else:
            fname = "%s_%d.cfg" % (stem, nchunks)
        for j in range(m):
            _cfg.SetStringValue(_SECTION, "r%d" % j, chunk[j])
        _cfg.SetIntValue(_SECTION, "n", m)
        _cfg.SetIntValue(_SECTION, "chunk", nchunks)
        try:
            _cfg.SaveConfigFile(fname)
            echo("wrote %s with %d lines (chunk %d)" % (fname, m, nchunks))
        except Exception, _e:
            echo("save FAILED (%s): %s" % (fname, str(_e)))
        for j in range(m):
            _cfg.SetStringValue(_SECTION, "r%d" % j, "")
        _cfg.SetIntValue(_SECTION, "n", 0)
        nchunks = nchunks + 1
        i = i + CHUNK_SIZE
    if i < n:
        echo("OVERFLOW: %d lines NOT written (cap %d chunks)" % (n - i, MAX_CHUNKS))
    echo("chunked flush: %d file(s)" % nchunks)


# --- live-state helpers -----------------------------------------------------

def _safe(obj, name, args):
    """apply(getattr(obj, name), args) with the getattr INSIDE the try, so a
    missing SWIG method degrades to None instead of escaping the net."""
    try:
        return apply(getattr(obj, name), args)
    except:
        return None


def _cast(cast_name, pObj):
    """Try one App.<Type>_Cast(pObj). Returns the cast pointer or None."""
    try:
        fn = getattr(App, cast_name)
    except:
        return None
    try:
        return apply(fn, (pObj,))
    except:
        return None


# The canonical cast ladder -- (cast function name, label, id-method list).
# q16/q17 extend this; keep the shared core here so probes stop hand-rolling it.
# We try EVERY cast and list every one that matched (a TorpedoTube also casts to
# ShipSubsystem -- reporting both is informative), asking the engine rather than
# guessing the type.
_CAST_LADDER = [
    ("Torpedo_Cast",       "Torpedo"),
    ("TorpedoTube_Cast",   "TorpedoTube"),
    ("TorpedoSystem_Cast", "TorpedoSystem"),
    ("ShipSubsystem_Cast", "ShipSubsystem"),
    ("ShipClass_Cast",     "ShipClass"),
    ("Planet_Cast",        "Planet"),
    ("Sun_Cast",           "Sun"),
]


def describe(pObj):
    """Identify an object by trying the cast ladder. Returns a compact string of
    every cast that matched plus a name/objid, or UNKNOWN if none matched."""
    if pObj is None:
        return "None"
    hits = []
    for pair in _CAST_LADDER:
        p = _cast(pair[0], pObj)
        if p:
            nm = _safe(p, "GetName", ())
            if nm is not None:
                hits.append("%s(name='%s')" % (pair[1], str(nm)))
            else:
                hits.append(pair[1])
    oid = _safe(pObj, "GetObjID", ())
    if oid is not None:
        hits.append("objid=%s" % str(oid))
    if not hits:
        hits.append("UNKNOWN(no cast matched)")
    return string.join(hits, " ")


def _rendered_set():
    try:
        return App.g_kSetManager.GetRenderedSet()
    except:
        return None


def current_player():
    """The player ship if one exists (a mission/battle is live), else None."""
    try:
        p = App.Game_GetCurrentPlayer()
        if p is not None:
            return p
    except:
        pass
    try:
        import MissionLib
        return MissionLib.GetPlayer()
    except:
        return None


def episode():
    """The current episode object if a scripted mission is running, else None."""
    try:
        import MissionLib
        return MissionLib.GetEpisode()
    except:
        return None


def persistent_owner():
    """The 'self' to hand AddBroadcastPythonFuncHandler. Prefer the episode --
    it outlives individual set transitions (E1M1). Fall back to the player, then
    None. Documented in one place so every event probe uses the same policy."""
    pEp = episode()
    if pEp is not None:
        return pEp
    return current_player()


def _episode_name(pEp):
    nm = _safe(pEp, "GetName", ())
    if nm is not None:
        return str(nm)
    return str(pEp)


def scenario_tag():
    """Short scenario id for result filenames: 'A' (QuickBattle), 'B' (a scripted
    mission), 'menu', or 'unknown'. Keys off the set name -- NB QuickBattle also
    has an episode, so episode-presence alone does NOT distinguish A from B."""
    if current_player() is None:
        return "menu"
    pSet = _rendered_set()
    sset = ""
    if pSet is not None:
        nm = _safe(pSet, "GetName", ())
        if nm is not None:
            sset = str(nm)
    if string.find(sset, "QuickBattle") >= 0:
        return "A"
    if episode() is not None:
        return "B"
    return "unknown"


def provenance():
    """Return (does NOT print) the self-identifying header lines for a live-state
    dump: scenario classification, set, game time/frame, and the ship roster.
    The roster is what makes 'Scenario A' checkable after the fact and lets other
    probes tie events/objects to named ships."""
    out = []
    pPlayer = current_player()
    pEp = episode()
    pSet = _rendered_set()

    set_name = None
    if pSet is not None:
        set_name = _safe(pSet, "GetName", ())
    sset = ""
    if set_name is not None:
        sset = str(set_name)

    # Scenario is DERIVED from live state, never a flag. NB: QuickBattle also has
    # an episode object (QuickBattleEpisode), so episode-presence does NOT
    # distinguish A from B -- key off the set name instead.
    if pPlayer is None:
        scen = "menu (no current player)"
    elif string.find(sset, "QuickBattle") >= 0:
        scen = "A (QuickBattle, set=%s)" % sset
    elif pEp is not None:
        scen = "B (mission, set=%s)" % sset
    else:
        scen = "battle (unknown scenario, set=%s)" % sset
    out.append("scenario = %s" % scen)

    out.append("set_name = %s" % sset)
    out.append("game_time = %s" % str(_safe(App.g_kUtopiaModule, "GetGameTime", ())))
    out.append("frame = %s" % str(_safe(App.g_kSystemWrapper, "GetUpdateNumber", ())))

    # Roster: every ship in the rendered set. This is the same set-walk q16
    # relies on, so it carries diagnostics: roster_scanned tells us whether the
    # iterator advanced at all, and obj_seenN (emitted only when NO ship was
    # found) shows what the walk actually returned -- so a 0-ship result is
    # self-diagnosing rather than a mystery.
    objs = iter_set_objids(pSet)
    nships = 0
    for pair in objs:
        if _cast("ShipClass_Cast", pair[1]):
            out.append("ship%d = %s" % (nships, describe(pair[1])))
            nships = nships + 1
    out.append("roster_ships = %d" % nships)
    out.append("roster_scanned = %d" % len(objs))
    return out


def iter_set_objids(pSet):
    """Yield-equivalent (returns a list of) every distinct object in a set,
    walking BC's set iterator correctly. Two gotchas, both found in q14:
      1. GetNextObject advances by OBJID, not by the object -- passing the
         object returns None after one element.  SDK: GetNextObject(pObj.GetObjID()).
      2. The iterator is CIRCULAR -- after the last object it wraps to the first
         rather than returning None -- so we must dedup on objid and stop on a
         repeat, or the walk never terminates.
    Returns a list of (objid, object) pairs. Shared so q16/q17 reuse the exact
    same corrected walk."""
    out = []
    if pSet is None:
        return out
    visited = {}
    obj = _safe(pSet, "GetFirstObject", ())
    guard = 0
    while obj is not None and guard < 8000:
        oid = _safe(obj, "GetObjID", ())
        if oid is not None and visited.has_key(oid):
            break                                   # iterator wrapped -> done
        if oid is not None:
            visited[oid] = 1
        out.append((oid, obj))
        if oid is None:
            break
        obj = _safe(pSet, "GetNextObject", (oid,))
        guard = guard + 1
    return out
