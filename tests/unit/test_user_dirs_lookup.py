from pathlib import Path, PureWindowsPath

import pytest

from engine import paths

HOME = Path("/h")
KEYS = {"config", "saves", "mods", "cache", "logs"}


def _kf(mapping):
    return lambda name: mapping.get(name)


def test_windows_uses_known_folders():
    d = paths.os_user_dirs(
        platform="win32", env={}, home=Path("C:/U"),
        known_folder=_kf({"RoamingAppData": Path("C:/R"),
                          "LocalAppData": Path("C:/L")}))
    assert d["config"] == Path("C:/R/Dauntless")
    assert d["saves"] == Path("C:/R/Dauntless/saves")
    assert d["mods"] == Path("C:/R/Dauntless/mods")
    assert d["cache"] == Path("C:/L/Dauntless/Cache")
    assert d["logs"] == Path("C:/L/Dauntless/Logs")


def test_windows_falls_back_to_env_when_known_folder_fails():
    d = paths.os_user_dirs(
        platform="win32", env={"APPDATA": "C:/E/R", "LOCALAPPDATA": "C:/E/L"},
        home=Path("C:/U"), known_folder=_kf({}))
    assert d["config"] == Path("C:/E/R/Dauntless")
    assert d["cache"] == Path("C:/E/L/Dauntless/Cache")


def test_windows_ignores_empty_or_relative_env():
    d = paths.os_user_dirs(
        platform="win32", env={"APPDATA": "", "LOCALAPPDATA": "rel"},
        home=Path("C:/U"), known_folder=_kf({}))
    assert d["config"] == Path("C:/U/AppData/Roaming/Dauntless")
    assert d["logs"] == Path("C:/U/AppData/Local/Dauntless/Logs")


def test_macos_layout():
    d = paths.os_user_dirs(platform="darwin", env={}, home=HOME)
    base = HOME / "Library" / "Application Support" / "Dauntless"
    assert d["config"] == base
    assert d["saves"] == base / "saves"
    assert d["mods"] == base / "mods"
    assert d["cache"] == HOME / "Library" / "Caches" / "Dauntless"
    assert d["logs"] == HOME / "Library" / "Logs" / "Dauntless"


def test_linux_xdg_set():
    env = {"XDG_CONFIG_HOME": "/x/c", "XDG_DATA_HOME": "/x/d",
           "XDG_CACHE_HOME": "/x/k", "XDG_STATE_HOME": "/x/s"}
    d = paths.os_user_dirs(platform="linux", env=env, home=HOME)
    assert d["config"] == Path("/x/c/dauntless")
    assert d["saves"] == Path("/x/d/dauntless/saves")
    assert d["mods"] == Path("/x/d/dauntless/mods")
    assert d["cache"] == Path("/x/k/dauntless")
    assert d["logs"] == Path("/x/s/dauntless/logs")


@pytest.mark.parametrize("val", [None, "", "relative/x"])
def test_linux_xdg_unset_empty_or_relative_uses_defaults(val):
    names = ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME")
    env = {} if val is None else {n: val for n in names}
    d = paths.os_user_dirs(platform="linux", env=env, home=HOME)
    assert d["config"] == HOME / ".config" / "dauntless"
    assert d["saves"] == HOME / ".local" / "share" / "dauntless" / "saves"
    assert d["mods"] == HOME / ".local" / "share" / "dauntless" / "mods"
    assert d["cache"] == HOME / ".cache" / "dauntless"
    assert d["logs"] == HOME / ".local" / "state" / "dauntless" / "logs"


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_every_result_is_absolute(platform):
    home = Path("C:/U") if platform == "win32" else HOME
    d = paths.os_user_dirs(platform=platform, env={}, home=home,
                           known_folder=_kf({}))
    assert set(d) == KEYS
    for v in d.values():
        if platform == "win32":
            assert PureWindowsPath(str(v)).is_absolute(), v
        else:
            assert v.is_absolute(), v
