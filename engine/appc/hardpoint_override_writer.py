"""Pure tooling to read, edit, and emit engine/appc/hardpoint_overrides.py.

The override file is machine-owned: one function per ship, one block per
subsystem, plain Appc setter calls. We recover a ship's model by EXECUTING its
function against a recording `find` (the functions are pure straight-line setter
calls), edit the model, and re-emit the whole file deterministically.

Design: docs/superpowers/specs/2026-07-25-spv-hardpoint-value-override-editing-design.md
"""
from __future__ import annotations

import ast
import json

# Setters whose first argument is a region index (so an edit targets one index).
_INDEXED_PREFIX = "SetGlowRegion"


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
    if setter.startswith(_INDEXED_PREFIX) and args:
        return (setter, args[0])      # same setter AND same region index
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
    if not per_sub:
        out.append("    return")
    else:
        for subsystem, calls in per_sub.items():
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
