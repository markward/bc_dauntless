"""Smoke test that host_loop initializes audio and ticks the listeners.

We don't run the full host loop — we exercise the audio init/tick helpers
that host_loop.py exposes for testability.
"""
import os
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")


def test_host_loop_exposes_audio_helpers():
    from engine import host_loop
    assert hasattr(host_loop, "init_audio")
    assert hasattr(host_loop, "tick_audio")
    assert hasattr(host_loop, "shutdown_audio")


def test_init_audio_uses_null_backend_when_env_set(monkeypatch):
    monkeypatch.setenv("OPEN_STBC_AUDIO", "0")
    _dauntless_host = pytest.importorskip("_dauntless_host")
    from engine import host_loop
    host_loop.init_audio()
    log_ops = [e["op"] for e in _dauntless_host.audio.debug_command_log()]
    assert "init" in log_ops
    host_loop.shutdown_audio()


def test_tick_audio_pushes_listener_pose(monkeypatch):
    monkeypatch.setenv("OPEN_STBC_AUDIO", "0")
    _dauntless_host = pytest.importorskip("_dauntless_host")
    from engine import host_loop
    host_loop.init_audio()
    _dauntless_host.audio.clear_command_log()
    host_loop.tick_audio(
        camera_position=(0.0, 0.0, 0.0),
        camera_forward=(0.0, 0.0, -1.0),
        camera_up=(0.0, 1.0, 0.0),
        dt=0.016,
        player=None,
    )
    assert any(e["op"] == "set_listener"
               for e in _dauntless_host.audio.debug_command_log())
    host_loop.shutdown_audio()


def test_register_default_sounds_is_gone():
    # The hardcoded stand-in is replaced by the real LoadBridge.LoadSounds()
    # + LoadTacticalSounds.LoadSounds() paths.
    import engine.audio.tg_sound as tg
    assert not hasattr(tg, "register_default_sounds")


def test_init_audio_backend_is_idempotent(monkeypatch):
    monkeypatch.setenv("OPEN_STBC_AUDIO", "0")
    _dauntless_host = pytest.importorskip("_dauntless_host")
    from engine import host_loop
    host_loop.init_audio_backend()
    _dauntless_host.audio.clear_command_log()
    host_loop.init_audio_backend()  # second call must not re-init
    ops = [e["op"] for e in _dauntless_host.audio.debug_command_log()]
    assert "init" not in ops
    host_loop.shutdown_audio()
