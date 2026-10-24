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
import keyword
import sys
import types

# Setters whose first argument is a region index (so an edit targets one index).
_INDEXED_PREFIX = "SetGlowRegion"
_EMITTER_PREFIX = "SetLightEmitter"
_INDEXED_PREFIXES = (_INDEXED_PREFIX, _EMITTER_PREFIX)
# ShieldProperty setters whose first argument is a shield face (0..5), so an
# edit targets one face. Exact names: they are not region setters, and
# set_region's prefix full-replace must never treat them as one.
_FACE_SETTERS = ("SetMaxShields", "SetShieldChargePerSecond")

# Key under which a ship's articulated parts live in its model dict, alongside
# (never inside) its subsystem blocks -- see set_part / _emit_part.
_PARTS_KEY = "__parts__"

# Key under which a ship's Dauntless-authored running lights live, beside
# __parts__: {name: {"op": "create"|"edit"|"remove", <spec fields>}}. Spec
# fields are position, color, radius, period, duration (an "edit" carries only
# the ones being set). Spec 2026-10-22-spv-running-lights-design.md section 4.3.
_LIGHTS_KEY = "__lights__"
_LIGHT_FIELDS = ("position", "color", "radius", "period", "duration")
# Setters only a running light has -- how a find(name) block that edits a
# light is told apart from a subsystem block.
_LIGHT_ONLY_SETTERS = ("SetPeriod", "SetDuration", "SetColor")
# Python 1.5 reserved words (stock BC compiles emitted hardpoint text with it).
# `print`/`exec` are keywords there but not in Python 3, so keyword.iskeyword
# misses them; `access` was a 1.5 keyword too.
_PY15_KEYWORDS = frozenset((
    "access", "and", "assert", "break", "class", "continue", "def", "del",
    "elif", "else", "except", "exec", "finally", "for", "from", "global",
    "if", "import", "in", "is", "lambda", "not", "or", "pass", "print",
    "raise", "return", "try", "while"))
_RESERVED_IDENTS = ("p", "c", "find", "App", "leaf")

_NOT_SET = object()   # sentinel: distinguishes "no prior sys.modules['App']" from None


class _Recorder:
    """Proxy returned by the recording find; records every method call as
    (name, args) into the shared list. Truthy + not-None so `if p is not None`
    guards always pass."""

    def __init__(self, calls, name=None):
        self._calls = calls
        self._name = name

    def __getattr__(self, name):
        def rec(*args):
            self._calls.append((name, args))
            return None
        return rec


class _ColorRecorder:
    """Stands in for App.TGColorA() while recording a light's colour."""

    def __init__(self):
        self.rgba = (0.0, 0.0, 0.0, 0.0)

    def SetRGBA(self, r, g, b, a):
        self.rgba = (r, g, b, a)


class _LightRecorder:
    """Stands in for a BlinkingLightProperty created by a create block."""

    def __init__(self, entry):
        self._entry = entry

    def SetPosition(self, x, y, z):
        self._entry["position"] = (x, y, z)

    def SetColor(self, color):
        self._entry["color"] = tuple(color.rgba[:3])

    def SetRadius(self, v):
        self._entry["radius"] = v

    def SetPeriod(self, v):
        self._entry["period"] = v

    def SetDuration(self, v):
        self._entry["duration"] = v


def _make_find(per_sub):
    def find(name):
        return _Recorder(per_sub.setdefault(name, []), name)
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

    DAUNTLESS_ENV = 2

    class _Mgr:
        def __init__(self, lights):
            self._lights = lights

        def RegisterLocalTemplate(self, part):
            pass

        def RemoveTemplate(self, prop):
            self._lights[prop._name] = {"op": "remove"}

    def __init__(self, parts, lights=None):
        self._parts = parts
        self._lights = {} if lights is None else lights
        self.g_kModelPropertyManager = self._Mgr(self._lights)

    def ArticulatedPartProperty_Create(self, name):
        return _Recorder(self._parts.setdefault(name, []))

    def BlinkingLightProperty_Create(self, name):
        entry = self._lights.setdefault(name, {})
        entry["op"] = "create"
        return _LightRecorder(entry)

    def TGColorA(self):
        return _ColorRecorder()

    def DauntlessAttachTemplate(self, prop):
        pass


def record_fn(fn) -> dict:
    """{subsystem: [(setter, args), ...]} for ONE override-shaped function, by
    executing it against a recording `find` and a recording `App`.

    A function with articulated parts also gets a "__parts__" entry:
    {..., "__parts__": {part_name: [(setter, args), ...]}}.
    """
    per_sub: dict = {}
    parts: dict = {}
    lights: dict = {}
    prev_app = sys.modules.get("App", _NOT_SET)
    sys.modules["App"] = _RecordingApp(parts, lights)
    try:
        fn(_make_find(per_sub))
    finally:
        if prev_app is _NOT_SET:
            del sys.modules["App"]
        else:
            sys.modules["App"] = prev_app
    _absorb_light_edits(per_sub, lights)
    if parts:
        per_sub[_PARTS_KEY] = parts
    if lights:
        per_sub[_LIGHTS_KEY] = lights
    return per_sub


_LIGHT_SETTER_FIELD = {"SetPosition": "position", "SetColor": "color",
                       "SetRadius": "radius", "SetPeriod": "period",
                       "SetDuration": "duration"}


def _absorb_light_edits(per_sub, lights) -> None:
    """Move find(name) blocks that edit a running light out of per_sub and into
    `lights` as "edit" entries, and drop the empty find a remove leaves behind.
    A block is a light edit when it carries a light-only setter."""
    for name in list(per_sub):
        calls = per_sub[name]
        if lights.get(name, {}).get("op") == "remove" and not calls:
            del per_sub[name]
            continue
        if not any(s in _LIGHT_ONLY_SETTERS for s, _a in calls):
            continue
        entry = lights.setdefault(name, {"op": "edit"})
        kept = []
        for setter, args in calls:
            field = _LIGHT_SETTER_FIELD.get(setter)
            if field is None:
                kept.append((setter, args))
            elif field == "color":
                entry["color"] = tuple(args[0].rgba[:3])
            elif field == "position":
                entry["position"] = tuple(args)
            else:
                entry[field] = args[0]
        if kept:
            per_sub[name] = kept
        else:
            del per_sub[name]


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
    if (setter.startswith(_INDEXED_PREFIXES) or setter in _FACE_SETTERS) and args:
        return (setter, args[0])      # same setter AND same index / face
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


def unset_setter(models, leaf, subsystem, setter) -> None:
    """Remove every `setter` call from a subsystem's call list (the SPV's
    "Reset to Auto" for SetPhysicalParent). Other setters are untouched; an
    emptied list emits no block."""
    calls = models.get(leaf, {}).get(subsystem)
    if calls:
        models[leaf][subsystem] = [(s, a) for (s, a) in calls if s != setter]


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


def set_running_light(models, leaf, name, spec, new) -> None:
    """Record one running-light change in the ship's __lights__ map.

    spec None removes: a light this file creates simply loses its create entry
    (never a RemoveTemplate for a template the file itself makes); any other
    light gets a "remove" entry. A spec on a created light replaces its fields;
    `new` creates; otherwise an "edit" carrying every field."""
    if spec is not None:
        missing = [k for k in _LIGHT_FIELDS if spec.get(k) is None]
        if missing:
            raise ValueError("running light %r: partial spec, missing %s"
                             % (name, ", ".join(missing)))
    per_sub = models.setdefault(leaf, {})
    lights = per_sub.get(_LIGHTS_KEY, {})
    existing = lights.get(name)
    created = existing is not None and existing.get("op") == "create"
    if spec is None:
        if created:
            del lights[name]
            if not lights:
                per_sub.pop(_LIGHTS_KEY, None)
            return
        entry = {"op": "remove"}
    else:
        entry = dict((k, spec[k]) for k in _LIGHT_FIELDS if k in spec)
        entry["op"] = "create" if (created or new) else "edit"
    per_sub.setdefault(_LIGHTS_KEY, {})[name] = entry


def _rekey(d, old, new) -> dict:
    """`d` with key `old` renamed `new`, in the same position."""
    return dict(((new if k == old else k), v) for k, v in d.items())


def rename_running_light(models, leaf, old, new, require_created=True) -> None:
    """Rename light `old` to `new` in the ship's model: its __lights__ entry
    and any setter list stored under `old` (SetPhysicalParent) are re-keyed
    in place, so the emitted order is stable.

    Refused (ValueError, the model untouched) when `new` already names a
    light entry or a non-empty setter list, or -- with `require_created`, the
    stock file's rule -- when `old` is not a light this file creates: any
    other light is a template from the game's own hardpoint file, which is
    keyed by name and cannot be renamed. A mod file passes False after it has
    renamed the author's own Create (mod_hardpoint_writer)."""
    per_sub = models.setdefault(leaf, {})
    lights = per_sub.get(_LIGHTS_KEY, {})
    if new in lights or per_sub.get(new):
        raise ValueError("cannot rename light %r to %r: %r already exists"
                         % (old, new, new))
    entry = lights.get(old)
    if require_created and (entry is None or entry.get("op") != "create"):
        raise ValueError("cannot rename light %r: it is not a light Dauntless "
                         "created" % (old,))
    # An emptied list under `new` (an unset earlier in the same write) would
    # otherwise overwrite the moved one in the re-key below.
    per_sub.pop(new, None)
    if entry is not None:
        per_sub[_LIGHTS_KEY] = _rekey(lights, old, new)
    if old in per_sub:
        models[leaf] = per_sub = _rekey(per_sub, old, new)


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
    (subsystem, "__unset__", setter) 3-tuples, (old, "__rename_light__", new)
    3-tuples, and/or (subsystem, "__region__"/"__emitter__", index, calls) 4-tuples."""
    if len(edit) == 4 and edit[1] == "__region__":
        subsystem, _tag, index, calls = edit
        set_region(models, leaf, subsystem, index, calls)
    elif len(edit) == 4 and edit[1] == "__emitter__":
        subsystem, _tag, index, calls = edit
        set_region(models, leaf, subsystem, index, calls, prefix=_EMITTER_PREFIX)
    elif len(edit) == 3 and edit[1] == "__part__":
        name, _tag, calls = edit
        set_part(models, leaf, name, calls)
    elif len(edit) == 3 and edit[1] == "__running_light__":
        name, _tag, payload = edit
        set_running_light(models, leaf, name, payload["spec"], payload["new"])
    elif len(edit) == 3 and edit[1] == "__rename_light__":
        rename_running_light(models, leaf, edit[0], edit[2])
    elif len(edit) == 3 and edit[1] == "__unset__":
        unset_setter(models, leaf, edit[0], edit[2])
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
    ident = "".join(c if (c.isascii() and (c.isalnum() or c == "_")) else "_"
                    for c in name)
    if not ident or ident[0].isdigit():
        ident = "_" + ident
    ident = ident.lower()
    if keyword.iskeyword(ident) or ident in _PY15_KEYWORDS:
        ident += "_"
    return ident


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


def _unique_ident(name, used) -> str:
    """_ident_for(name), suffixed _2, _3... when it (or its _color twin)
    collides with an earlier light's variable. Lights are user-named, so two
    names can map to the same identifier."""
    base = _ident_for(name)
    ident, n = base, 1
    while ident in used or ident + "_color" in used:
        n += 1
        ident = "%s_%d" % (base, n)
    used.add(ident)
    used.add(ident + "_color")
    return ident


def _fnum(v) -> str:
    return repr(float(v))


def _emit_light_create(lines, name, entry, used) -> None:
    var = _unique_ident(name, used)
    r, g, b = entry["color"]
    x, y, z = entry["position"]
    lines.append('    ' + env_guard(2))
    lines.append('        %s = App.BlinkingLightProperty_Create(%s)' % (var, _lit(name)))
    lines.append('        %s.SetPosition(%s, %s, %s)' % (var, _fnum(x), _fnum(y), _fnum(z)))
    lines.append('        %s_color = App.TGColorA()' % var)
    lines.append('        %s_color.SetRGBA(%s, %s, %s, 1.0)' % (var, _fnum(r), _fnum(g), _fnum(b)))
    lines.append('        %s.SetColor(%s_color)' % (var, var))
    lines.append('        %s.SetRadius(%s)' % (var, _fnum(entry["radius"])))
    lines.append('        %s.SetPeriod(%s)' % (var, _fnum(entry["period"])))
    lines.append('        %s.SetDuration(%s)' % (var, _fnum(entry["duration"])))
    lines.append('        App.g_kModelPropertyManager.RegisterLocalTemplate(%s)' % var)
    lines.append('        App.DauntlessAttachTemplate(%s)' % var)


def _emit_light_edit(lines, name, entry) -> None:
    lines.append('    ' + env_guard(2))
    lines.append('        p = find(%s)' % _lit(name))
    lines.append('        if p is not None:')
    if "position" in entry:
        x, y, z = entry["position"]
        lines.append('            p.SetPosition(%s, %s, %s)' % (_fnum(x), _fnum(y), _fnum(z)))
    if "color" in entry:
        r, g, b = entry["color"]
        lines.append('            c = App.TGColorA()')
        lines.append('            c.SetRGBA(%s, %s, %s, 1.0)' % (_fnum(r), _fnum(g), _fnum(b)))
        lines.append('            p.SetColor(c)')
    for key, setter in (("radius", "SetRadius"), ("period", "SetPeriod"),
                        ("duration", "SetDuration")):
        if key in entry:
            lines.append('            p.%s(%s)' % (setter, _fnum(entry[key])))


def _emit_light_remove(lines, name) -> None:
    lines.append('    ' + env_guard(2))
    lines.append('        p = find(%s)' % _lit(name))
    lines.append('        if p is not None:')
    lines.append('            App.g_kModelPropertyManager.RemoveTemplate(p)')


def _emit_function(leaf, per_sub, fn_name=None) -> str:
    out = ["def %s(find):" % (fn_name or "_" + leaf), '    """%s."""' % leaf]
    non_empty = [(s, c) for s, c in per_sub.items()
                 if s not in (_PARTS_KEY, _LIGHTS_KEY) and c]
    parts = dict((n, c) for n, c in per_sub.get(_PARTS_KEY, {}).items() if c)
    lights = per_sub.get(_LIGHTS_KEY, {})
    if not non_empty and not parts and not lights:
        out.append("    return")
        return "\n".join(out)
    if parts or lights:
        # One local import covers every part block below; `import App` here
        # (not at module scope) keeps a part-free ship's function -- and
        # read_models reading it -- free of any dependency on App at all.
        out.append("    import App")
    # Creates first, so a later find(name) (SetPhysicalParent) sees the new
    # template; then subsystem blocks; then light edits/removes; then parts.
    used = set(_RESERVED_IDENTS)
    for name, entry in lights.items():
        if entry["op"] == "create":
            _emit_light_create(out, name, entry, used)
    for subsystem, calls in non_empty:
        out.append("    p = find(%s)" % _lit(subsystem))
        out.append("    if p is not None:")
        for setter, args in calls:
            out.append("        p.%s(%s)" % (setter, _fmt_args(args)))
    # Edits/removes in name order: read-back rebuilds them in find order, which
    # a SetPhysicalParent block can shift, so only a sorted order is stable.
    for name in sorted(lights):
        entry = lights[name]
        if entry["op"] == "edit":
            _emit_light_edit(out, name, entry)
        elif entry["op"] == "remove":
            _emit_light_remove(out, name)
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
