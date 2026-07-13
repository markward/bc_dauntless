###############################################################################
# q15_firehose -- a census of every event the engine actually fires.
#
# Question(s): docs/instrumented_experiments/2026-07-13-event-firehose-probe.md
#              Q15-1 which ET_* fire in Scenario A, Q15-2 which fire in B (E1M1)
#              that don't in A, Q15-3 first source->destination per type,
#              Q15-4 which declared types never fire, Q15-5 ordering (focus mode).
# Needs combat state? YES. Start a scenario, Install(), play, then Dump().
# Output:      game/BCProbe_q15_<scenario>.cfg  (<scenario> = A / B / unknown)
#
# THIS IS AN IMPORTED, EVENT-DRIVEN PROBE (like q12, not execfile):
#   import q15_firehose
#   q15_firehose.Install()          # arms ONE handler for every ET_* type
#   ... play the scenario ...
#   q15_firehose.Rearm()            # (E1M1 only) at each set-transition checkpoint
#   q15_firehose.Dump()             # writes BCProbe_q15_<scenario>.cfg
#
# REQUIRES probe_harness.py in game/ (push.py copies it alongside).
#
# THE DESIGN: one handler, not 363. AddBroadcastPythonFuncHandler resolves a
# handler by the string "q15_firehose.OnEvent" -- you cannot bind the event type
# into a closure -- so we register the SAME OnEvent for EVERY ET_* type and read
# pEvent.GetEventType() inside it to learn which fired. O(1) source, O(363)
# coverage.
#
# CONSOLE DISCIPLINE (q13 lesson): OnEvent fires EVERY FRAME. It is print-free
# and record-free -- it touches only in-memory dicts. describe() runs once per
# type (first firing), never per event. Only Install/Rearm/Dump echo.
#
# PYTHON 1.5 CONSTRAINTS -- see console-probe-workflow.md
#   No "import X as Y" / no f-strings / no True/False / "except E, e:" /
#   print is a statement / dict.has_key() not "in".
###############################################################################

import App
import sys
import string
import probe_harness
_h = probe_harness              # no "import X as Y" in Python 1.5

# --- knobs ------------------------------------------------------------------
_MAX_DISTINCT = 16              # cap on distinct src/dst objids tracked per type
_MAX_FOCUS    = 300            # cap on raw focus-mode log lines

# --- state ------------------------------------------------------------------
_tallies   = {}                 # itype -> record dict (count/first_t/last_t/...)
_TYPE_NAME = {}                 # itype -> "ET_..." name
_armed     = 0
_owner     = None
_focus     = {}                 # itype -> 1  (raw-log these types)
_focus_log = []


def _gt():
    try:
        return App.g_kUtopiaModule.GetGameTime()
    except:
        return -1.0


def _src_of(pEvent):
    try:
        return _h.describe(pEvent.GetSource())
    except:
        return "GetSource:EXC"


def _dst_of(pEvent):
    try:
        return _h.describe(pEvent.GetDestination())
    except:
        return "GetDestination:EXC"


def _note_id(idmap, pEvent, method):
    """Record a distinct objid, bounded. The length check short-circuits BEFORE
    the SWIG calls once full, so this stays cheap on the hot path."""
    if len(idmap) >= _MAX_DISTINCT:
        return
    try:
        p = apply(getattr(pEvent, method), ())
        if p is not None:
            idmap[p.GetObjID()] = 1
    except:
        pass


# --- THE hot path -- one handler for every event type -----------------------
# Signature matches the SDK broadcast handlers: (owner-TGObject, pEvent).
# BUFFER-FREE, PRINT-FREE, in-memory only.
def OnEvent(TGObject, pEvent):
    try:
        itype = pEvent.GetEventType()
    except:
        return
    if not _tallies.has_key(itype):
        rec = {}
        rec["count"]     = 0
        rec["first_t"]   = _gt()
        rec["last_t"]    = rec["first_t"]
        rec["first_src"] = _src_of(pEvent)     # bounded: once per type
        rec["first_dst"] = _dst_of(pEvent)
        rec["src_ids"]   = {}
        rec["dst_ids"]   = {}
        _tallies[itype] = rec
    else:
        rec = _tallies[itype]
    rec["count"]  = rec["count"] + 1
    rec["last_t"] = _gt()
    _note_id(rec["src_ids"], pEvent, "GetSource")
    _note_id(rec["dst_ids"], pEvent, "GetDestination")
    if _focus.has_key(itype) and len(_focus_log) < _MAX_FOCUS:
        _focus_log.append("%s | t=%s | frame=%s | SRC %s | DST %s"
                          % (_name_of(itype), str(_gt()),
                             str(_frame()), _src_of(pEvent), _dst_of(pEvent)))


def _frame():
    try:
        return App.g_kSystemWrapper.GetUpdateNumber()
    except:
        return -1


def _name_of(itype):
    if _TYPE_NAME.has_key(itype):
        return _TYPE_NAME[itype]
    return "ET_?(%s)" % str(itype)


def _et_names():
    """Every 'ET_*' name currently on the App module."""
    names = []
    try:
        for nm in dir(App):
            if len(nm) >= 3 and nm[:3] == "ET_":
                names.append(nm)
    except:
        pass
    return names


def _arm_all(names):
    """(Re)register OnEvent as a broadcast handler for every named event type.
    Returns (n_armed, n_skipped)."""
    narmed = 0
    nskip = 0
    for nm in names:
        try:
            itype = getattr(App, nm)
        except:
            nskip = nskip + 1
            continue
        _TYPE_NAME[itype] = nm
        try:
            App.g_kEventManager.AddBroadcastPythonFuncHandler(
                itype, _owner, "q15_firehose.OnEvent")
            narmed = narmed + 1
        except:
            nskip = nskip + 1
    return (narmed, nskip)


def Install():
    """Arm ONE broadcast handler for every ET_* type. Refuses a second call
    (would double-register and double-count)."""
    global _armed, _owner
    if _armed:
        _h.echo("q15: already armed -- use Rearm() after a set transition.")
        return
    _owner = _h.persistent_owner()
    if _owner is None:
        _h.echo("q15: FATAL -- no owner. Start a battle/mission FIRST, then Install().")
        return
    names = _et_names()
    result = _arm_all(names)
    _armed = 1
    _h.echo("q15 ARMED: %d handlers (%d skipped) for %d ET_* names; owner=%s"
            % (result[0], result[1], len(names), _h.describe(_owner)))
    _h.echo("  Now play the scenario, then: q15_firehose.Dump()")


def Rearm():
    """Re-register handlers after an E1M1 set transition (the owner object or its
    handlers may not survive an unload). CAUTION: if the handlers DID survive,
    this double-registers and doubles counts -- only call it when the firehose
    has visibly gone quiet across a transition. Not needed in QuickBattle."""
    global _owner
    _owner = _h.persistent_owner()
    if _owner is None:
        _h.echo("q15 Rearm: no owner")
        return
    result = _arm_all(_et_names())
    _h.echo("q15 REARMED: %d handlers; owner=%s" % (result[0], _h.describe(_owner)))


def Focus(names):
    """Switch specific types from aggregate to raw per-event logging (for
    ordering/coupling questions, Q15-5). Capped at _MAX_FOCUS lines. Off by
    default. names = list of 'ET_...' strings."""
    for nm in names:
        try:
            _focus[getattr(App, nm)] = 1
        except:
            pass
    _h.echo("q15 focus: tracking %d type(s) raw" % len(_focus))


def _card(idmap):
    n = len(idmap)
    if n >= _MAX_DISTINCT:
        return "%d+" % n
    return str(n)


def _hex(v):
    try:
        return "0x%08X" % v
    except:
        return str(v)


def _f2(v):
    try:
        return "%.2f" % v
    except:
        return str(v)


def _cmp_count(a, b):
    """Descending by count (Python 1.5 list.sort takes a cmp func)."""
    ca = a[1]["count"]
    cb = b[1]["count"]
    if ca < cb:
        return 1
    if ca > cb:
        return -1
    return 0


def Dump():
    """Write the aggregated census to game/BCProbe_q15_<scenario>.cfg."""
    tag = _h.scenario_tag()
    _h.configure("BCProbe_q15_" + tag, "BCProbe_q15_" + tag + ".cfg")

    _h.section("provenance")
    for _ln in _h.provenance():
        _h.emit(_ln)
    _h.record("armed", _armed)
    _h.record("distinct_types_fired", len(_tallies))

    # fired types, most frequent first. cfg-SAFE FORMAT (q15 crash lesson):
    # BC's SaveConfigFile choked on q15's first attempt. Avoid the cfg's
    # structural chars '|' '[' ']' in values, and keep every line short --
    # src/dst go on their own keys rather than one 150-char pipe-joined line.
    _h.section("fired events (by count)")
    items = []
    for itype in _tallies.keys():
        items.append((itype, _tallies[itype]))
    items.sort(_cmp_count)
    idx = 0
    for it in items:
        itype = it[0]
        rec = it[1]
        _h.emit("e%03d = %s %s n=%d tf=%s tl=%s nsrc=%s ndst=%s"
                % (idx, _name_of(itype), _hex(itype), rec["count"],
                   _f2(rec["first_t"]), _f2(rec["last_t"]),
                   _card(rec["src_ids"]), _card(rec["dst_ids"])))
        _h.emit("e%03d.s = %s" % (idx, rec["first_src"]))
        _h.emit("e%03d.d = %s" % (idx, rec["first_dst"]))
        idx = idx + 1

    # declared-but-silent types (Q15-4). CRITICAL: emit in SMALL batches -- a
    # single string.join over ~300 names is a ~6000-char value, which is what
    # crashed the cfg writer on the first run. 8 names per line stays short.
    _h.section("never fired (declared but silent this scenario)")
    silent = []
    for nm in _et_names():
        try:
            itype = getattr(App, nm)
        except:
            continue
        if not _tallies.has_key(itype):
            silent.append(nm)
    silent.sort()
    _h.record("n_never_fired", len(silent))
    _si = 0
    while _si < len(silent):
        # 4 per line: ET_ names are long, and 8 could exceed the harness's
        # 180-char cap and clip a name.
        _h.emit("silent = " + string.join(silent[_si:_si + 4], ", "))
        _si = _si + 4

    # focus raw log (Q15-5), if any
    if _focus_log:
        _h.section("focus raw log (%d)" % len(_focus_log))
        for _i in range(len(_focus_log)):
            _h.emit("f%03d = %s" % (_i, _focus_log[_i]))

    _h.flush()
    _h.echo("q15 done -- %d distinct types fired, %d never fired (scenario %s)"
            % (len(_tallies), len(silent), tag))
