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


# ── 4. verify_keys() safety ───────────────────────────────────────────────────

def test_verify_keys_no_raise_when_keys_match(monkeypatch, caplog):
    # The boot path calls verify_keys() unconditionally after validate_bindings().
    # It must be safe (non-fatal) when the host `keys` submodule agrees with
    # engine.input_map's table — mismatches are logged, never raised.
    from engine import input_map

    class _MatchingKeys:
        # Every attribute resolves to input_map's own expected code, so
        # verify_against_host finds zero mismatches.
        def __getattr__(self, attr):
            for name, code in input_map.GLFW_KEYS.items():
                if input_map._host_key_attr(name) == attr:
                    return code
            raise AttributeError(attr)

    fake = _full_fake()
    fake.keys = _MatchingKeys()
    monkeypatch.setattr(host_io, "_h", fake)

    with caplog.at_level(logging.WARNING, logger="engine.host_io"):
        host_io.verify_keys()  # must not raise
    assert "disagrees" not in caplog.text


def test_verify_keys_no_raise_when_headless(monkeypatch):
    # _h is None (not built / headless) — verify_keys must be a silent no-op.
    monkeypatch.setattr(host_io, "_h", None)
    host_io.verify_keys()  # must not raise


# ── 5. Boot wiring: run() validates the host_io façade at the same point ──────

def test_run_boot_path_validates_host_io_facade():
    # Task 5's wiring: host_loop.run() must validate the host_io façade at boot
    # right next to the renderer façade, so a stale/incomplete .so missing a
    # REQUIRED host_io binding fails loudly at boot instead of no-opping
    # mid-mission. Assert the boot path calls both host_io.validate_bindings and
    # host_io.verify_keys (AST, so a comment mention wouldn't satisfy it), and
    # that they sit adjacent to the renderer's r.validate_bindings check.
    import pathlib as _pathlib
    from engine import host_loop

    src = _pathlib.Path(host_loop.__file__).read_text()
    tree = ast.parse(src)

    run_fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == "run"),
        None,
    )
    assert run_fn is not None, "host_loop.run() not found"

    def _facade_call(node):
        """Return ('facade', 'method') for a `<name>.<method>(...)` call stmt."""
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)):
            return None
        fn = node.value.func
        if (isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name)):
            return (fn.value.id, fn.attr)
        return None

    calls = [c for c in (_facade_call(n) for n in run_fn.body) if c is not None]

    assert ("r", "validate_bindings") in calls, (
        "renderer façade boot validation went missing from run()"
    )
    assert ("host_io", "validate_bindings") in calls, (
        "run() must call host_io.validate_bindings() at boot"
    )
    assert ("host_io", "verify_keys") in calls, (
        "run() must call host_io.verify_keys() at boot"
    )

    # Both host_io checks must sit immediately after the renderer check, so the
    # two façades are validated at the same boot point.
    r_idx = calls.index(("r", "validate_bindings"))
    assert calls[r_idx + 1] == ("host_io", "validate_bindings")
    assert calls[r_idx + 2] == ("host_io", "verify_keys")
