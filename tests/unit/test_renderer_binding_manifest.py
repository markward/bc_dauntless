"""The engine.renderer native-binding manifest + startup validation.

The manifest (`_REQUIRED_BINDINGS` / `_OPTIONAL_BINDINGS`) exists so a
stale/incomplete `_dauntless_host` .so is caught loudly at real-host boot rather
than as a silently-dead feature mid-mission. These tests:

  1. keep the hand-maintained manifest honest by deriving ground truth from the
     façade's own `_h.NAME` / `getattr(_h, "NAME")` references (the primary
     guard — you cannot add/remove a wrapper without updating the manifest);
  2. exercise validate_bindings() against synthetic fakes for the
     clean / missing-required / missing-optional cases;
  3. lock the "never invoked at import time" contract.

All pure-Python — no GL, no real host boot.
"""
import ast
import logging
import pathlib
import types

import pytest

import engine.renderer as renderer

_SRC = pathlib.Path(renderer.__file__).read_text()


def _collect_h_refs():
    """Walk engine/renderer.py's AST for the façade's real `_h` references.

    Returns (hard, soft, dynamic):
      hard    - names accessed as `_h.NAME` (attribute access)
      soft    - names accessed as getattr/hasattr(_h, "NAME") string literals
      dynamic - dumps of any getattr/hasattr(_h, <non-literal>) call

    validate_bindings() itself is skipped: it legitimately does
    `hasattr(_h, n)` over a variable, which is infrastructure, not a wrapper.
    AST (not regex) is used so `_h.NAME` mentions inside comments/docstrings and
    the manifest's own string-literal frozensets are ignored.
    """
    hard: set[str] = set()
    soft: set[str] = set()
    dynamic: list[str] = []

    class _Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            if node.name == "validate_bindings":
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
    """A fake `_h` exposing every binding in the manifest."""
    ns = types.SimpleNamespace()
    for name in renderer._REQUIRED_BINDINGS | renderer._OPTIONAL_BINDINGS:
        setattr(ns, name, lambda *a, **k: None)
    return ns


# ── 1. Manifest ↔ façade sync (the primary guard) ────────────────────────────

def test_manifest_matches_facade_references():
    hard, soft, dynamic = _collect_h_refs()
    # `InstanceId` is a type resolved at import; its absence hard-fails `import`,
    # so it is deliberately excluded from the manifest.
    required_expected = hard - soft - {"InstanceId"}
    optional_expected = soft

    assert renderer._REQUIRED_BINDINGS == required_expected, (
        "renderer._REQUIRED_BINDINGS is out of sync with the façade's `_h.NAME` "
        "calls. Added/removed: "
        + str(renderer._REQUIRED_BINDINGS ^ required_expected)
    )
    assert renderer._OPTIONAL_BINDINGS == optional_expected, (
        "renderer._OPTIONAL_BINDINGS is out of sync with the façade's "
        "getattr/hasattr(_h, ...) guards. Added/removed: "
        + str(renderer._OPTIONAL_BINDINGS ^ optional_expected)
    )


def test_no_dynamic_h_access_in_wrappers():
    # A wrapper reaching `_h` through a non-literal name would be invisible to
    # the sync test above — forbid it so the manifest can't silently drift.
    _, _, dynamic = _collect_h_refs()
    assert dynamic == [], (
        "dynamic getattr/hasattr(_h, <non-literal>) found in a renderer wrapper; "
        "the manifest can no longer be verified against it:\n" + "\n".join(dynamic)
    )


# ── 2. validate_bindings() behaviour ─────────────────────────────────────────

def test_validate_clean_when_all_present(monkeypatch):
    monkeypatch.setattr(renderer, "_h", _full_fake())
    assert renderer.validate_bindings() == []
    assert renderer.validate_bindings(strict=True) == []  # no raise


def test_validate_reports_missing_required(monkeypatch, caplog):
    fake = _full_fake()
    delattr(fake, "frame")  # a required binding
    monkeypatch.setattr(renderer, "_h", fake)

    with caplog.at_level(logging.ERROR, logger="engine.renderer"):
        missing = renderer.validate_bindings()
    assert "frame" in missing
    assert "frame" in caplog.text

    with pytest.raises(RuntimeError, match="frame"):
        renderer.validate_bindings(strict=True)


def test_validate_optional_warns_never_raises(monkeypatch, caplog):
    from engine import dev_mode
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)

    fake = _full_fake()
    delattr(fake, "set_cloak_ships")  # an optional binding
    monkeypatch.setattr(renderer, "_h", fake)

    with caplog.at_level(logging.WARNING, logger="engine.renderer"):
        # strict=True must NOT raise for an optional-only gap.
        missing = renderer.validate_bindings(strict=True)
    assert missing == ["set_cloak_ships"]
    assert "set_cloak_ships" in caplog.text


def test_validate_optional_silent_without_dev_mode(monkeypatch, caplog):
    from engine import dev_mode
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: False)

    fake = _full_fake()
    delattr(fake, "set_cloak_ships")
    monkeypatch.setattr(renderer, "_h", fake)

    with caplog.at_level(logging.WARNING, logger="engine.renderer"):
        assert renderer.validate_bindings(strict=True) == ["set_cloak_ships"]
    assert "set_cloak_ships" not in caplog.text  # quiet in production


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
