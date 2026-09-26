"""Pure tooling to read, edit, and emit engine/appc/hardpoint_overrides.py.

The override file is machine-owned: one function per ship, one block per
subsystem, plain Appc setter calls. We recover a ship's model by EXECUTING its
function against a recording `find` (the functions are pure straight-line setter
calls), edit the model, and re-emit the whole file deterministically.

Design: docs/superpowers/specs/2026-07-25-spv-hardpoint-value-override-editing-design.md

Notes (reverse-engineering provenance):
- Data-bag read-back quirk: `TGModelProperty` stores `Set<F>(*args)` under key
  `(F, args[:-1])` with value `args[-1]`, so multi-arg setters are NOT
  readable via a plain `Get<F>(i)` — read them via `prop._data` or by passing
  the same leading args (e.g. `GetGlowRegionExtent(0, -2.0) -> 2.0`).
  Single-arg setters like `SetRadius` read back normally.
- Root-shadow hardpoint gap: a project-root shadow hardpoint (none exist
  today) would load through normal import machinery, NOT `_SDKLoader`, so the
  SDK-loader override hook would not fire for it. Prefer an override entry
  here over a shadow.
"""
from __future__ import annotations

import ast
import json
import sys
import types

# Setters whose first argument is a region index (so an edit targets one index).
_INDEXED_PREFIX = "SetGlowRegion"
_EMITTER_PREFIX = "SetLightEmitter"
_INDEXED_PREFIXES = (_INDEXED_PREFIX, _EMITTER_PREFIX)

# Key under which a ship's articulated parts live in its model dict, alongside
# (never inside) its subsystem blocks -- see set_part / _emit_part.
_PARTS_KEY = "__parts__"

_NOT_SET = object()   # sentinel: distinguishes "no prior sys.modules['App']" from None


class _Recorder:
    """Proxy returned by the recording find; records every method call as
    (name, args) into the shared list. Truthy + not-None so `if p is not None`
    guards always pass."""

    def __init__(self, calls):
        self._calls = calls

    def __getattr__(self, name):
        def rec(*args):
            self._calls.append((name, args))
            return None
        return rec


def _make_find(per_sub):
    def find(name):
        return _Recorder(per_sub.setdefault(name, []))
    return find


class _RecordingApp:
    """Fake `App` module the generated `import App` binds to while recording.

    A part block has no `find` call to hook -- it calls
    `App.ArticulatedPartProperty_Create(name)` directly -- so the recorder
    needs its own hook onto `App` itself. This stands in for the real App
    shim during read_models exactly as `_Recorder` stands in for a live
    property, so recovering a ship's parts never depends on the real App
    module (or its side effects on a real g_kModelPropertyManager).

    `DAUNTLESS_ENV` must be present here too: a part block's guard is now
    `if hasattr(App, "DAUNTLESS_ENV") and App.DAUNTLESS_ENV >= N:`, and
    without it read_models would skip every part block, silently dropping
    all parts on the next save."""

    DAUNTLESS_ENV = 1

    class _Mgr:
        def RegisterLocalTemplate(self, part):
            pass

    def __init__(self, parts):
        self._parts = parts
        self.g_kModelPropertyManager = self._Mgr()

    def ArticulatedPartProperty_Create(self, name):
        return _Recorder(self._parts.setdefault(name, []))


def record_fn(fn) -> dict:
    """{subsystem: [(setter, args), ...]} for ONE override-shaped function, by
    executing it against a recording `find` and a recording `App`.

    A function with articulated parts also gets a "__parts__" entry:
    {..., "__parts__": {part_name: [(setter, args), ...]}}.
    """
    per_sub: dict = {}
    parts: dict = {}
    prev_app = sys.modules.get("App", _NOT_SET)
    sys.modules["App"] = _RecordingApp(parts)
    try:
        fn(_make_find(per_sub))
    finally:
        if prev_app is _NOT_SET:
            del sys.modules["App"]
        else:
            sys.modules["App"] = prev_app
    if parts:
        per_sub[_PARTS_KEY] = parts
    return per_sub


def read_models(module) -> dict:
    """{leaf: {subsystem: [(setter, args), ...]}} by executing each override fn.

    A leaf with articulated parts also gets a "__parts__" entry:
    {leaf: {..., "__parts__": {part_name: [(setter, args), ...]}}}.
    """
    return dict((leaf, record_fn(fn)) for leaf, fn in module.OVERRIDES.items())


def read_models_from_source(text) -> dict:
    """read_models, but from emitted source text rather than an already
    imported module -- what a round-trip (save, then re-read) actually has."""
    module = types.ModuleType("_hardpoint_overrides_roundtrip")
    exec(compile(text, "<hardpoint_overrides>", "exec"), module.__dict__)  # noqa: S102
    return read_models(module)


def _replace_key(setter, args):
    if setter.startswith(_INDEXED_PREFIXES) and args:
        return (setter, args[0])      # same setter AND same index
    return (setter,)


def set_setter(models, leaf, subsystem, setter, args) -> None:
    per_sub = models.setdefault(leaf, {})
    calls = per_sub.setdefault(subsystem, [])
    key = _replace_key(setter, args)
    for i, (s, a) in enumerate(calls):
        if _replace_key(s, a) == key:
            calls[i] = (setter, tuple(args))
            return
    calls.append((setter, tuple(args)))


def set_part(models, leaf, name, calls) -> None:
    """Replace one articulated part's whole call list -- find-or-CREATE, full
    replace like set_region full-replaces one glow-region index. `calls` is
    ordered [(setter, args), ...] -- the current authoring surface is
    SetAnchor, SetTransitionSeconds, SetStatePose (one per authored state),
    SetBreakFraction, in any combination (spec 2026-09-25 section 3). The
    legacy SetPivot/SetAxis/SetStateAngle/SetDetachFraction are still
    accepted and load correctly, but the writer never emits them again."""
    per_sub = models.setdefault(leaf, {})
    parts = per_sub.setdefault(_PARTS_KEY, {})
    parts[name] = [(s, tuple(a)) for (s, a) in calls]


def set_region(models, leaf, subsystem, index, calls, prefix=_INDEXED_PREFIX) -> None:
    """Replace all <prefix>*(index, ...) calls for a subsystem with `calls`
    (ordered [(setter, args), ...], each args starting with `index`). Other
    setters (e.g. SetRadius, or the other indexed prefix) and other indices
    of the same prefix are left intact."""
    per_sub = models.setdefault(leaf, {})
    existing = per_sub.setdefault(subsystem, [])
    kept = [(s, a) for (s, a) in existing
            if not (s.startswith(prefix) and a and a[0] == index)]
    kept.extend((s, tuple(a)) for (s, a) in calls)
    per_sub[subsystem] = kept


def apply_edit(models, leaf, edit) -> None:
    """Apply one SPV edit tuple (see HardpointOverridesFileTarget.write):
    (subsystem, setter, args) 3-tuples, (name, "__part__", calls) 3-tuples,
    and/or (subsystem, "__region__"/"__emitter__", index, calls) 4-tuples."""
    if len(edit) == 4 and edit[1] == "__region__":
        subsystem, _tag, index, calls = edit
        set_region(models, leaf, subsystem, index, calls)
    elif len(edit) == 4 and edit[1] == "__emitter__":
        subsystem, _tag, index, calls = edit
        set_region(models, leaf, subsystem, index, calls, prefix=_EMITTER_PREFIX)
    elif len(edit) == 3 and edit[1] == "__part__":
        name, _tag, calls = edit
        set_part(models, leaf, name, calls)
    else:
        subsystem, setter, args = edit
        set_setter(models, leaf, subsystem, setter, args)


# ── Emission ────────────────────────────────────────────────────────────────

_HEADER = '''"""Machine-owned hardpoint overrides — edited by the Ship Property Viewer.

Do NOT hand-edit: the SPV regenerates this file on save. One function per ship,
one block per subsystem, plain Appc setter calls.
Design: docs/superpowers/specs/2026-07-25-spv-hardpoint-value-override-editing-design.md
"""


def apply(leaf):
    """Run a ship's override function from the SDK-loader hook, if any."""
    fn = OVERRIDES.get(leaf)
    if fn is None:
        return
    import App

    mgr = App.g_kModelPropertyManager

    def find(name):
        return mgr.FindByName(name, App.TGModelPropertyManager.LOCAL_TEMPLATES)

    fn(find)'''


def _lit(v) -> str:
    if isinstance(v, str):
        return json.dumps(v)          # valid double-quoted Python string literal
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, float):
        return repr(v)
    return str(v)


def _fmt_args(args) -> str:
    """Render a setter's positional args as the text between its parens."""
    return ", ".join(_lit(a) for a in args)


def _ident_for(name) -> str:
    """A valid Python identifier for `name`, to hold one part's property
    instance in its emitted block. BC part names are already distinct within
    one ship's hardpoint file, so this only needs to be a legal identifier,
    not independently unique."""
    ident = "".join(c if (c.isalnum() or c == "_") else "_" for c in name)
    if not ident or ident[0].isdigit():
        ident = "_" + ident
    return ident.lower()


def env_guard(level: int = 1) -> str:
    """The Python-1.5-safe guard every Dauntless-only emitted block sits
    under (spec 2026-09-26 section 4.3)."""
    return 'if hasattr(App, "DAUNTLESS_ENV") and App.DAUNTLESS_ENV >= %d:' % level


def _emit_part(lines, name, calls) -> None:
    """Append a find-or-CREATE block for one articulated part to `lines`.

    The guard sits on the versioned `App.DAUNTLESS_ENV` marker (not on a
    borrowed function name like `ArticulatedPartProperty_Create`): stock BC
    has never heard of this property type, so there is no instance to guard
    on until Create succeeds, and gating on the marker lets the guard level
    be bumped independently of any one Appc surface. It is Python-1.5-safe --
    hasattr is a two-argument builtin -- and so is everything inside it: no
    True/False literals, no f-strings.

    hardpoint_overrides.py does not strictly need the guard (stbc.exe never
    loads it), but emitting the identical block in both homes means the SPV
    has exactly one part emitter to maintain, and the text can be lifted
    straight into a mod's own hardpoint file. See spec section 2.3.
    """
    var = _ident_for(name)
    lines.append('    ' + env_guard())
    lines.append('        %s = App.ArticulatedPartProperty_Create(%s)'
                 % (var, _lit(name)))
    for setter, args in calls:
        lines.append('        %s.%s(%s)' % (var, setter, _fmt_args(args)))
    lines.append('        App.g_kModelPropertyManager.RegisterLocalTemplate(%s)' % var)


def _emit_function(leaf, per_sub, fn_name=None) -> str:
    out = ["def %s(find):" % (fn_name or "_" + leaf), '    """%s."""' % leaf]
    non_empty = [(s, c) for s, c in per_sub.items() if s != _PARTS_KEY and c]
    parts = dict((n, c) for n, c in per_sub.get(_PARTS_KEY, {}).items() if c)
    if not non_empty and not parts:
        out.append("    return")
        return "\n".join(out)
    if parts:
        # One local import covers every part block below; `import App` here
        # (not at module scope) keeps a part-free ship's function -- and
        # read_models reading it -- free of any dependency on App at all.
        out.append("    import App")
    for subsystem, calls in non_empty:
        out.append("    p = find(%s)" % _lit(subsystem))
        out.append("    if p is not None:")
        for setter, args in calls:
            out.append("        p.%s(%s)" % (setter, _fmt_args(args)))
    for name, calls in parts.items():
        _emit_part(out, name, calls)
    return "\n".join(out)


def _emit_overrides(leaves) -> str:
    out = ["OVERRIDES = {"]
    for leaf in leaves:
        out.append('    "%s": _%s,' % (leaf, leaf))
    out.append("}")
    return "\n".join(out)


def emit(models) -> str:
    chunks = [_HEADER]
    for leaf, per_sub in models.items():
        chunks.append(_emit_function(leaf, per_sub))
    chunks.append(_emit_overrides(models.keys()))
    text = "\n\n\n".join(chunks) + "\n"
    ast.parse(text)                    # raises SyntaxError on a bad emit
    return text
