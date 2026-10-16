"""Diagnostics follow log_dir(); repo-authoring writers refuse in a packaged
build (spec 2026-10-16 per-user data dirs: D1, V1, V3-V6)."""
import json
from pathlib import Path

import pytest

from engine import paths
from engine.appc import decals_writer
from engine.appc import hardpoint_override_writer as hw
from engine.appc import override_routing
from engine.bridge_editor import lighting_doc as ld
from engine.bridge_editor import lighting_writer
from engine.core import stub_telemetry
from engine.ui import decal_editor


@pytest.fixture(autouse=True)
def _clean_telemetry():
    prev = stub_telemetry.ENABLED
    stub_telemetry.reset()
    yield
    stub_telemetry.set_enabled(prev)
    stub_telemetry.reset()


def _hit_and_persist():
    stub_telemetry.set_enabled(True)
    stub_telemetry.record_attr("A", "x")
    stub_telemetry.persist_run()


def test_sidecar_default_is_resolved_at_use(tmp_path, monkeypatch):
    monkeypatch.delenv("DAUNTLESS_STUB_TELEMETRY_FILE", raising=False)
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir()
    second.mkdir()
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(first))
    _hit_and_persist()
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(second))
    _hit_and_persist()
    written = [p for p in tmp_path.rglob("stub_hits.jsonl")]
    assert len(written) == 2
    assert {p.is_relative_to(first) for p in written} == {True, False}


def test_sidecar_env_file_still_wins(tmp_path, monkeypatch):
    target = tmp_path / "mine.jsonl"
    monkeypatch.setenv("DAUNTLESS_STUB_TELEMETRY_FILE", str(target))
    _hit_and_persist()
    assert target.is_file()
    assert stub_telemetry._default_sidecar_path() == str(target)


def test_checkout_sidecar_unchanged(monkeypatch):
    monkeypatch.delenv("DAUNTLESS_STUB_TELEMETRY_FILE", raising=False)
    monkeypatch.delenv(paths.DATA_DIR_ENV, raising=False)
    assert stub_telemetry._default_sidecar_path() == str(
        paths.PROJECT_ROOT / "stub_hits.jsonl")


def test_ai_export_and_nonfinite_dir_follow_log_dir(tmp_path, monkeypatch):
    from engine.ui import ai_inspector_panel
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path))
    assert ai_inspector_panel._export_path() == (
        paths.log_dir() / "ai_inspector_export.json")
    assert paths.log_dir() != paths.PROJECT_ROOT

    import engine.dev_mode as dev_mode
    from engine import renderer
    from engine.dev_keybindings import register_for_frame
    from tests.unit.test_dev_keybindings import _FakeHost
    saved = dict(dev_mode._dev_keybindings)
    try:
        register_for_frame(_FakeHost, None, None)
        handler = dev_mode._dev_keybindings[_FakeHost.keys.KEY_F11]
        handler = handler[0]
        calls = []
        monkeypatch.setattr(renderer, "nonfinite_probe_enabled", lambda: False)
        monkeypatch.setattr(renderer, "set_nonfinite_probe_enabled",
                            lambda on, d=None: calls.append((on, d)))
        handler()
    finally:
        dev_mode._dev_keybindings.clear()
        dev_mode._dev_keybindings.update(saved)
    want = paths.log_dir() / "nonfinite_dumps"
    assert calls == [(True, str(want))]
    assert want.is_dir()


# --- repo authoring writers -------------------------------------------------

def _packaged_root(tmp_path, monkeypatch):
    root = tmp_path / "install"
    root.mkdir()
    (root / paths.PACKAGED_MARKER).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(paths, "PROJECT_ROOT", root)
    return root


def _hardpoint_file(d):
    f = d / "hardpoint_overrides.py"
    f.write_text(hw.emit({"galaxy": {"Center Impulse": [("SetRadius", (0.25,))]}}),
                 encoding="utf-8")
    return f


def _writers(d):
    """(name, call(dir)) for each of the three writers aimed at dir."""
    def hardpoints():
        f = _hardpoint_file(d)
        override_routing.HardpointOverridesFileTarget(str(f)).write(
            "galaxy", [("Center Impulse", "SetRadius", (0.5,))])
        return f

    def decals():
        f = d / "Masks" / "decals.json"
        decals_writer.write_decals(f, [], None)
        return f

    def lighting():
        f = d / "bridge.json"
        lighting_writer.save(
            ld.empty_doc("data/Models/Sets/DBridge/DBridge.nif"), f)
        return f

    return [hardpoints, decals, lighting]


def test_repo_writers_refuse_when_packaged(tmp_path, monkeypatch):
    root = _packaged_root(tmp_path, monkeypatch)
    inside = root / "native"
    inside.mkdir()
    for write in _writers(inside):
        with pytest.raises(paths.RepoWriteInPackagedBuild) as ei:
            write()
        assert isinstance(ei.value, OSError)
        assert "developer authoring saves need a source checkout" in str(ei.value)
    assert not (inside / "Masks").exists()
    assert not (inside / "bridge.json").exists()

    outside = tmp_path / "per-user-mod"
    outside.mkdir()
    for write in _writers(outside):
        assert write().is_file()


def test_repo_writers_unaffected_in_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)   # no marker
    assert not paths.is_packaged()
    for write in _writers(tmp_path):
        assert write().is_file()


def test_refuse_compares_resolved_paths(tmp_path, monkeypatch):
    root = _packaged_root(tmp_path, monkeypatch)
    link = tmp_path / "link"
    link.symlink_to(root)
    with pytest.raises(paths.RepoWriteInPackagedBuild):
        paths.refuse_repo_write_when_packaged(link / "x.json")
    with pytest.raises(paths.RepoWriteInPackagedBuild):
        paths.refuse_repo_write_when_packaged(root / "a" / ".." / "x.json")


# --- fix round 1: log dir may not exist yet ---------------------------------

def test_sidecar_creates_missing_log_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("DAUNTLESS_STUB_TELEMETRY_FILE", raising=False)
    root = tmp_path / "not" / "yet"
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(root))
    assert not paths.log_dir().exists()
    _hit_and_persist()
    assert (paths.log_dir() / "stub_hits.jsonl").is_file()


def test_ai_export_creates_missing_log_dir(tmp_path, monkeypatch):
    from engine.ui import ai_inspector_panel as mod
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path / "not" / "yet"))
    monkeypatch.setattr(mod, "collect_all_ship_ai", lambda: [{"ship_name": "A"}])
    panel = mod.AIInspectorPanel()
    panel.open()
    panel.dispatch_event("export")
    assert (paths.log_dir() / "ai_inspector_export.json").is_file()


def test_ai_export_failure_reports_path(tmp_path, monkeypatch, capsys):
    from engine.ui import ai_inspector_panel as mod
    blocker = tmp_path / "file"
    blocker.write_text("x")
    target = blocker / "e.json"
    paths._reset_write_failure_reports()
    monkeypatch.setattr(mod, "_export_path", lambda: target)
    monkeypatch.setattr(mod, "collect_all_ship_ai", lambda: [])
    panel = mod.AIInspectorPanel()
    panel.open()
    panel.dispatch_event("export")
    err = capsys.readouterr().err
    assert "could not write" in err and str(target) in err
    assert "export FAILED" in err


def test_heatmap_sidecar_default_follows_writer(tmp_path, monkeypatch, capsys):
    import sys
    sys.path.insert(0, str(paths.PROJECT_ROOT / "tools"))
    try:
        import stub_heatmap
    finally:
        sys.path.pop(0)
    monkeypatch.delenv("DAUNTLESS_STUB_TELEMETRY_FILE", raising=False)
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path))
    stub_heatmap.main(["--out", str(tmp_path / "out.md")])
    assert str(paths.log_dir() / "stub_hits.jsonl") in capsys.readouterr().out
