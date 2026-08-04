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

# Setters whose first argument is a region index (so an edit targets one index).
_INDEXED_PREFIX = "SetGlowRegion"
_EMITTER_PREFIX = "SetLightEmitter"
_INDEXED_PREFIXES = (_INDEXED_PREFIX, _EMITTER_PREFIX)


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


def read_models(module) -> dict:
    """{leaf: {subsystem: [(setter, args), ...]}} by executing each override fn."""
    models: dict = {}
    for leaf, fn in module.OVERRIDES.items():
        per_sub: dict = {}
        fn(_make_find(per_sub))
        models[leaf] = per_sub
    return models


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


def _emit_function(leaf, per_sub) -> str:
    out = ["def _%s(find):" % leaf, '    """%s."""' % leaf]
    non_empty = [(s, c) for s, c in per_sub.items() if c]
    if not non_empty:
        out.append("    return")
    else:
        for subsystem, calls in non_empty:
            out.append("    p = find(%s)" % _lit(subsystem))
            out.append("    if p is not None:")
            for setter, args in calls:
                out.append("        p.%s(%s)"
                           % (setter, ", ".join(_lit(a) for a in args)))
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
