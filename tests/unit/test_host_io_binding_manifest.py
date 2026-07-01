"""The engine.host_io native-binding manifest + startup validation.

Mirror of tests/unit/test_renderer_binding_manifest.py, pointed at the new
host_io façade (the non-render surface of _dauntless_host). The manifest
(`_REQUIRED_BINDINGS` / `_OPTIONAL_BINDINGS`) exists so a stale/incomplete
`_dauntless_host` .so is caught loudly at real-host boot rather than as a
silently-dead feature mid-mission. These tests:

  1. keep the hand-maintained manifest honest by deriving ground truth from the
     façade's own `_h.NAME` / `getattr(_h, "NAME")` references (the primary
     guard — you cannot add/remove a wrapper without updating the manifest);
  2. exercise validate_bindings() against synthetic fakes for the
     clean / missing-required cases;
  3. lock the "never invoked at import time" contract.

All pure-Python — no GL, no real host boot.
"""
import ast
import logging
import pathlib
import types

import pytest

import engine.host_io as host_io

_SRC = pathlib.Path(host_io.__file__).read_text()

# `keys` is a submodule of _dauntless_host, not a callable binding, so the
# façade references `_h.keys` (attribute access) as infrastructure for
# verify_keys(). It is intentionally excluded from the callable manifest and
# validated separately by validate_bindings (which asserts hasattr(_h, "keys")).
_NON_BINDING_ATTRS = {"keys"}


def _collect_h_refs():
    """Walk engine/host_io.py's AST for the façade's real `_h` references.

    Returns (hard, soft, dynamic):
      hard    - names accessed as `_h.NAME` (attribute access)
      soft    - names accessed as getattr/hasattr(_h, "NAME") string literals
      dynamic - dumps of any getattr/hasattr(_h, <non-literal>) call

    validate_bindings() and verify_keys() are skipped: they legitimately do
    `hasattr(_h, ...)` / touch `_h.keys` as infrastructure, not as a wrapper.
    AST (not regex) is used so `_h.NAME` mentions inside comments/docstrings and
    the manifest's own string-literal frozensets are ignored.
    """
    hard: set[str] = set()
    soft: set[str] = set()
    dynamic: list[str] = []

    class _Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            if node.name in ("validate_bindings", "verify_keys"):
                return  # infrastructure — not a façade wrapper
            self.generic_visit(node)

        def visit_Attribute(self, node):
            if isinstance(node.value, ast.Name) and node.value.id == "_h":
                hard.add(node.attr)
            self.generic_visit(node)

        def visit_Call(self, node):
            fn = node.func
            if (isinstance(fn, ast.Name) and fn.id in ("getattr", "hasattr")
                    and node.args and isinstance(node.args[0], ast.Name)
                    and node.args[0].id == "_h"):
                key = node.args[1] if len(node.args) > 1 else None
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    soft.add(key.value)
                else:
                    dynamic.append(ast.dump(node))
            self.generic_visit(node)

    _Visitor().visit(ast.parse(_SRC))
    return hard, soft, dynamic


def _full_fake():
    """A fake `_h` exposing every binding in the manifest, plus a keys stub."""
    ns = types.SimpleNamespace()
    for name in host_io._REQUIRED_BINDINGS | host_io._OPTIONAL_BINDINGS:
        setattr(ns, name, lambda *a, **k: None)
    ns.keys = types.SimpleNamespace()  # validate_bindings asserts this exists
    return ns


# ── 1. Manifest ↔ façade sync (the primary guard) ────────────────────────────

def test_manifest_matches_facade_references():
    hard, soft, dynamic = _collect_h_refs()
    # `_h.keys` is a submodule reference (infrastructure for verify_keys), not a
    # callable binding — excluded from the callable manifest by design.
    required_expected = hard - soft - _NON_BINDING_ATTRS
    optional_expected = soft - _NON_BINDING_ATTRS

    assert host_io._REQUIRED_BINDINGS == required_expected, (
        "host_io._REQUIRED_BINDINGS is out of sync with the façade's `_h.NAME` "
        "calls. Added/removed: "
        + str(host_io._REQUIRED_BINDINGS ^ required_expected)
    )
    assert host_io._OPTIONAL_BINDINGS == optional_expected, (
        "host_io._OPTIONAL_BINDINGS is out of sync with the façade's "
        "getattr/hasattr(_h, ...) guards. Added/removed: "
        + str(host_io._OPTIONAL_BINDINGS ^ optional_expected)
    )


def test_optional_is_empty_for_now():
    # get_camera_world_pos is being deleted in a later task, not tracked here;
    # there are no optional bindings yet. Lock that so a future addition is
    # a deliberate manifest edit, not an accident.
    assert host_io._OPTIONAL_BINDINGS == frozenset()


def test_no_dynamic_h_access_in_wrappers():
    # A wrapper reaching `_h` through a non-literal name would be invisible to
    # the sync test above — forbid it so the manifest can't silently drift.
    _, _, dynamic = _collect_h_refs()
    assert dynamic == [], (
        "dynamic getattr/hasattr(_h, <non-literal>) found in a host_io wrapper; "
        "the manifest can no longer be verified against it:\n" + "\n".join(dynamic)
    )


# ── 2. validate_bindings() behaviour ─────────────────────────────────────────

def test_validate_clean_when_all_present(monkeypatch):
    monkeypatch.setattr(host_io, "_h", _full_fake())
    assert host_io.validate_bindings() == []
    assert host_io.validate_bindings(strict=True) == []  # no raise


def test_validate_reports_missing_required(monkeypatch, caplog):
    fake = _full_fake()
    delattr(fake, "shield_hit")  # a required binding
    monkeypatch.setattr(host_io, "_h", fake)

    with caplog.at_level(logging.ERROR, logger="engine.host_io"):
        missing = host_io.validate_bindings()
    assert "shield_hit" in missing
    assert "shield_hit" in caplog.text

    with pytest.raises(RuntimeError, match="shield_hit"):
        host_io.validate_bindings(strict=True)


def test_validate_reports_missing_keys_submodule(monkeypatch, caplog):
    # The `keys` submodule is treated as a required entry: an editing slip in
    # host_bindings.cc that drops the submodule must be caught, not silently
    # break input verification.
    fake = _full_fake()
    delattr(fake, "keys")
    monkeypatch.setattr(host_io, "_h", fake)

    with caplog.at_level(logging.ERROR, logger="engine.host_io"):
        missing = host_io.validate_bindings()
    assert "keys" in missing

    with pytest.raises(RuntimeError, match="keys"):
        host_io.validate_bindings(strict=True)


def test_validate_headless_returns_empty(monkeypatch):
    # _h is None (module not built / headless) is a legitimately different
    # condition from a stale build — validate_bindings must not raise.
    monkeypatch.setattr(host_io, "_h", None)
    assert host_io.validate_bindings() == []
    assert host_io.validate_bindings(strict=True) == []


# ── 3. "never fires at import" contract ──────────────────────────────────────

def test_validate_not_invoked_at_module_scope():
    # validate_bindings must be called only from the real-host boot path, never
    # at import time (which would fire against the real _h during every test).
    tree = ast.parse(_SRC)
    for node in tree.body:
        called = (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                  and isinstance(node.value.func, ast.Name)
                  and node.value.func.id == "validate_bindings")
        assert not called, "validate_bindings() is called at module scope"
