###############################################################################
# q17_bridge_graph -- the live interior (bridge + character) graph.
#
# Question(s): docs/instrumented_experiments/2026-07-13-bridge-graph-probe.md
#              Q17-1 bridge-set object roster, Q17-2 officer roster by station,
#              Q17-3 viewscreen (BridgeWindow), Q17-4 what state Character node
#              handles (GetAnimNode/GetRootNode) expose, Q17-5 lift/door objects.
# Needs combat state? Needs a loaded scenario WITH THE BRIDGE VISIBLE -- flip to
#              bridge view at least once so the "bridge" set is populated, then
#              run this. E1M1 has scripted bridge scenes (best for a non-idle
#              animation in Q17-4).
# Output:      game/BCProbe_q17_<scenario>.cfg  (<scenario> = A / B / unknown)
#
# One-shot execfile() probe -- pure read, no handlers:
#   execfile('q17_bridge_graph.py')
#
# REQUIRES probe_harness.py in game/. Reuses iter_set_objids (hardened set-walk),
# provenance(), and the buffer-only 180-cap flush. Bridge access mirrors the SDK
# (Bridge/BridgeUtils.py):
#   pBridge = App.BridgeSet_Cast(App.g_kSetManager.GetSet("bridge"))
#   pChar   = App.CharacterClass_GetObject(pBridge, stationName)
#
# PYTHON 1.5 CONSTRAINTS -- see console-probe-workflow.md
#   No "import X as Y" / no f-strings / no True/False / "except E, e:" /
#   print is a statement / dict.has_key() not "in" / keep cfg lines short.
###############################################################################

import App
import sys
import string
import probe_harness
_h = probe_harness              # no "import X as Y" in Python 1.5

_CHUNK = 0
_STATIONS = ["Helm", "Tactical", "Science", "Engineer", "XO"]
_MAX_DIR = 120                  # cap on dir() names dumped per node


def _q17_tag():
    """Scenario tag for the filename. In bridge view the rendered set is
    'bridge', so scenario_tag() alone would misread a QuickBattle -- double-check
    for the QB set to keep A/B correct."""
    t = _h.scenario_tag()
    if t == "A":
        return "A"
    try:
        if App.g_kSetManager.GetSet("QuickBattleRegion") is not None:
            return "A"
    except:
        pass
    return t


def _bridge_set():
    try:
        return App.BridgeSet_Cast(App.g_kSetManager.GetSet("bridge"))
    except:
        return None


def _bdescribe(pObj):
    """Bridge-object cast ladder (most-specific first)."""
    hits = []
    for pair in [("BridgeWindow_Cast", "BridgeWindow"),
                 ("CharacterClass_Cast", "Character"),
                 ("BridgeObjectClass_Cast", "BridgeObject")]:
        if _h._cast(pair[0], pObj):
            hits.append(pair[1])
    nm = _h._safe(pObj, "GetName", ())
    if nm is not None:
        hits.append("name='%s'" % str(nm))
    oid = _h._safe(pObj, "GetObjID", ())
    if oid is not None:
        hits.append("objid=%s" % str(oid))
    if not hits:
        hits.append("UNKNOWN")
    return string.join(hits, " ")


def _char_name(pChar):
    n = _h._safe(pChar, "GetCharacterName", ())
    if n is None:
        n = _h._safe(pChar, "GetName", ())
    return str(n)


def _dump_names(label, names):
    """Emit dir()-style name lists in short batches (stay under the 180 cap)."""
    i = 0
    n = len(names)
    while i < n and i < _MAX_DIR:
        _h.emit("%s = %s" % (label, string.join(names[i:i + 6], ", ")))
        i = i + 6


def _recon_node(pChar, method):
    """Q17-4: introspect an animation/scene node. SWIG 1.x shadow instances hide
    methods on their class and serve members via __getattr__, so we report BOTH
    the instance repr (which reveals the underlying C type, e.g.
    '<C NiAnimation instance ...>') and dir(node) + dir(node.__class__)."""
    node = _h._safe(pChar, method, ())
    if node is None:
        _h.record(method, "None/absent")
        return
    _h.record(method, "present repr=%s" % str(node))
    try:
        _dump_names(method + ".dir", dir(node))
    except:
        _h.record(method + ".dir", "FAILED")
    try:
        _dump_names(method + ".class_dir", dir(node.__class__))
    except:
        pass


# === PROBE BODY ================================================================

try:
    tag = _q17_tag()
    _h.configure("BCProbe_q17_" + tag, "BCProbe_q17_" + tag + ".cfg")

    _h.section("provenance")
    for _ln in _h.provenance():
        _h.emit(_ln)

    pBridge = _bridge_set()

    # Q17-1 -- bridge object roster
    _h.section("bridge set")
    if pBridge is None:
        _h.record("bridge_set", "None -- flip to BRIDGE VIEW then re-run")
    else:
        _h.record("bridge_set", "present")
        objs = _h.iter_set_objids(pBridge)
        _h.record("n_bridge_objects", len(objs))
        idx = 0
        for pair in objs:
            _h.emit("b%03d = %s" % (idx, _bdescribe(pair[1])))
            idx = idx + 1

    # Q17-2 -- officer roster by station
    _h.section("officers (by station)")
    first_char = None
    for _st in _STATIONS:
        pc = None
        try:
            pc = App.CharacterClass_GetObject(pBridge, _st)
        except:
            pc = None
        if pc is not None:
            _h.emit("%s = %s" % (_st, _char_name(pc)))
            if first_char is None:
                first_char = pc
        else:
            _h.emit("%s = None" % _st)

    # Q17-4 -- animation-state reconnaissance on the first character found
    _h.section("character node recon")
    if first_char is not None:
        _h.record("recon_char", _char_name(first_char))
        _recon_node(first_char, "GetRootNode")
        _recon_node(first_char, "GetAnimNode")
    else:
        _h.record("recon", "no character found")

    _n = _h.line_count()
    _h.section("summary")
    _h.record("data_lines", _n)
    if _CHUNK:
        _h.flush_chunked()
    else:
        _h.flush()
    _h.echo("q17 done (scenario=%s, %d lines)" % (tag, _h.line_count()))

except Exception, _err:
    _h.record("FATAL", "%s: %s" % (_h.exc_name(_err), str(_err)))
    _h.echo("FATAL: %s: %s" % (_h.exc_name(_err), str(_err)))
    _h.flush()

# === END PROBE BODY ============================================================
