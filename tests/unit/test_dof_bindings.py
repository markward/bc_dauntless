"""The DOF façade must be manifest-complete and must not crash headless.

engine/renderer.py's wrappers are no-ops when the extension module is absent
(unit tests, headless import contexts) and hard calls when it is present. Both
paths are exercised here so a missing binding shows up as a red test rather
than a silently dead feature at runtime.
"""
import engine.renderer as r


def test_dof_bindings_are_in_the_required_manifest():
    for name in ("dof_set_enabled", "dof_enabled", "dof_set_params"):
        assert name in r._REQUIRED_BINDINGS, (
            f"{name} missing from _REQUIRED_BINDINGS -- validate_bindings() "
            "would not catch a stale build that dropped it"
        )


def test_set_dof_params_forwards_every_field(monkeypatch):
    seen = {}

    class _FakeHost:
        def dof_set_params(self, *args):
            seen["args"] = args

    monkeypatch.setattr(r, "_h", _FakeHost())
    r.set_dof_params(120.0, 0.5, 1.0, 1.0, 0.4, 0.008)

    assert seen["args"] == (120.0, 0.5, 1.0, 1.0, 0.4, 0.008)


def test_set_dof_enabled_coerces_to_bool(monkeypatch):
    seen = {}

    class _FakeHost:
        def dof_set_enabled(self, v):
            seen["v"] = v

    monkeypatch.setattr(r, "_h", _FakeHost())
    r.set_dof_enabled(1)

    assert seen["v"] is True
